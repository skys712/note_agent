from pathlib import Path

from novel_writer.storage.markdown_store import MarkdownStore


class ProjectContext:
    """面向百万字长篇的项目上下文管理"""

    # 世界观领域生成顺序: 基础领域先, 时间线最后(需要引用所有其他领域)
    WORLD_DOMAINS = (
        "geography", "magic_system", "races",
        "politics", "history", "culture", "glossary", "timeline",
    )

    # 全部 8 个 Agent 的 memory 文件 ID
    AGENT_IDS = (
        "editor_in_chief", "world_builder", "character_director",
        "plot_writer", "style_executor", "state_manager",
        "emotion_controller", "chapter_break_director",
    )

    def __init__(self, project_path: Path):
        self.root = Path(project_path)
        self.store = MarkdownStore(self.root)

    @property
    def project_name(self) -> str:
        return self.root.name

    # ======== 项目元信息 ========

    def get_meta(self) -> dict:
        return self._parse_kv(self.store.read("_meta.md"))

    def save_meta(self, meta: dict) -> None:
        self.store.write(self._format_kv(meta), "_meta.md")

    def get_config(self) -> dict:
        """读取项目配置: volumes, chapters_per_volume, sections_per_chapter"""
        meta = self.get_meta()
        return {
            "volumes": int(meta.get("target_volumes", 10)),
            "chapters_per_volume": int(meta.get("target_chapters_per_volume", 15)),
            "sections_per_chapter": int(meta.get("target_sections_per_chapter", 3)),
        }

    # ======== 状态追踪 ========

    def get_status(self) -> dict:
        return self._parse_kv(self.store.read("status.md"))

    def save_status(self, status: dict) -> None:
        self.store.write(self._format_kv(status), "status.md")

    def mark_progress(self, vol: int, ch: int, sec: int) -> None:
        """记录已完成章节，并把 status 指向下一节待写位置。"""
        s = self.get_status()
        cfg = self.get_config()

        next_vol, next_ch, next_sec = vol, ch, sec + 1
        if next_sec > cfg["sections_per_chapter"]:
            next_sec = 1
            next_ch += 1
        if next_ch > cfg["chapters_per_volume"]:
            next_ch = 1
            next_vol += 1

        s["current_vol"] = str(next_vol)
        s["current_ch"] = str(next_ch)
        s["current_sec"] = str(next_sec)
        s["total_sections_written"] = str(self.get_total_sections_written())
        self.save_status(s)

    # ======== 世界观（多文件） ========

    def get_world_index(self) -> dict[str, str]:
        text = self.store.read("world", "index.md")
        result = {}
        for line in text.splitlines():
            if ":" in line and line.startswith("- "):
                line = line[2:]
                k, v = line.split(":", 1)
                k = k.strip().lstrip("*").rstrip("*").strip()
                result[k] = v.strip()
        return result

    def save_world_index(self, index: dict[str, str]) -> None:
        lines = ["# 世界观领域索引", ""]
        for domain, summary in index.items():
            lines.append(f"- {domain}: {summary}")
        self.store.write("\n".join(lines), "world", "index.md")

    def get_world_domain(self, domain: str) -> str:
        return self.store.read("world", f"{domain}.md")

    def save_world_domain(self, domain: str, content: str) -> None:
        self.store.write(content, "world", f"{domain}.md")

    def get_world_timeline(self) -> str:
        """世界观时间线: 从创世神话到预期故事结局的历史描述"""
        return self.store.read("world", "timeline.md")

    def save_world_timeline(self, content: str) -> None:
        self.store.write(content, "world", "timeline.md")

    # ======== 人物系统 ========

    def get_character_index(self) -> list[dict]:
        """解析 characters/index.md 表格"""
        text = self.store.read("characters", "index.md")
        if not text:
            return []
        result = []
        in_table = False
        for line in text.splitlines():
            if "| 人物ID |" in line:
                in_table = True
                continue
            if in_table and line.startswith("|"):
                parts = [p.strip() for p in line.split("|") if p.strip()]
                # 跳过表头重复行和分隔行
                if len(parts) < 2 or parts[0].startswith("-") or parts[0] == "人物ID":
                    continue
                if len(parts) >= 6:
                    result.append({
                        "id": parts[0],
                        "name": parts[1],
                        "role": parts[2],
                        "faction": parts[3],
                        "status": parts[4],
                        "first_appearance": parts[5],
                    })
        return result

    def save_character_index(self, entries: list[dict]) -> None:
        lines = [
            "# 人物索引",
            "",
            "## 角色列表",
            "",
            "| 人物ID | 姓名 | 定位 | 势力 | 状态 | 首次出现 |",
            "|--------|------|------|------|------|----------|",
        ]
        for e in entries:
            lines.append(
                f"| {e['id']} | {e['name']} | {e['role']} | {e['faction']} | "
                f"{e['status']} | {e['first_appearance']} |"
            )
        self.store.write("\n".join(lines), "characters", "index.md")

    def get_character(self, char_id: str) -> str:
        return self.store.read("characters", "cards", f"{char_id}.md")

    def save_character(self, char_id: str, content: str) -> None:
        self.store.write(content, "characters", "cards", f"{char_id}.md")

    def get_relationships(self) -> str:
        return self.store.read("characters", "relationships.md")

    def save_relationships(self, content: str) -> None:
        self.store.write(content, "characters", "relationships.md")

    def get_faction(self, name: str) -> str:
        return self.store.read("characters", "factions", f"{name}.md")

    def save_faction(self, name: str, content: str) -> None:
        self.store.write(content, "characters", "factions", f"{name}.md")

    def get_faction_index(self) -> str:
        return self.store.read("characters", "factions", "index.md")

    def save_faction_index(self, content: str) -> None:
        self.store.write(content, "characters", "factions", "index.md")

    # ======== 大纲（三层） ========

    def get_synopsis(self) -> str:
        return self.store.read("outline", "synopsis.md")

    def save_synopsis(self, content: str) -> None:
        self.store.write(content, "outline", "synopsis.md")

    def get_volume_outline(self, vol: int) -> str:
        return self.store.read("outline", f"volume_{vol:03d}.md")

    def save_volume_outline(self, vol: int, content: str) -> None:
        self.store.write(content, "outline", f"volume_{vol:03d}.md")

    def get_outline_meta(self) -> dict:
        return self._parse_kv(self.store.read("outline", "_meta.md"))

    def save_outline_meta(self, meta: dict) -> None:
        self.store.write(self._format_kv(meta), "outline", "_meta.md")

    # ======== 卷/章/节（三层正文） ========

    def list_volumes(self) -> list[int]:
        if not self.store.exists("volumes"):
            return []
        nums = []
        for d in self.store.list_files("volumes/volume_*"):
            if d.is_dir():
                try:
                    nums.append(int(d.name.split("_")[1]))
                except (IndexError, ValueError):
                    pass
        return sorted(nums)

    def list_chapters(self, vol: int) -> list[int]:
        pattern = f"volumes/volume_{vol:03d}/chapter_*"
        nums = []
        for d in self.store.list_files(pattern):
            if d.is_dir():
                try:
                    nums.append(int(d.name.split("_")[1]))
                except (IndexError, ValueError):
                    pass
        return sorted(nums)

    def get_chapter_meta(self, vol: int, ch: int) -> str:
        return self.store.read(
            "volumes", f"volume_{vol:03d}", f"chapter_{ch:03d}", "_meta.md"
        )

    def save_chapter_meta(self, vol: int, ch: int, content: str) -> None:
        self.store.write(
            content, "volumes", f"volume_{vol:03d}", f"chapter_{ch:03d}", "_meta.md"
        )

    def get_section(self, vol: int, ch: int, sec: int) -> str:
        return self.store.read(
            "volumes", f"volume_{vol:03d}", f"chapter_{ch:03d}",
            f"section_{sec:03d}.md"
        )

    def save_section(self, vol: int, ch: int, sec: int, content: str) -> None:
        self.store.write(
            content, "volumes", f"volume_{vol:03d}", f"chapter_{ch:03d}",
            f"section_{sec:03d}.md"
        )

    def list_sections(self, vol: int, ch: int) -> list[int]:
        pattern = f"volumes/volume_{vol:03d}/chapter_{ch:03d}/section_*.md"
        nums = []
        for f in self.store.list_files(pattern):
            try:
                nums.append(int(f.stem.split("_")[1]))
            except (IndexError, ValueError):
                pass
        return sorted(nums)

    def get_prev_section(self, vol: int, ch: int, sec: int) -> str:
        """获取前一节完整内容（用于连续性，调用方自行截取结尾）"""
        cfg = self.get_config()
        if sec > 1:
            return self.get_section(vol, ch, sec - 1)
        if ch > 1:
            spc = cfg["sections_per_chapter"]
            return self.get_section(vol, ch - 1, spc)
        if vol > 1:
            prev_vol = vol - 1
            cpc = cfg["chapters_per_volume"]
            spc = cfg["sections_per_chapter"]
            return self.get_section(prev_vol, cpc, spc)
        return ""

    def get_next_write_position(self) -> tuple[int, int, int] | None:
        """从 status.md 读取下一写作位置"""
        s = self.get_status()
        cv = int(s.get("current_vol", 1))
        cc = int(s.get("current_ch", 1))
        cs = int(s.get("current_sec", 1))
        return (cv, cc, cs)

    def get_total_sections_written(self) -> int:
        """统计已写总节数"""
        total = 0
        for vol in self.list_volumes():
            for ch in self.list_chapters(vol):
                total += len(self.list_sections(vol, ch))
        return total

    # ======== State 快照（每节写入后保存，供重置时回滚） ========

    def save_state_snapshot(self, vol: int, ch: int, sec: int) -> None:
        """在章节目录下保存当前 state.md 的快照"""
        state = self.get_state()
        if state and "尚未开始" not in state:
            self.store.write(
                state,
                "volumes", f"volume_{vol:03d}", f"chapter_{ch:03d}",
                f"state_after_sec_{sec:03d}.md"
            )

    def restore_state_snapshot(self, vol: int, ch: int, sec: int) -> None:
        """重置时恢复到目标位置对应的 state 快照。

        查找策略（优先级从高到低）：
        1. 目标章内序号 <= sec 的最新快照
        2. 目标卷内前几章的最新快照
        3. 前几卷的最新快照
        4. 初始状态
        """
        # 1. 在当前章内查找 <= sec 的快照
        snapshots = self._list_state_snapshots(vol, ch)
        if snapshots:
            matching = [s for s in snapshots if s <= sec]
            if matching:
                best_sec = max(matching)
                snapshot_path = (
                    f"volumes/volume_{vol:03d}/chapter_{ch:03d}/"
                    f"state_after_sec_{best_sec:03d}.md"
                )
                state = self.store.read(
                    "volumes", f"volume_{vol:03d}", f"chapter_{ch:03d}",
                    f"state_after_sec_{best_sec:03d}.md"
                )
                if state:
                    self.save_state(state)
                    return

        # 2. 在同卷的前几章中查找
        for prev_ch in sorted(self.list_chapters(vol), reverse=True):
            if prev_ch >= ch:
                continue
            snapshots = self._list_state_snapshots(vol, prev_ch)
            if snapshots:
                best_sec = max(snapshots)
                state = self.store.read(
                    "volumes", f"volume_{vol:03d}", f"chapter_{prev_ch:03d}",
                    f"state_after_sec_{best_sec:03d}.md"
                )
                if state:
                    self.save_state(state)
                    return

        # 3. 在前几卷中查找
        for prev_vol in sorted(self.list_volumes(), reverse=True):
            if prev_vol >= vol:
                continue
            for prev_ch in sorted(self.list_chapters(prev_vol), reverse=True):
                snapshots = self._list_state_snapshots(prev_vol, prev_ch)
                if snapshots:
                    best_sec = max(snapshots)
                    state = self.store.read(
                        "volumes", f"volume_{prev_vol:03d}",
                        f"chapter_{prev_ch:03d}",
                        f"state_after_sec_{best_sec:03d}.md"
                    )
                    if state:
                        self.save_state(state)
                        return

        # 4. 回退到初始状态
        self.save_state("# 剧情状态\n\n尚未开始写作。")

    # ======== 时间线 ========

    def get_timeline(self) -> str:
        return self.store.read("timeline.md")

    def save_timeline(self, content: str) -> None:
        self.store.write(content, "timeline.md")

    # ======== 剧情状态（版本化） ========

    @staticmethod
    def _state_key(vol: int, ch: int, sec: int) -> str:
        """返回版本化 state 的 key: v001_c001_s001"""
        return f"v{vol:03d}_c{ch:03d}_s{sec:03d}"

    @staticmethod
    def _state_filename(vol: int, ch: int, sec: int) -> str:
        """返回版本化 state 的文件名: state_v001_c001_s001.md"""
        return f"state_v{vol:03d}_c{ch:03d}_s{sec:03d}.md"

    def get_state(self) -> str:
        """读取全局 state.md（向后兼容，始终指向最新有效状态）"""
        return self.store.read("state.md")

    def save_state(self, content: str) -> None:
        """写入全局 state.md"""
        self.store.write(content, "state.md")

    # ---- 版本化 state（states/ 文件夹） ----

    def _read_state_index(self) -> dict[str, str]:
        """读取 states/_index.md，返回 {key: valid|stale} 字典"""
        text = self.store.read("states", "_index.md")
        result = {}
        for line in text.splitlines():
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                k, v = line.split(":", 1)
                result[k.strip()] = v.strip()
        return result

    def _write_state_index(self, index: dict[str, str]) -> None:
        """写入 states/_index.md"""
        lines = ["# State Version Index", ""]
        for key, status in sorted(index.items()):
            lines.append(f"{key}: {status}")
        self.store.write("\n".join(lines), "states", "_index.md")

    def save_state_version(self, vol: int, ch: int, sec: int, content: str) -> None:
        """保存版本化 state 快照到 states/ 文件夹"""
        filename = self._state_filename(vol, ch, sec)
        self.store.write(content, "states", filename)

    def get_state_version(self, vol: int, ch: int, sec: int) -> str:
        """读取指定节的版本化 state 快照"""
        filename = self._state_filename(vol, ch, sec)
        return self.store.read("states", filename)

    def get_state_for_section(self, vol: int, ch: int, sec: int) -> str:
        """获取写本节时应使用的 state 上下文。

        查找策略（优先级从高到低）：
        1. 同章前一节的有效 state 快照
        2. 前几章最后一节的有效 state 快照
        3. 前几卷最后一节的有效 state 快照
        4. 全局 state.md（向后兼容）
        """
        key = self._state_key(vol, ch, sec)
        idx = self._read_state_index()

        # 1. 同章前节
        if sec > 1:
            prev_key = self._state_key(vol, ch, sec - 1)
            if idx.get(prev_key, "valid") == "valid":
                snapshot = self.get_state_version(vol, ch, sec - 1)
                if snapshot and "尚未开始" not in snapshot:
                    return snapshot

        # 2. 前几章
        cfg = self.get_config()
        if ch > 1:
            for prev_ch in range(ch - 1, 0, -1):
                spc = cfg["sections_per_chapter"]
                prev_key = self._state_key(vol, prev_ch, spc)
                if idx.get(prev_key, "valid") == "valid":
                    snapshot = self.get_state_version(vol, prev_ch, spc)
                    if snapshot and "尚未开始" not in snapshot:
                        return snapshot

        # 3. 前几卷
        if vol > 1:
            cpc = cfg["chapters_per_volume"]
            spc = cfg["sections_per_chapter"]
            for prev_vol in range(vol - 1, 0, -1):
                prev_key = self._state_key(prev_vol, cpc, spc)
                if idx.get(prev_key, "valid") == "valid":
                    snapshot = self.get_state_version(prev_vol, cpc, spc)
                    if snapshot and "尚未开始" not in snapshot:
                        return snapshot

        # 4. 回退到全局 state.md
        global_state = self.get_state()
        if global_state and "尚未开始" not in global_state:
            return global_state
        return "# 剧情状态\n\n尚未开始写作。"

    def mark_section_valid(self, vol: int, ch: int, sec: int) -> None:
        """标记某节的状态为有效"""
        idx = self._read_state_index()
        idx[self._state_key(vol, ch, sec)] = "valid"
        self._write_state_index(idx)

    def invalidate_sections_after(self, vol: int, ch: int, sec: int) -> int:
        """将指定节之后的所有节标记为 stale。返回失效的节数。"""
        idx = self._read_state_index()
        cfg = self.get_config()
        count = 0

        # 收集所有需要失效的 key
        stale_keys = []
        for key in idx:
            # 解析 key: v001_c001_s001
            try:
                parts = key.split("_")
                kv = int(parts[0][1:])  # v001 -> 1
                kc = int(parts[1][1:])  # c001 -> 1
                ks = int(parts[2][1:])  # s001 -> 1
            except (IndexError, ValueError):
                continue

            # 判断是否在当前节之后
            if (kv, kc, ks) > (vol, ch, sec):
                if idx[key] != "stale":
                    idx[key] = "stale"
                    stale_keys.append(key)
                    count += 1

        if stale_keys:
            self._write_state_index(idx)
        return count

    def is_section_valid(self, vol: int, ch: int, sec: int) -> bool:
        """检查某节的状态是否仍然有效"""
        key = self._state_key(vol, ch, sec)
        idx = self._read_state_index()
        return idx.get(key, "valid") == "valid"

    def list_state_versions(self) -> list[dict]:
        """列出所有状态版本"""
        idx = self._read_state_index()
        result = []
        for key, status in sorted(idx.items()):
            try:
                parts = key.split("_")
                v = int(parts[0][1:])
                c = int(parts[1][1:])
                s = int(parts[2][1:])
            except (IndexError, ValueError):
                continue
            # 检查 state 文件是否存在
            filename = self._state_filename(v, c, s)
            has_file = self.store.exists("states", filename)
            result.append({
                "key": key, "vol": v, "ch": c, "sec": s,
                "status": status,
                "has_file": has_file,
            })
        return result

    def count_stale_sections(self) -> int:
        """统计失效节数"""
        idx = self._read_state_index()
        return sum(1 for v in idx.values() if v == "stale")

    # ======== 碎片管理 ========

    def list_fragments(self) -> list[dict]:
        """列出所有碎片文件及其元信息"""
        result = []
        for f in self.store.list_files("fragments/*.md"):
            text = f.read_text("utf-8")
            first_line = text.split("\n")[0].lstrip("#").strip()
            result.append({
                "id": f.stem,
                "path": str(f.relative_to(self.root)),
                "title": first_line,
                "size": len(text),
                "modified": f.stat().st_mtime,
            })
        return sorted(result, key=lambda x: x["modified"], reverse=True)

    def get_fragment(self, fragment_id: str) -> str:
        return self.store.read("fragments", f"{fragment_id}.md")

    def save_fragment(self, fragment_id: str, content: str) -> None:
        self.store.write(content, "fragments", f"{fragment_id}.md")

    def next_fragment_id(self) -> str:
        existing = sorted([f.stem for f in self.store.list_files("fragments/*.md")])
        if not existing:
            return "001"
        last = existing[-1]
        try:
            num = int(last.split("_")[0]) if "_" in last else int(last)
            return f"{num + 1:03d}"
        except ValueError:
            return f"{len(existing) + 1:03d}"

    def get_fragments_summary(self) -> str:
        return self.store.read("fragments_summary.md")

    def save_fragments_summary(self, content: str) -> None:
        self.store.write(content, "fragments_summary.md")

    def get_fragment_scan_status(self) -> float:
        """获取上次碎片扫描时间，0 表示从未扫描"""
        s = self.get_status()
        return float(s.get("last_fragment_scan", "0"))

    def set_fragment_scan_status(self, timestamp: float) -> None:
        s = self.get_status()
        s["last_fragment_scan"] = str(timestamp)
        self.save_status(s)

    def get_all_fragments_text(self) -> str:
        fragments = self.list_fragments()
        if not fragments:
            return ""
        parts = []
        for f in fragments:
            content = self.get_fragment(f["id"])
            parts.append(f"## 碎片 {f['id']}: {f['title']}\n{content}")
        return "\n\n---\n\n".join(parts)

    # ======== Agent 记忆 ========

    def read_agent_memory(self, agent_id: str) -> str:
        return self.store.read("agents", f"{agent_id}.md")

    def write_agent_memory(self, agent_id: str, content: str) -> None:
        self.store.write(content, "agents", f"{agent_id}.md")

    # ======== 批量初始化 ========

    def init_project_structure(self, meta: dict) -> None:
        """创建完整项目目录结构"""
        vols = int(meta.get("target_volumes", 10))
        c_p_v = int(meta.get("target_chapters_per_volume", 15))
        cfg = {
            "name": meta.get("name", ""),
            "genre": meta.get("genre", ""),
            "logline": meta.get("logline", ""),
            "target_volumes": str(vols),
            "target_chapters_per_volume": str(c_p_v),
            "target_sections_per_chapter": str(meta.get("target_sections_per_chapter", 3)),
            "status": "init",
        }
        self.save_meta(cfg)

        # 状态
        self.save_status({
            "current_vol": "1",
            "current_ch": "1",
            "current_sec": "1",
            "total_sections_written": "0",
        })

        # 世界观
        index = {d: f"待生成: {d}" for d in self.WORLD_DOMAINS}
        self.save_world_index(index)

        # 世界时间线模板
        self.save_world_timeline("""# 世界历史时间线

## 创世神话
> 描述世界的起源神话、创世神明或初始混沌。这是整个世界观的历史起点。

(待生成)

## 远古纪元
> 创世后的第一个时代: 古神/古文明/世界规则的确立

(待生成)

## 中古纪元
> 重要文明兴衰、重大战争、力量体系的起源

(待生成)

## 近世纪元
> 故事发生前的近代历史: 王国建立、上一次大规模冲突、现状的形成

(待生成)

## 故事时代
> 小说主线剧情发生的时间段。标注预期的大事件时间节点

(待生成)

## 预言与终局
> 故事预期结局的世界状态: 文明走向、力量平衡的最终形态

(待生成)
""")

        # 人物
        self.save_character_index([])
        self.store.write(
            "# 人物关系矩阵\n\n尚未建立。",
            "characters", "relationships.md"
        )
        self.store.write(
            "# 势力索引\n\n尚未建立。",
            "characters", "factions", "index.md"
        )

        # 大纲
        self.save_synopsis("尚未设计。")
        self.save_volume_outline(1, f"# 第一卷大纲\n\n尚未设计。")
        self.save_outline_meta({
            "synopsis_generated": "0",
            "volumes_outlined": "0",
            "last_outlined_vol": "0",
        })

        # 碎片
        self.save_fragments_summary("# 碎片参考摘要\n\n尚无碎片。")

        # 时间线
        self.save_timeline("# 时间线\n\n尚未记录。")

        # 剧情状态（全局 + 版本化 states/ 目录）
        initial_state = "# 剧情状态\n\n尚未开始写作。"
        self.save_state(initial_state)
        self.store.write("# State Version Index\n\n", "states", "_index.md")  # 空索引

        # 初始状态快照: 对应 section 0 (写第1节前的状态)
        self.store.write(initial_state, "states", "state_v001_c001_s000.md")

        # Agent 记忆
        for agent_id in self.AGENT_IDS:
            self.store.write(
                f"# Agent: {agent_id}\n\n尚未开始。",
                "agents", f"{agent_id}.md"
            )

        # input_config 模板（项目专属输入配置）
        self.store.write(
            "# 故事级约束\n\n"
            "> 最高优先级，所有大纲设计和正文写作必须严格遵守以下约束。\n\n"
            "## 时间线规则\n\n"
            "- （待填写）\n\n"
            "## 禁止出现的元素\n\n"
            "- （待填写）\n\n"
            "## 允许的核心设定\n\n"
            "- （待填写）\n\n"
            "## 修正项\n\n"
            "- （待填写）\n",
            "input_config", "story_constraints.md"
        )
        self.store.write("[]\n", "input_config", "chars.json")
        self.store.write(
            '{\n  "premise": "",\n  "allow_invent": false\n}\n',
            "input_config", "world_build.json"
        )

    # ======== 重置操作 ========

    def reset_full(self) -> dict:
        """完全重置写作进度：清除所有已写章节、剧情状态、故事时间线、Agent 记忆。
        保留：世界观、人物卡、大纲、碎片、卷大纲。

        Returns:
            重置统计信息。
        """
        import time
        stats = {
            "deleted_volumes": len(self.list_volumes()),
            "deleted_sections": self.get_total_sections_written(),
        }

        # 1. 重置 status.md
        self.save_status({
            "current_vol": "1",
            "current_ch": "1",
            "current_sec": "1",
            "total_sections_written": "0",
        })

        # 2. 重置 state.md（剧情状态）
        self.save_state("# 剧情状态\n\n尚未开始写作。")

        # 2b. 清空 states/ 版本化 state 目录，重建初始状态
        self._clear_state_versions()
        self.store.write("# State Version Index\n\n", "states", "_index.md")
        self.store.write("# 剧情状态\n\n尚未开始写作。", "states", "state_v001_c001_s000.md")

        # 3. 重置 timeline.md（故事时间线）
        self.save_timeline("# 时间线\n\n尚未记录。")

        # 4. 删除所有已写节（保留章节 _meta.md 场景设计）
        for vol in self.list_volumes():
            for ch in self.list_chapters(vol):
                self._clear_chapter_sections(vol, ch)

        # 5. 重置 Agent 记忆
        for agent_id in self.AGENT_IDS:
            self.write_agent_memory(
                agent_id,
                f"# Agent: {agent_id}\n\n已重置 ({time.strftime('%Y-%m-%d %H:%M:%S')})。"
            )

        # 6. 更新 _meta.md 状态
        meta = self.get_meta()
        meta["status"] = "init"
        self.save_meta(meta)

        # 7. 重置人物索引中的状态和首次出现
        idx = self.get_character_index()
        for entry in idx:
            entry["status"] = "活跃"
            entry["first_appearance"] = "待定"
        if idx:
            self.save_character_index(idx)

        return stats

    def reset_to(self, vol: int, ch: int, sec: int = 0) -> dict:
        """重置到指定位置之后：删除该位置之后的所有内容，将进度指针设到下一个位置。

        Args:
            vol: 保留到的卷号（含）。
            ch: 保留到的章号（含）。0 表示保留整卷（保留卷内所有已有章节）。
            sec: 保留到的节号（含）。0 表示保留整章。

        Returns:
            操作统计信息。
        """
        if ch == 0:
            chapters = self.list_chapters(vol)
            if chapters:
                ch = max(chapters)
                sec = self._get_last_section_in_chapter(vol, ch)
                if sec == 0:
                    sec = 1
            else:
                ch = 1
                sec = 0
            next_vol, next_ch, next_sec = self._advance_position(vol, ch, sec)
        elif sec == 0:
            sec = self._get_last_section_in_chapter(vol, ch)
            if sec == 0:
                next_vol, next_ch, next_sec = vol, ch, 1
            else:
                next_vol, next_ch, next_sec = self._advance_position(vol, ch, sec)
        else:
            next_vol, next_ch, next_sec = self._advance_position(vol, ch, sec)

        deleted_sections = 0
        deleted_chapters = 0
        deleted_volumes = 0

        # 1. 删除同章中序号 > sec 的节（含 state 快照和版本化 state）
        for existing_sec in self.list_sections(vol, ch):
            if existing_sec > sec:
                self._delete_section_file(vol, ch, existing_sec)
                self._delete_state_snapshot(vol, ch, existing_sec)
                self._delete_state_version(vol, ch, existing_sec)
                deleted_sections += 1

        # 2. 删除同卷中序号 > ch 的节（保留 _meta.md 场景设计）
        for existing_ch in self.list_chapters(vol):
            if existing_ch > ch:
                secs = self.list_sections(vol, existing_ch)
                for existing_sec in secs:
                    self._delete_state_version(vol, existing_ch, existing_sec)
                self._clear_chapter_sections(vol, existing_ch)
                deleted_sections += len(secs)
                deleted_chapters += 1

        # 3. 删除序号 > vol 的节（保留 _meta.md 场景设计）
        for existing_vol in self.list_volumes():
            if existing_vol > vol:
                for ech in self.list_chapters(existing_vol):
                    secs = self.list_sections(existing_vol, ech)
                    for existing_sec in secs:
                        self._delete_state_version(existing_vol, ech, existing_sec)
                    self._clear_chapter_sections(existing_vol, ech)
                    deleted_sections += len(secs)
                    deleted_chapters += 1
                deleted_volumes += 1

        # 4. 更新 status.md
        self.save_status({
            "current_vol": str(next_vol),
            "current_ch": str(next_ch),
            "current_sec": str(next_sec),
            "total_sections_written": str(self.get_total_sections_written()),
        })

        # 5. 恢复到目标位置对应的 state 快照（优先使用 states/ 版本化状态）
        restored = self._restore_from_state_version(vol, ch, sec)
        if not restored:
            self.restore_state_snapshot(vol, ch, sec)

        # 6. 重置后位置之后的节标记为 stale
        self.invalidate_sections_after(vol, ch, sec)

        return {
            "deleted_volumes": deleted_volumes,
            "deleted_chapters": deleted_chapters,
            "deleted_sections": deleted_sections,
            "next_position": (next_vol, next_ch, next_sec),
        }

    def _restore_from_state_version(self, vol: int, ch: int, sec: int) -> bool:
        """尝试从 states/ 版本化文件恢复 state.md。返回 True 表示恢复成功。"""
        # 优先读同节
        state = self.get_state_version(vol, ch, sec)
        if state and "尚未开始" not in state:
            self.save_state(state)
            return True
        # 回退：找前一个有效 state
        state = self.get_state_for_section(vol, ch, sec + 1)  # +1 因为本节之后的第一个
        if state and "尚未开始" not in state:
            self.save_state(state)
            return True
        return False

    # ======== 上下文注入（基础层，由 ContextBuilder 扩展） ========

    def get_relevant_world_domains(self, domains: list[str]) -> str:
        """读取指定领域的世界观内容"""
        parts = []
        for d in domains:
            content = self.get_world_domain(d)
            if content:
                parts.append(f"## {d}\n{content[:1500]}")
        return "\n\n".join(parts)

    def get_relevant_characters(self, char_ids: list[str]) -> str:
        """读取指定人物的完整卡"""
        parts = []
        for cid in char_ids:
            content = self.get_character(cid)
            if content:
                parts.append(content)
        return "\n\n---\n\n".join(parts)

    # ======== 辅助 ========

    def _get_last_section_in_chapter(self, vol: int, ch: int) -> int:
        """获取某章中最后一节的节号，没有则返回 0"""
        sections = self.list_sections(vol, ch)
        return max(sections) if sections else 0

    def _advance_position(self, vol: int, ch: int, sec: int) -> tuple[int, int, int]:
        """计算下一写作位置"""
        cfg = self.get_config()
        next_vol, next_ch, next_sec = vol, ch, sec + 1
        if next_sec > cfg["sections_per_chapter"]:
            next_sec = 1
            next_ch += 1
        if next_ch > cfg["chapters_per_volume"]:
            next_ch = 1
            next_vol += 1
        return next_vol, next_ch, next_sec

    def _clear_chapter_sections(self, vol: int, ch: int) -> None:
        """删除某章中所有节文件和 state 快照，但保留 _meta.md（场景设计）"""
        for sec in self.list_sections(vol, ch):
            self._delete_section_file(vol, ch, sec)
            self._delete_state_snapshot(vol, ch, sec)

    def _delete_section_file(self, vol: int, ch: int, sec: int) -> None:
        """删除指定节文件"""
        sec_file = self.root / "volumes" / f"volume_{vol:03d}" / f"chapter_{ch:03d}" / f"section_{sec:03d}.md"
        if sec_file.exists():
            sec_file.unlink()

    def _delete_state_snapshot(self, vol: int, ch: int, sec: int) -> None:
        """删除指定节的 state 快照"""
        snap_file = (
            self.root / "volumes" / f"volume_{vol:03d}" / f"chapter_{ch:03d}"
            / f"state_after_sec_{sec:03d}.md"
        )
        if snap_file.exists():
            snap_file.unlink()

    def _clear_state_versions(self) -> None:
        """删除 states/ 目录下所有 state 版本文件（保留 _index.md 和初始状态）"""
        states_dir = self.root / "states"
        if not states_dir.exists():
            return
        for f in states_dir.glob("state_v*.md"):
            try:
                f.unlink()
            except OSError:
                pass

    def _delete_state_version(self, vol: int, ch: int, sec: int) -> None:
        """删除指定节的版本化 state 文件并从索引中移除"""
        filename = self._state_filename(vol, ch, sec)
        state_file = self.root / "states" / filename
        if state_file.exists():
            state_file.unlink()
        idx = self._read_state_index()
        key = self._state_key(vol, ch, sec)
        if key in idx:
            del idx[key]
            self._write_state_index(idx)

    def _list_state_snapshots(self, vol: int, ch: int) -> list[int]:
        """列出某章中所有 state 快照的节号"""
        pattern = (
            f"volumes/volume_{vol:03d}/chapter_{ch:03d}/state_after_sec_*.md"
        )
        nums = []
        for f in self.store.list_files(pattern):
            try:
                nums.append(int(f.stem.rsplit("_", 1)[1]))
            except (IndexError, ValueError):
                pass
        return sorted(nums)

    @staticmethod
    def _parse_kv(text: str) -> dict:
        result = {}
        for line in text.strip().splitlines():
            if ":" in line and not line.startswith("#"):
                k, v = line.split(":", 1)
                result[k.strip()] = v.strip()
        return result

    @staticmethod
    def _format_kv(d: dict) -> str:
        return "\n".join(f"{k}: {v}" for k, v in d.items())
