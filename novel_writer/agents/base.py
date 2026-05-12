from abc import ABC, abstractmethod
from dataclasses import dataclass

from novel_writer.core.llm import LLMClient


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


class BaseAgent(ABC):
    """Agent 抽象基类"""

    def __init__(self, name: str, memory_file: str, llm: LLMClient):
        self.name = name
        self.memory_file = memory_file
        self.llm = llm

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
        try:
            messages = self._build_messages(task, context, memory)
            response = self.llm.chat(messages, system=self.system_prompt)
            return self._parse_response(response)
        except Exception as e:
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

    def _parse_response(self, raw: str) -> AgentResult:
        # 用 ``` 分割：第一段内容，第二段笔记
        parts = raw.split("```")
        if len(parts) >= 3:
            content = parts[1].strip()
            notes = parts[3].strip() if len(parts) >= 5 else ""
            return AgentResult(success=True, content=content, notes=notes)
        return AgentResult(success=True, content=raw.strip(), notes="")
