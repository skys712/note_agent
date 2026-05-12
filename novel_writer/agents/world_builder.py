from novel_writer.agents.base import BaseAgent, AgentTask, AgentResult
from novel_writer.core.llm import LLMClient


class WorldBuilder(BaseAgent):
    """世界观管理员"""

    def __init__(self, llm: LLMClient):
        super().__init__(
            name="世界管理员",
            memory_file="world_builder",
            llm=llm,
        )

    @property
    def system_prompt(self) -> str:
        _p = []
        _p.append("你是百万字长篇小说的世界观管理者, 擅长构建自治的虚构世界。")
        _p.append("")
        _p.append("世界观按领域拆分(geography/magic_system/politics/history/races/culture/glossary), 每次只处理一个领域, 确保本领域内容自治且与其他领域一致。")
        _p.append("")
        _p.append("职责:")
        _p.append("1. 逐领域生成详细设定 (每个领域内容 500-3000 字)")
        _p.append("2. 发现逻辑矛盾时明确指出具体矛盾和修改方案")
        _p.append("3. 检查人物设定和剧情场景是否违反世界规则")
        _p.append("4. 在记忆文件中用 [ACTIVE] 标记活跃规则, [CONTRADICTION] 标记已发现矛盾")
        _p.append("5. 维护术语表 glossary.md, 确保专有名词全作一致")
        _p.append("6. 生成世界历史时间线 (world/timeline.md): 从创世神话到预期故事结局, 跨越六个时代 (创世神话/远古纪元/中古纪元/近世纪元/故事时代/预言与终局), 每个关键时间点需要有故事级别的叙事描述")
        _p.append("")
        _p.append("输出格式:")
        _p.append("将生成/修订的设定内容用 ``` 包裹。")
        _p.append("将需要写入记忆的规则或矛盾记录在第二个 ``` 块中, 格式为 [ACTIVE] 或 [CONTRADICTION] 开头。")
        return "\n".join(_p)

    def _build_messages(
        self, task: AgentTask, context: str, memory: str
    ) -> list[dict]:
        parts = []
        if memory:
            parts.append(f"## 已确认的设定记录\n{memory}")
        if context:
            parts.append(f"## 当前项目状态\n{context}")
        parts.append(f"## 任务\n{task.input_text}")
        return [{"role": "user", "content": "\n\n".join(parts)}]

