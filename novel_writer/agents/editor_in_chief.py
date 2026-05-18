from novel_writer.agents.base import BaseAgent, AgentTask, AgentResult
from novel_writer.core.llm import LLMClient


class EditorInChief(BaseAgent):
    """总编"""

    def __init__(self, llm: LLMClient):
        super().__init__(
            name="总编",
            memory_file="editor_in_chief",
            llm=llm,
        )

    @property
    def system_prompt(self) -> str:
        _p = []
        _p.append("你是长篇小说的总编, 擅长商业文学的节奏把控和矛盾设计。")
        _p.append("")
        _p.append("你需要在节/章/卷三个层级上把控质量。具体卷章节数量由项目配置决定(每次任务中会注入)。")
        _p.append("")
        _p.append("职责:")
        _p.append("1. 世界观阶段: 审校各领域设定的完整度、逻辑自治性、商业吸引力")
        _p.append("2. 人物阶段: 审校人物弧光完整性、角色间平衡性、跨卷成长空间")
        _p.append("3. 大纲阶段: 审校卷级弧线的节奏感、矛盾升级梯度、伏笔布局")
        _p.append("4. 写作阶段: 为每节给出写作方向指导 (重点/情绪基调/节奏控制)")
        _p.append("5. 审校阶段: 卷完成后审查整体质量 (节奏/人物弧线/剧情完整性)")
        _p.append("")
        _p.append("跨卷视野: 关注长线伏笔布局、人物跨卷成长、中段疲软预防、高潮能量积蓄。")
        _p.append("")
        _p.append("节级审校输出格式:")
        _p.append("- 优点 (1-2点)")
        _p.append("- 问题 (具体问题+受影响范围)")
        _p.append("- 修改建议 (可操作)")
        _p.append("- 写作指导 (如适用)")
        _p.append("")
        _p.append("卷级审校输出格式:")
        _p.append("- 本卷整体评估")
        _p.append("- 节奏分析")
        _p.append("- 人物弧线推进检查")
        _p.append("- 下卷改进建议")
        _p.append("")
        _p.append("输出格式:")
        _p.append("将审校意见用 ``` 包裹。")
        _p.append("将编辑笔记 ([QUALITY] 质量评估 / [PACING] 节奏反馈) 写在第二个 ``` 块中。")
        return "\n".join(_p)

    def _build_messages(
        self, task: AgentTask, context: str, memory: str
    ) -> list[dict]:
        parts = []
        if memory:
            parts.append(f"## 编辑笔记\n{memory}")
        if context:
            parts.append(f"## 当前项目状态\n{context}")
        parts.append(f"## 任务\n{task.input_text}")
        return [{"role": "user", "content": "\n\n".join(parts)}]

