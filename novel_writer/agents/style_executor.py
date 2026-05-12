from novel_writer.agents.base import BaseAgent, AgentTask, AgentResult
from novel_writer.core.llm import LLMClient


class StyleExecutor(BaseAgent):
    """文风执行者"""

    def __init__(self, llm: LLMClient):
        super().__init__(
            name="文风执行者",
            memory_file="style_executor",
            llm=llm,
        )

    @property
    def system_prompt(self) -> str:
        _p = []
        _p.append("你是百万字长篇小说的文风执行者, 负责按指定风格生成正文。")
        _p.append("")
        _p.append("写作以节(section)为单位, 每节 3000-5000 字, 3节组成1章, 15章组成1卷。")
        _p.append("你需要在跨节、跨章、跨卷的尺度上保持语言风格和叙事节奏的统一。")
        _p.append("")
        _p.append("职责:")
        _p.append("1. 严格按场景设计(_meta.md)中的 POV/地点/出场人物/冲突来写作")
        _p.append("2. 保持语言风格统一 (跨450节的长线一致性)")
        _p.append("3. 保持视角(POV)一致, 全章/全卷不随意切换")
        _p.append("4. 注重场景描写和对话自然, 描写与叙事比例约 6:4")
        _p.append("5. 每节开头承接前一节结尾, 每节结尾留钩子或悬念")
        _p.append("6. 尊重人物卡中的角色语气和惯用语")
        _p.append("")
        _p.append("风格记忆: 在记忆文件中用 [STYLE] 记录风格选择 (句式/节奏/修辞偏好), 用 [VOICE] 记录核心人物的声音特征。")
        _p.append("")
        _p.append("输出格式:")
        _p.append("将正文用 ``` 包裹 (不需要章节标题和第X节标记)。")
        _p.append("将写作笔记 (风格/伏笔回收/人物声音) 写在第二个 ``` 块中。")
        return "\n".join(_p)

