from novel_writer.agents.base import BaseAgent, AgentTask, AgentResult
from novel_writer.core.llm import LLMClient


class PlotWriter(BaseAgent):
    """剧情编剧"""

    def __init__(self, llm: LLMClient):
        super().__init__(
            name="剧情编剧",
            memory_file="plot_writer",
            llm=llm,
        )

    @property
    def system_prompt(self) -> str:
        _p = []
        _p.append("你是百万字长篇小说的剧情编剧, 擅长设计强冲突、高转折的长线剧情。")
        _p.append("")
        _p.append("大纲为三层结构: 全书梗概(synopsis.md) -> 卷弧线(outline/volume_N.md) -> 章节场景设计(volumes/vol_N/ch_M/_meta.md)。逐卷生成, 写完全卷再设计下一卷。")
        _p.append("")
        _p.append("职责:")
        _p.append("1. 设计全书梗概 (500-1000字), 明确主线/核心矛盾/结局预设")
        _p.append("2. 逐卷设计弧线: 本卷核心冲突/角色成长/剧情推进量")
        _p.append("3. 逐章设计场景序列 (3-5个场景), 每个场景标注: POV/地点/出场人物/世界观元素引用/核心冲突/字数目标")
        _p.append("4. 管理伏笔系统: 用 [FORESHADOWING] 记录埋入, [ACTIVE] 追踪未完成剧情线, [RESOLVED] 标记已完结线")
        _p.append("5. 确保每章每节都有钩子, 矛盾逐级升级不拖沓")
        _p.append("")
        _p.append("场景设计格式 (_meta.md):")
        _p.append("## 场景N (section_00N): 场景标题")
        _p.append("- POV: 视角人物")
        _p.append("- 地点: 具体地点")
        _p.append("- 出场人物: 人物名列表")
        _p.append("- 世界观元素: [领域:具体元素]")
        _p.append("- 核心冲突: 一句话冲突描述")
        _p.append("- 字数目标: 3000-5000")
        _p.append("")
        _p.append("输出格式:")
        _p.append("将大纲/场景设计用 ``` 包裹。")
        _p.append("将剧情笔记 (伏笔/线索/节奏) 写在第二个 ``` 块中。")
        return "\n".join(_p)

    def _build_messages(
        self, task: AgentTask, context: str, memory: str
    ) -> list[dict]:
        parts = []
        if memory:
            parts.append(f"## 剧情笔记\n{memory}")
        if context:
            parts.append(f"## 当前项目状态\n{context}")
        parts.append(f"## 任务\n{task.input_text}")
        return [{"role": "user", "content": "\n\n".join(parts)}]

