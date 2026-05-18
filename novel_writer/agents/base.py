import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from novel_writer.core.llm import LLMClient, LLMResponse


@dataclass
class AgentTask:
    """Agent 任务"""
    action: str
    input_text: str


@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool
    content: str
    notes: str = ""
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: float = 0.0


class BaseAgent(ABC):
    """Agent 抽象基类"""

    def __init__(self, name: str, memory_file: str, llm: LLMClient):
        self.name = name
        self.memory_file = memory_file
        self.llm = llm
        self.logger = None

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        ...

    def execute(
        self,
        task: AgentTask,
        context: str = "",
        memory: str = "",
    ) -> AgentResult:
        t0 = time.time()
        try:
            messages = self._build_messages(task, context, memory)

            on_progress = None
            if self.logger:
                def _progress(total_chars: int) -> None:
                    self.logger.stream_progress(total_chars)
                on_progress = _progress

            response = self.llm.chat(
                messages, system=self.system_prompt, on_progress=on_progress,
            )
            elapsed = (time.time() - t0) * 1000

            if self.logger:
                self.logger.stream_end(len(response.content))

            result = self._parse_response(response)
            result.input_tokens = response.input_tokens
            result.output_tokens = response.output_tokens
            result.duration_ms = elapsed

            if self.logger:
                self.logger.step_end(
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    result_chars=len(result.content),
                    success=True,
                )
                self.logger.record_call(
                    agent_name=self.name,
                    action=task.action,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    duration_ms=elapsed,
                    result_chars=len(result.content),
                    success=True,
                )
            return result
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            if self.logger:
                self.logger.stream_end(0)
                self.logger.step_end(success=False, error=str(e))
                self.logger.record_call(
                    agent_name=self.name,
                    action=task.action,
                    input_tokens=0,
                    output_tokens=0,
                    duration_ms=elapsed,
                    result_chars=0,
                    success=False,
                    error=str(e),
                )
            return AgentResult(success=False, content="", error=str(e))

    def _build_messages(
        self, task: AgentTask, context: str, memory: str
    ) -> list[dict]:
        parts = []
        if memory:
            parts.append(f"## 你的记忆\n{memory}")
        if context:
            parts.append(f"## 当前项目状态\n{context}")
        parts.append(f"## 任务\n{task.input_text}")
        return [{"role": "user", "content": "\n\n".join(parts)}]

    _RE_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)

    def _parse_response(self, response: LLMResponse) -> AgentResult:
        raw = response.content
        blocks = self._RE_FENCE.findall(raw)
        if len(blocks) >= 2:
            first = blocks[0].strip()
            second = blocks[1].strip()
            # 如果第一个 block 看起来像笔记（[ACTIVE]/[CONTRADICTION] 开头），
            # 而第二个不像，则交换：block[1] 才是正文
            if self._looks_like_notes(first) and not self._looks_like_notes(second):
                return AgentResult(success=True, content=second, notes=first)
            return AgentResult(success=True, content=first, notes=second)
        if len(blocks) == 1:
            candidate = blocks[0].strip()
            if self._looks_like_notes(candidate):
                return AgentResult(success=True, content="", notes=candidate)
            return AgentResult(success=True, content=candidate, notes="")
        # 没有 ``` 块: 尝试智能拆分笔记和正文
        return self._split_notes_and_content(raw)

    # 所有 Agent 可能使用的笔记标记前缀
    _NOTE_PREFIXES = (
        "[ACTIVE]", "[CONTRADICTION]", "[待补充]", "[推断]",
        "[ARC]", "[STYLE]", "[VOICE]", "[CONSISTENCY]",
        "[FORESHADOWING]", "[RESOLVED]",
        "# 记忆更新", "[记忆更新]", "# 剧情笔记", "[剧情笔记]",
    )

    @classmethod
    def _normalize_brackets(cls, text: str) -> str:
        """统一全角括号为半角，避免模型混用 【】 和 [] 导致匹配失败"""
        return text.replace("【", "[").replace("】", "]")

    @classmethod
    def _looks_like_notes(cls, text: str) -> bool:
        """检测文本是否为 Agent 记忆笔记而非正文内容"""
        if not text:
            return False
        first_line = cls._normalize_brackets(text.split("\n")[0].strip())
        return any(first_line.startswith(p) for p in cls._NOTE_PREFIXES)

    @classmethod
    def _split_notes_and_content(cls, raw: str) -> "AgentResult":
        """无 ``` 块时，拆分笔记和正文的混合响应"""
        text = raw.strip()
        if not text:
            return AgentResult(success=True, content="", notes="")

        # 不以笔记开头 → 全部当正文
        if not cls._looks_like_notes(text):
            return AgentResult(success=True, content=text, notes="")

        # 以笔记开头，尝试找分割点

        lines = text.split("\n")
        # 找到第一个"非笔记"行作为正文起点
        content_start = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            # 以笔记标记开头 → 仍是笔记区
            normalized = cls._normalize_brackets(stripped)
            if any(normalized.startswith(p) for p in cls._NOTE_PREFIXES):
                continue
            # 找到正文了：标题行、或包含足够中文内容的行
            if (stripped.startswith("#") or
                    len(stripped) >= 30 or
                    bool(re.search(r'[一-鿿]', stripped))):
                content_start = i
                break

        if content_start is not None:
            notes_part = "\n".join(lines[:content_start]).strip()
            content_part = "\n".join(lines[content_start:]).strip()
            # 验证正文部分不像纯笔记
            if not cls._looks_like_notes(content_part):
                return AgentResult(success=True, content=content_part, notes=notes_part)

        # 无法拆分 → 全部当笔记
        return AgentResult(success=True, content="", notes=text)
