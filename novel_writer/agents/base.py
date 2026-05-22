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

    async def execute(
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

            response = await self.llm.chat(
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
                    response_preview=result.content if self.logger.debug_mode else "",
                    max_tokens=self.llm.default_max_tokens,
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
            if self._looks_like_notes(first) and not self._looks_like_notes(second):
                return AgentResult(success=True, content=second, notes=first)
            return AgentResult(success=True, content=first, notes=second)
        if len(blocks) == 1:
            candidate = blocks[0].strip()
            if self._looks_like_notes(candidate):
                return AgentResult(success=True, content="", notes=candidate)
            return AgentResult(success=True, content=candidate, notes="")
        return self._split_notes_and_content(raw)

    _NOTE_PREFIXES = (
        "[ACTIVE]", "[CONTRADICTION]", "[待补充]", "[推断]",
        "[ARC]", "[STYLE]", "[VOICE]", "[CONSISTENCY]",
        "[FORESHADOWING]", "[RESOLVED]",
        "# 记忆更新", "[记忆更新]", "# 剧情笔记", "[剧情笔记]",
    )

    @classmethod
    def _normalize_brackets(cls, text: str) -> str:
        return text.replace("【", "[").replace("】", "]")

    _LIST_PREFIX_RE = re.compile(r'^[-*]\s+|^\d+[.)]\s*|^>\s*|^#{1,6}\s+')

    @classmethod
    def _line_starts_with_note(cls, line: str) -> bool:
        stripped = cls._normalize_brackets(line.strip())
        if not stripped:
            return False
        content = cls._LIST_PREFIX_RE.sub("", stripped, count=1)
        return any(content.startswith(p) for p in cls._NOTE_PREFIXES)

    @classmethod
    def _looks_like_notes(cls, text: str) -> bool:
        if not text:
            return False
        lines = [ln for ln in text.split("\n") if ln.strip()]
        sample = lines[:7]
        if not sample:
            return False
        match_count = sum(1 for ln in sample if cls._line_starts_with_note(ln))
        return match_count >= 2 or cls._line_starts_with_note(sample[0])

    @classmethod
    def _split_notes_and_content(cls, raw: str) -> "AgentResult":
        text = raw.strip()
        if not text:
            return AgentResult(success=True, content="", notes="")

        if not cls._looks_like_notes(text):
            return AgentResult(success=True, content=text, notes="")

        lines = text.split("\n")
        content_start = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if cls._line_starts_with_note(stripped):
                continue
            if (stripped.startswith("#") or
                    len(stripped) >= 30 or
                    bool(re.search(r'[一-鿿]', stripped))):
                content_start = i
                break

        if content_start is not None:
            notes_part = "\n".join(lines[:content_start]).strip()
            content_part = "\n".join(lines[content_start:]).strip()
            if not cls._looks_like_notes(content_part):
                return AgentResult(success=True, content=content_part, notes=notes_part)

        return AgentResult(success=True, content="", notes=text)
