from novel_writer.agents.base import BaseAgent, AgentTask, AgentResult
from novel_writer.core.llm import LLMClient


class CharacterDirector(BaseAgent):
    """人物导演"""

    def __init__(self, llm: LLMClient):
        super().__init__(
            name="人物导演",
            memory_file="character_director",
            llm=llm,
        )

    @property
    def system_prompt(self) -> str:
        _p = []
        _p.append("你是百万字长篇小说的人物导演, 确保角色行为始终符合人物卡设定。")
        _p.append("")
        _p.append("人物卡按单人单文件管理(cards/<char_id>.md), 通过 characters/index.md 索引。")
        _p.append("每人物的弧线需跨卷追踪(最长10卷150章), 性格发展可以渐变但不能突变。")
        _p.append("")
        _p.append("职责:")
        _p.append("1. 创建丰满的人物卡: 姓名/角色定位/性格特征/背景故事/人物弧光/说话风格")
        _p.append("2. 生成和维护人物关系矩阵(relationships.md)及势力文件(factions/)")
        _p.append("3. 检查章节场景设计中角色行为是否偏离人物卡")
        _p.append("4. 追踪每个人物跨卷的成长弧线, 在记忆中用 [ARC] 记录里程碑")
        _p.append("5. 用 [CONSISTENCY] 记录跨卷行为一致性观察")
        _p.append("")
        _p.append("注意: 百万字长篇中角色应有渐进式成长, 每个关键决策需要有前文铺垫。")
        _p.append("")
        _p.append("输出格式:")
        _p.append("将人物卡/关系矩阵等内容用 ``` 包裹。")
        _p.append("将人物观察和弧线追踪记录在第二个 ``` 块中 (以 [ARC] 或 [CONSISTENCY] 开头)。")
        return "\n".join(_p)

    def _build_messages(
        self, task: AgentTask, context: str, memory: str
    ) -> list[dict]:
        parts = []
        if memory:
            parts.append(f"## 人物观察笔记\n{memory}")
        if context:
            parts.append(f"## 当前项目状态\n{context}")
        parts.append(f"## 任务\n{task.input_text}")
        return [{"role": "user", "content": "\n\n".join(parts)}]

