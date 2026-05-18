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

    # ======== 时间线 ========

    def get_timeline(self) -> str:
        return self.store.read("timeline.md")

    def save_timeline(self, content: str) -> None:
        self.store.write(content, "timeline.md")

    # ======== 剧情状态 ========

    def get_state(self) -> str:
        return self.store.read("state.md")

    def save_state(self, content: str) -> None:
        self.store.write(content, "state.md")

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

        # 碎片
        self.save_fragments_summary("# 碎片参考摘要\n\n尚无碎片。")

        # 时间线
        self.save_timeline("# 时间线\n\n尚未记录。")

        # 剧情状态
        self.save_state("# 剧情状态\n\n尚未开始写作。")

        # Agent 记忆
        for agent_id in self.AGENT_IDS:
            self.store.write(
                f"# Agent: {agent_id}\n\n尚未开始。",
                "agents", f"{agent_id}.md"
            )

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
