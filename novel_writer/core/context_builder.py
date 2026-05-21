from novel_writer.core.context import ProjectContext


class ContextBuilder:
    """P1-P4 分层上下文注入引擎，Token 预算约 6000"""

    TOKEN_BUDGET = 6000

    def build(
        self,
        ctx: ProjectContext,
        agent_id: str,
        vol: int,
        ch: int,
        sec: int,
        constraints: str = "",
    ) -> str:
        parts: list[str] = []

        # === P0: 故事级约束（最高优先级，始终最先注入） ===
        if constraints:
            parts.append(constraints)

        # === P1: 场景元数据 + 前一节 + 时间线（总是注入） ===
        p1 = self._build_p1(ctx, vol, ch, sec)
        parts.append(p1)

        # === P2: 卷弧线 + 出场人物 + 相关世界观 ===
        p2 = self._build_p2(ctx, vol, ch)
        parts.append(p2)

        # === P3: 全局索引 + 关系摘要 ===
        p3 = self._build_p3(ctx, agent_id, ch, vol)
        if p3:
            parts.append(p3)

        # === P4: Agent 记忆 ===
        p4 = self._build_p4(ctx, agent_id)
        if p4:
            parts.append(p4)

        return "\n\n---\n\n".join(parts)

    # ---- P1: 即时上下文 ----

    def _build_p1(self, ctx: ProjectContext, vol: int, ch: int, sec: int) -> str:
        lines = []

        # 剧情状态 (所有 Agent 都需要) — 读取本节对应的前置 state 版本
        state = ctx.get_state_for_section(vol, ch, sec)
        if state and "尚未开始" not in state:
            lines.append(f"## 当前剧情状态\n{state[:2000]}")

        # 碎片参考摘要 (所有 Agent 都需要)
        frag_summary = ctx.get_fragments_summary()
        if frag_summary and "尚无碎片" not in frag_summary:
            lines.append(f"## 碎片参考\n{frag_summary[:8000]}")

        # 本章场景设计 — 需要足够大的截断窗口以确保多节场景概要不被切断
        chapter_meta = ctx.get_chapter_meta(vol, ch)
        if chapter_meta:
            lines.append(f"## 本章场景设计\n{chapter_meta[:12000]}")
        else:
            vol_outline = ctx.get_volume_outline(vol)
            if vol_outline:
                chapter_outline = self._extract_chapter_outline(vol_outline, ch)
                lines.append(f"## 本章大纲 (大纲中提取)\n{chapter_outline}")

        # 前一节内容
        prev = ctx.get_prev_section(vol, ch, sec)
        if prev:
            lines.append(f"## 前一节结尾\n{prev[-1500:]}")

        # 时间线
        timeline = ctx.get_timeline()
        if timeline and "尚未记录" not in timeline:
            lines.append(f"## 时间线\n{timeline[:500]}")

        return "\n\n".join(lines) if lines else ""

    # ---- P2: 卷级上下文 + 出场人物 + 世界观 ----

    def _build_p2(self, ctx: ProjectContext, vol: int, ch: int) -> str:
        lines = []

        # 全书梗概 (synopsis.md) — 最高层大纲，所有 Agent 都需要的全局方向感
        synopsis = ctx.get_synopsis()
        if synopsis and "尚未设计" not in synopsis:
            lines.append(f"## 全书梗概\n{synopsis[:1500]}")

        # 卷弧线
        vol_outline = ctx.get_volume_outline(vol)
        if vol_outline:
            lines.append(f"## 第{vol}卷弧线\n{vol_outline[:1500]}")

        # 世界历史时间线 (plot_writer / editor 需要历史纵深)
        world_timeline = ctx.get_world_timeline()
        if world_timeline and "尚未记录" not in world_timeline:
            lines.append(f"## 世界历史时间线\n{world_timeline[:1500]}")

        # 当前卷已写各章的摘要（从 chapter _meta 提取）
        written = ctx.list_chapters(vol)
        if written:
            summaries = []
            for wch in written:
                if wch <= ch:
                    cm = ctx.get_chapter_meta(vol, wch)
                    if cm:
                        first_line = cm.split("\n")[0] if cm else ""
                        summaries.append(f"- 第{wch}章: {first_line}")
            if summaries:
                lines.append("## 已写章节\n" + "\n".join(summaries))

        return "\n\n".join(lines) if lines else ""

    # ---- P3: 全局索引 ----

    def _build_p3(
        self, ctx: ProjectContext, agent_id: str, ch: int, vol: int
    ) -> str:
        lines = []

        if agent_id in ("style_executor", "editor_in_chief", "character_director",
                       "emotion_controller", "chapter_break_director"):
            char_index = ctx.get_character_index()
            if char_index:
                lines.append("## 人物总览\n" + "\n".join(
                    f"- [{e['id']}] {e['name']} ({e['role']}, {e['faction']})"
                    for e in char_index[:20]
                ))

        if agent_id in ("plot_writer", "editor_in_chief", "world_builder",
                       "style_executor", "chapter_break_director", "emotion_controller"):
            world_index = ctx.get_world_index()
            if world_index:
                lines.append("## 世界观领域\n" + "\n".join(
                    f"- {d}: {summary}" for d, summary in world_index.items()
                ))

        if agent_id in ("character_director", "editor_in_chief", "emotion_controller",
                       "chapter_break_director"):
            rels = ctx.get_relationships()
            if rels and "尚未建立" not in rels:
                lines.append(f"## 关系摘要\n{rels[:800]}")

        return "\n\n".join(lines) if lines else ""

    # ---- P4: Agent 记忆 ----

    def _build_p4(self, ctx: ProjectContext, agent_id: str) -> str:
        memory = ctx.read_agent_memory(agent_id)
        if memory and "尚未开始" not in memory:
            # 只注入最近的 [ACTIVE] 条目
            lines = []
            in_active = False
            for line in memory.splitlines():
                if "[ACTIVE]" in line or "[ACTIVE]" in line.upper():
                    in_active = True
                if in_active:
                    lines.append(line)
                    if len(lines) > 30:
                        break
            if lines:
                return "## Agent记忆 (最近活跃项)\n" + "\n".join(lines)
            # 如果没有结构化标记，注入最后 800 字
            return f"## Agent记忆\n{memory[-800:]}"
        return ""

    # ---- 辅助 ----

    @staticmethod
    def _extract_chapter_outline(outline_text: str, chapter_num: int) -> str:
        lines = outline_text.splitlines()
        capture = False
        result = []
        markers = [f"第{chapter_num}章", f"第 {chapter_num} 章",
                    f"Chapter {chapter_num}"]
        for line in lines:
            if any(m in line for m in markers):
                capture = True
            if capture:
                result.append(line)
                for i in range(chapter_num + 1, chapter_num + 10):
                    if f"第{i}章" in line or f"Chapter {i}" in line:
                        capture = False
                        break
            if capture is False and result:
                break
        return "\n".join(result) if result else outline_text[:500]
