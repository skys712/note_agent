import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path

from novel_writer.core.context import ProjectContext
from novel_writer.core.llm import LLMClient


@dataclass
class ChapterProcessingResult:
    vol: int
    ch: int
    chapter_title: str
    processed_text: str
    error: str | None = None


PUBLISH_SYSTEM_PROMPT = """\
你是一位资深的中文小说校对编辑。你的任务是审校小说章节正文，修正病句、错别字和格式问题。

核心原则：
- 必须保持原文的叙事风格、文学性和人物语气完全不变
- 不得修改任何情节、人名、地名、专有名词或世界观设定
- 不得增删任何实质性内容，只修正语言层面的问题
- 对话中的口语化表达、人物特有的说话方式必须保留"""


PUBLISH_USER_TEMPLATE = """\
请审校以下小说章节正文，完成三项工作：

## 一、病句和错别字检查
- 修正所有错别字（特别注意："的/地/得"混用、同音字错误、形近字错误）
- 修正病句：搭配不当、成分残缺、语序不当、句式杂糅
- 修正标点错误：引号不匹配、逗号句号混用、全角半角不一致
- 删除多余空格和重复字词

## 二、格式美化
- 段落之间使用空行分隔
- 确保对话格式规范，引号正确配对
- 统一使用中文全角标点（，。！？：；""）
- 过长的段落（超过500字）可适当拆分
- 场景切换处保持原有分隔线（---）

## 三、章节标题
- 在正文最开头添加章节标题，独占一行，格式为：`# 第{vol}章：标题`
- 标题应准确概括本章核心内容，8-15字为宜
- {title_hint}

## 注意事项
- **保持原文叙事风格、文学性和人物语气不变**
- **不要修改任何情节、人名、地名或专有名词**
- **只修正语言和格式问题**
- **请直接输出完整的修正后正文，不要添加任何说明**

---

{chapter_text}"""


class Publisher:
    """发布管线：收集、审校、打包全文为单文档"""

    def __init__(self, project_path: Path):
        self.ctx = ProjectContext(project_path)
        self.llm = LLMClient()
        self.llm.thinking = None

    async def publish(
        self,
        output: str | None = None,
        skip_check: bool = False,
        max_workers: int = 4,
    ) -> str | None:
        """主入口：收集章节、逐章审校、组装、输出。"""
        print("=" * 60, flush=True)
        print("发布：审校并打包全文", flush=True)
        print("=" * 60, flush=True)

        chapters = self._collect_chapters()
        if not chapters:
            print("暂无已写内容，无法发布。", flush=True)
            return None

        total_sections = sum(
            len(self.ctx.list_sections(vol, ch)) for vol, ch in chapters
        )
        print(f"已写: {len(set(v for v, _ in chapters))} 卷, "
              f"{len(chapters)} 章, {total_sections} 节", flush=True)
        print(f"审校: {'跳过 (--no-check)' if skip_check else '启用'}", flush=True)
        print(flush=True)

        results: list[ChapterProcessingResult] = []
        failed: list[tuple[int, int]] = []

        if skip_check:
            for vol, ch in chapters:
                scene_titles, chapter_text = self._build_chapter_text(vol, ch)
                if not chapter_text:
                    continue
                title = self._get_chapter_title_from_outline(vol, ch)
                results.append(ChapterProcessingResult(
                    vol=vol, ch=ch,
                    chapter_title=title,
                    processed_text=chapter_text,
                ))
                print(f"  [OK] 第{vol}卷第{ch}章: {title}", flush=True)
        else:
            sem = asyncio.Semaphore(max_workers)

            async def _process_one(vol: int, ch: int):
                scene_titles, chapter_text = self._build_chapter_text(vol, ch)
                if not chapter_text:
                    return None
                async with sem:
                    result = await self._process_chapter(vol, ch, scene_titles, chapter_text)
                    status = "[FAIL]" if result.error else "[OK]"
                    print(f"  {status} 第{vol}卷第{ch}章: {result.chapter_title}", flush=True)
                    return result

            tasks = [_process_one(vol, ch) for vol, ch in chapters]
            for coro in asyncio.as_completed(tasks):
                try:
                    result = await coro
                except Exception as e:
                    print(f"  [FAIL] chapter: {e}", flush=True)
                    continue
                if result is None:
                    continue
                results.append(result)
                if result.error:
                    failed.append((result.vol, result.ch))

        # 按卷/章排序
        results.sort(key=lambda r: (r.vol, r.ch))

        # 组装文档
        stats = {
            "total_chars": sum(len(r.processed_text) for r in results),
            "volumes": len(set(r.vol for r in results)),
            "chapters": len(results),
            "sections": total_sections,
            "checked": not skip_check,
            "failed_chapters": failed,
        }
        document = self._assemble_document(results, stats)

        # 确定输出路径
        if output:
            output_path = Path(output)
        else:
            output_dir = self.ctx.root / "publish"
            output_dir.mkdir(parents=True, exist_ok=True)
            book_name = self._get_book_title()
            output_path = output_dir / f"{book_name}_完整稿.md"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(document, encoding="utf-8")

        print(flush=True)
        print(f"输出: {output_path}", flush=True)
        print(f"总字数: {stats['total_chars']:,}", flush=True)
        if failed:
            print(f"审校失败章节: {len(failed)} (已使用原文)", flush=True)

        return str(output_path)

    # ======== 数据收集 ========

    def _collect_chapters(self) -> list[tuple[int, int]]:
        """返回所有包含已写正文的 (卷号, 章号) 列表"""
        result = []
        for vol in self.ctx.list_volumes():
            for ch in self.ctx.list_chapters(vol):
                sections = self.ctx.list_sections(vol, ch)
                if sections:
                    result.append((vol, ch))
        return result

    def _get_book_title(self) -> str:
        meta = self.ctx.get_meta()
        return meta.get("name", self.ctx.root.name)

    def _get_volume_title(self, vol: int) -> str:
        outline = self.ctx.get_volume_outline(vol)
        if not outline or "尚未" in outline:
            return f"第{vol}卷"

        m = re.search(r'\*\*卷标题\*\*[：:]\s*[《]?(.+?)[》]?\s*$', outline, re.MULTILINE)
        if m:
            return f"第{vol}卷：{m.group(1).strip()}"

        m = re.search(rf'#\s*第{vol}卷大纲[：:]\s*[《]?(.+?)[》]?\s*$', outline, re.MULTILINE)
        if m:
            return f"第{vol}卷：{m.group(1).strip()}"

        return f"第{vol}卷"

    @staticmethod
    def _to_chinese_numeral(n: int) -> str:
        digits = "零一二三四五六七八九"
        if n < 10:
            return digits[n]
        if n < 20:
            return "十" + (digits[n % 10] if n % 10 else "")
        tens = digits[n // 10] + "十"
        return tens + (digits[n % 10] if n % 10 else "")

    def _get_chapter_title_from_outline(self, vol: int, ch: int) -> str:
        outline = self.ctx.get_volume_outline(vol)
        if not outline or "尚未" in outline:
            return f"第{ch}章"

        ch_cn = self._to_chinese_numeral(ch)
        ch_num = str(ch)
        ch_alt = ch_cn if ch_cn == ch_num else f"{ch_num}|{ch_cn}"
        patterns = [
            rf'\*\*第(?:{ch_alt})章[（(](.+?)[）)]\*\*',
            rf'\*\*第(?:{ch_alt})章[：:]\s*(.+?)\*\*',
            rf'第(?:{ch_alt})章[（(](.+?)[）)]',
        ]
        for pat in patterns:
            m = re.search(pat, outline)
            if m:
                title = m.group(1).strip()
                if title:
                    return f"第{ch}章：{title}"

        return f"第{ch}章"

    def _get_chapter_scene_titles(self, vol: int, ch: int) -> str:
        meta = self.ctx.get_chapter_meta(vol, ch)
        if not meta:
            return ""

        titles = re.findall(r'##\s*场景\d+\s*\(section_\d+\)[：:]\s*(.+)', meta)
        if titles:
            return "、".join(titles)
        return ""

    def _build_chapter_text(self, vol: int, ch: int) -> tuple[str, str]:
        sections = self.ctx.list_sections(vol, ch)
        parts = []
        for sec in sections:
            text = self.ctx.get_section(vol, ch, sec)
            if text and text.strip():
                parts.append(text.strip())

        scene_titles = self._get_chapter_scene_titles(vol, ch)
        full_text = "\n\n---\n\n".join(parts)
        return scene_titles, full_text

    # ======== LLM 审校 ========

    async def _process_chapter(
        self,
        vol: int,
        ch: int,
        scene_titles: str,
        chapter_text: str,
    ) -> ChapterProcessingResult:
        """对单章调用 LLM 进行病句检查、格式美化和标题生成"""
        outline_title = self._get_chapter_title_from_outline(vol, ch)
        if "：" in outline_title:
            title_hint = f"建议标题（已从大纲提取，可直接使用或优化）：{outline_title}"
        else:
            title_hint = "请根据本章内容自行拟定标题"

        scene_hint = ""
        if scene_titles:
            scene_hint = f"\n本章场景：{scene_titles}\n"

        user_message = PUBLISH_USER_TEMPLATE.format(
            vol=vol,
            title_hint=title_hint,
            chapter_text=scene_hint + chapter_text,
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": user_message}],
                system=PUBLISH_SYSTEM_PROMPT,
                max_tokens=16384,
            )

            processed = response.content.strip()
            if not processed:
                raise ValueError("LLM 返回空内容")

            chapter_title = outline_title
            lines = processed.split("\n")
            if lines and lines[0].startswith("# "):
                raw_title = lines[0][2:].strip()
                if re.match(rf'第{ch}章[：:]\s*', raw_title):
                    chapter_title = raw_title
                elif raw_title:
                    chapter_title = f"第{ch}章：{raw_title}"
                processed = "\n".join(lines[1:]).strip()

            return ChapterProcessingResult(
                vol=vol,
                ch=ch,
                chapter_title=chapter_title,
                processed_text=processed,
            )

        except Exception as e:
            return ChapterProcessingResult(
                vol=vol,
                ch=ch,
                chapter_title=self._get_chapter_title_from_outline(vol, ch),
                processed_text=chapter_text,
                error=str(e),
            )

    # ======== 文档组装 ========

    def _assemble_document(
        self,
        results: list[ChapterProcessingResult],
        stats: dict,
    ) -> str:
        """将全部已处理章节组装为完整文档"""
        book_title = self._get_book_title()
        meta = self.ctx.get_meta()
        genre = meta.get("genre", "")

        lines = [
            f"# 《{book_title}》",
            "",
        ]
        if genre:
            lines.append(f"> **类型**: {genre}")
        lines.extend([
            "",
            "---",
            "",
        ])

        current_vol = None
        for r in results:
            if r.vol != current_vol:
                current_vol = r.vol
                vol_title = self._get_volume_title(r.vol)
                lines.append(f"## {vol_title}")
                lines.append("")

            lines.append(f"### {r.chapter_title}")
            lines.append("")
            lines.append(r.processed_text)
            lines.append("")
            lines.append("---")
            lines.append("")

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        check_status = "已启用" if stats["checked"] else "已跳过"
        lines.extend([
            "",
            "*发布说明*",
            f"- 生成时间: {timestamp}",
            f"- 总字数: {stats['total_chars']:,}",
            f"- 卷数: {stats['volumes']} | 章数: {stats['chapters']} | 节数: {stats['sections']}",
            f"- 审校: {check_status}",
        ])

        failed = stats.get("failed_chapters", [])
        if failed:
            failed_list = ", ".join(f"第{v}卷第{c}章" for v, c in failed)
            lines.append(f"- 审校失败 (已使用原文): {failed_list}")

        return "\n".join(lines)
