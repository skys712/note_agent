from novel_writer.agents.base import AgentResult, BaseAgent
from novel_writer.core.llm import LLMResponse


def _parse(raw: str) -> AgentResult:
    """快捷入口：用 BaseAgent._parse_response 的子类绕过抽象方法"""
    class _TestAgent(BaseAgent):
        @property
        def system_prompt(self) -> str:
            return ""

    agent = _TestAgent(name="test", memory_file="test", llm=None)  # type: ignore[arg-type]
    return agent._parse_response(LLMResponse(content=raw))


class TestParseResponse:
    """_parse_response 解析逻辑测试"""

    def test_two_blocks_content_first(self):
        result = _parse(
            "```\n这是正文内容。\n```\n```\n[ACTIVE] 规则一\n[CONTRADICTION] 矛盾一\n```"
        )
        assert result.success
        assert "这是正文内容" in result.content
        assert "[ACTIVE] 规则一" in result.notes

    def test_two_blocks_notes_first_swap(self):
        """当第一个块看起来像笔记、第二个不像时，自动交换"""
        result = _parse(
            "```\n[ACTIVE] 规则\n[ARC] 弧线更新\n```\n```\n正文内容在这里。\n```"
        )
        assert result.success
        assert "正文内容在这里" in result.content
        assert "[ACTIVE] 规则" in result.notes

    def test_single_block_is_content(self):
        result = _parse("```\n这是一段纯正文内容，没有任何笔记标记。\n```")
        assert result.success
        assert "纯正文内容" in result.content
        assert result.notes == ""

    def test_single_block_is_notes(self):
        result = _parse("```\n[ACTIVE] 规则\n[ARC] 弧线\n```")
        assert result.success
        assert result.content == ""
        assert "[ACTIVE] 规则" in result.notes

    def test_no_fence_blocks(self):
        result = _parse("这是一段没有围栏块的正文内容，包含多个句子。")
        assert result.success
        assert "正文内容" in result.content
        assert result.notes == ""

    def test_no_fence_looks_like_notes(self):
        result = _parse("[ACTIVE] 重要规则\n[ARC] 人物弧线推进\n[CONTRADICTION] 矛盾")
        assert result.success
        assert result.content == ""
        assert "重要规则" in result.notes

    def test_empty_response(self):
        result = _parse("")
        assert result.success
        assert result.content == ""
        assert result.notes == ""

    def test_mixed_notes_and_content_no_fence(self):
        """无围栏时，笔记标记后跟着正文，应正确拆分"""
        result = _parse(
            "[ACTIVE] 规则一\n[记忆更新] 更新条目\n\n第一卷第三章描写了主角初入江湖的场景。"
        )
        assert result.success
        assert "初入江湖" in result.content
        assert "[ACTIVE] 规则一" in result.notes

    def test_chinese_content_detection(self):
        """中文字符检测：含中文的块判定为正文"""
        result = _parse("```\n这是一个测试正文，包含大量中文字符。主角登场。\n```")
        assert result.success
        assert "主角登场" in result.content

    def test_two_blocks_both_content_like(self):
        """两个块都不像笔记，都按正文处理"""
        result = _parse(
            "```\n第一章内容。\n```\n```\n第二章内容。\n```"
        )
        assert result.success
        assert "第一章内容" in result.content
        assert "第二章内容" in result.notes


class TestLineStartsWithNote:
    """_line_starts_with_note 静态方法测试"""

    def test_active_prefix(self):
        assert BaseAgent._line_starts_with_note("[ACTIVE] 规则描述")

    def test_contradiction_prefix(self):
        assert BaseAgent._line_starts_with_note("[CONTRADICTION] 矛盾")

    def test_chinese_prefix(self):
        assert BaseAgent._line_starts_with_note("[待补充] 需要补充的内容")

    def test_arc_prefix(self):
        assert BaseAgent._line_starts_with_note("[ARC] 弧线更新")

    def test_fullwidth_brackets(self):
        """全角方括号【】应被标准化为半角[]"""
        assert BaseAgent._line_starts_with_note("【ACTIVE】 规则")

    def test_list_prefix(self):
        """列表标记前缀（-, *, 1.）应被忽略"""
        assert BaseAgent._line_starts_with_note("- [ACTIVE] 规则")
        assert BaseAgent._line_starts_with_note("* [ACTIVE] 规则")
        assert BaseAgent._line_starts_with_note("1. [ACTIVE] 规则")

    def test_heading_prefix(self):
        """# heading 前缀应被忽略"""
        assert BaseAgent._line_starts_with_note("# [ACTIVE] 规则")

    def test_not_note_line(self):
        assert not BaseAgent._line_starts_with_note("这是一段普通正文")
        assert not BaseAgent._line_starts_with_note("")


class TestLooksLikeNotes:
    """_looks_like_notes 启发式判断测试"""

    def test_multiple_note_lines(self):
        assert BaseAgent._looks_like_notes(
            "[ACTIVE] 规则一\n[ARC] 弧线\n[CONTRADICTION] 矛盾\n"
        )

    def test_single_note_line_first(self):
        assert BaseAgent._looks_like_notes("[ACTIVE] 开头的笔记\n其他内容")

    def test_empty_text(self):
        assert not BaseAgent._looks_like_notes("")

    def test_content_only(self):
        assert not BaseAgent._looks_like_notes("这是一段纯正文内容。")
