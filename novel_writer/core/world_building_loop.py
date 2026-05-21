"""
交互式世界观自循环构建器。

设计原则:
- LLM 只做分析（完备性评估、提问生成、冲突检测），不凭空创造设定内容
- 用户是所有世界观设定的唯一来源
- 完备性驱动循环：每个领域都有明确标准，不达标就继续提问
- 用户回答以碎片文件保存，最终通过 LLM 整理为领域文档
"""

import asyncio
import re
from pathlib import Path

from novel_writer.core.context import ProjectContext
from novel_writer.core.llm import LLMClient
from novel_writer.core.logging import ExecutionLogger


# 8 个世界观领域及其完备标准
DOMAIN_COMPLETENESS_CRITERIA = {
    "geography": {
        "name": "地理环境",
        "required": [
            "大陆/海洋的分布与名称",
            "主要地形区域（山脉、沙漠、森林等）",
            "气候带分布",
            "至少3个重要地点/城市的名称与特征",
            "主要交通路线或空间连接方式",
        ],
    },
    "magic_system": {
        "name": "力量体系",
        "required": [
            "力量/魔法的来源",
            "力量的分级或分类体系",
            "使用规则与限制条件",
            "使用力量的代价或副作用",
            "力量体系与世界观其他部分的关系",
        ],
    },
    "races": {
        "name": "种族",
        "required": [
            "存在的智慧种族列表",
            "每个种族的生理特征与能力",
            "每个种族的栖息地与分布",
            "种族间的社会地位与关系",
            "种族间的文化差异",
        ],
    },
    "politics": {
        "name": "政治格局",
        "required": [
            "国家/城邦/势力的名称列表",
            "各势力的统治体制",
            "势力间的外交关系（同盟、敌对、中立）",
            "军事力量的分布与对比",
            "主要矛盾或冲突来源",
        ],
    },
    "history": {
        "name": "历史背景",
        "required": [
            "至少5个重大历史事件",
            "重要战争及其影响",
            "王朝或文明的兴衰更迭",
            "历史事件之间的因果链条",
        ],
    },
    "culture": {
        "name": "文化风俗",
        "required": [
            "主要宗教信仰体系",
            "重要节日与庆典",
            "婚丧嫁娶等社会习俗",
            "社会禁忌与行为规范",
            "艺术风格与建筑特征",
        ],
    },
    "glossary": {
        "name": "术语表",
        "required": [
            "所有专有名词（地名、人名、概念）的定义",
            "术语之间的关联说明",
        ],
    },
    "timeline": {
        "name": "世界时间线",
        "required": [
            "创世神话（故事级叙事）",
            "远古纪元的关键事件",
            "中古纪元的关键事件",
            "近世纪元的关键事件",
            "故事时代的大事件节点",
            "预言与终局的预期走向",
        ],
    },
}

# 8 个领域的生成顺序（timeline 最后）
DOMAIN_ORDER = (
    "geography", "magic_system", "races",
    "politics", "history", "culture", "glossary", "timeline",
)


class WorldBuildingLoop:
    """交互式世界观自循环构建器"""

    COMPLETENESS_THRESHOLD = 80  # 每个领域 >= 80% 才算完备

    def __init__(self, ctx: ProjectContext, llm: LLMClient, log: ExecutionLogger):
        self.ctx = ctx
        self.llm = llm
        self.log = log

    # ======== 主入口 ========

    async def run(self, premise: str = "") -> bool:
        """主入口。循环直到完备或用户主动退出。"""
        _print_header()
        cfg = self.ctx.get_config()
        target_words = cfg["volumes"] * cfg["chapters_per_volume"] * cfg["sections_per_chapter"] * 3500

        if not premise:
            print("输入你的初始设定前提（回车跳过）:")
            premise = (await asyncio.to_thread(input, "> ")).strip()

        if premise:
            self._save_premise_fragment(premise)

        round_num = 0
        while True:
            round_num += 1
            print(f"\n{'=' * 50}")
            print(f"=== 第 {round_num} 轮: 完备性检查 ===")
            print(f"{'=' * 50}")

            # Step 1: 完备性检查
            scores = await self._check_completeness(target_words)
            self._print_completeness_report(scores)

            all_complete = all(
                s["score"] >= self.COMPLETENESS_THRESHOLD
                for s in scores.values()
            )
            if all_complete:
                print(f"\n[OK] 所有领域完备度均 >= {self.COMPLETENESS_THRESHOLD}%，世界观已完善!")
                break

            incomplete = {
                k: v for k, v in scores.items()
                if v["score"] < self.COMPLETENESS_THRESHOLD
            }

            # Step 2: 生成提问
            questions = await self._generate_questions(incomplete)
            if not questions:
                print("[WARN] 未能生成提问，请手动补充设定。")
                break

            # Step 3 & 4: 展示提问并收集回答
            self._present_questions(questions, round_num, scores)
            answers_text = await self._collect_answers()

            if answers_text is None:
                # 用户输入 /quit
                print("已保存当前进度，退出。")
                break

            if not answers_text.strip():
                print("[SKIP] 本轮无输入，跳过。")
                continue

            # Step 5: 保存回答为碎片
            domain_tag = questions[0]["domain"] if questions else "general"
            frag_id = self._save_answer_as_fragment(domain_tag, round_num, answers_text)
            print(f"[OK] 已保存为碎片 {frag_id}")

            # Step 6: 冲突检测
            if self.ctx.list_fragments():
                conflicts = await self._detect_conflicts()
                if conflicts:
                    print(f"\n[WARN] 检测到 {len(conflicts)} 个潜在矛盾。")
                    await self._resolve_conflicts(conflicts)

        # Final: 生成最终世界观文档
        print("\n" + "=" * 50)
        print("=== 生成最终世界观文档 ===")
        print("=" * 50)
        await self._generate_final_world()

        print("\n[OK] 交互式世界观构建完成!")
        self.log.summary()
        return True

    # ======== Step 1: 完备性检查 ========

    _COMPLETENESS_SYSTEM = (
        "你是一个世界观完备性审查专家。你的任务是评估当前世界观设定是否足够支撑一部长篇小说的创作。"
        "你需要检查每个领域是否包含足够的信息，并给出0-100的完备度评分。"
        "输出必须是严格的JSON格式，不要输出任何其他内容。"
    )

    def _build_completeness_prompt(self, target_words: int) -> str:
        criteria_lines = []
        for domain in DOMAIN_ORDER:
            info = DOMAIN_COMPLETENESS_CRITERIA[domain]
            criteria_lines.append(f"### {info['name']} ({domain})")
            for i, item in enumerate(info["required"], 1):
                criteria_lines.append(f"  {i}. {item}")
            criteria_lines.append("")

        criteria_text = "\n".join(criteria_lines)

        fragments_text = self.ctx.get_all_fragments_text()

        # 也读取已有的领域文件
        domain_texts = []
        for domain in DOMAIN_ORDER:
            content = self.ctx.get_world_domain(domain)
            if content and "待生成" not in content:
                domain_texts.append(f"## {DOMAIN_COMPLETENESS_CRITERIA[domain]['name']}\n{content[:3000]}")
        existing_domains = "\n\n".join(domain_texts) if domain_texts else "(尚无已生成的领域文档)"

        return (
            f"评估当前世界观设定的完备程度，判断是否足够支撑一部约 {target_words:,} 字的长篇小说创作。\n\n"
            f"## 完备标准（每个领域需达80%以上）\n\n{criteria_text}\n"
            f"## 已有领域文档\n\n{existing_domains}\n\n"
            f"## 碎片设定（用户输入的所有世界观片段）\n\n{fragments_text or '(尚无碎片)'}\n\n"
            f"请评估每个领域的完备度（0-100），并列出缺失的具体内容。输出严格JSON格式:\n"
            f'{{"geography": {{"score": 0-100, "missing": ["缺失项1", "缺失项2", ...]}}, ...}}\n'
            f"只对score低于{self.COMPLETENESS_THRESHOLD}的领域列出missing项。完备的领域missing为空数组。"
        )

    async def _check_completeness(self, target_words: int) -> dict:
        """调用 LLM 评估各领域完备度"""
        prompt = self._build_completeness_prompt(target_words)
        try:
            response = await self.llm.chat(
                [{"role": "user", "content": prompt}],
                system=self._COMPLETENESS_SYSTEM,
                max_tokens=4096,
            )
            return self._parse_completeness_response(response.content)
        except Exception as e:
            print(f"[FAIL] 完备性检查失败: {e}")
            # 返回全0评分以便继续
            return {
                d: {"score": 0, "missing": ["评估失败，请手动补充"]}
                for d in DOMAIN_ORDER
            }

    def _parse_completeness_response(self, raw: str) -> dict:
        """从 LLM 响应中解析 JSON"""
        # 尝试提取 JSON 块
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            import json
            try:
                data = json.loads(json_match.group())
                result = {}
                for domain in DOMAIN_ORDER:
                    info = data.get(domain, {})
                    result[domain] = {
                        "score": int(info.get("score", 0)),
                        "missing": info.get("missing", []),
                    }
                return result
            except json.JSONDecodeError:
                pass
        # 解析失败，返回全0
        return {
            d: {"score": 0, "missing": ["无法解析LLM输出，请手动补充"]}
            for d in DOMAIN_ORDER
        }

    # ======== Step 2: 生成提问 ========

    _QUESTION_SYSTEM = (
        "你是一个小说世界观访谈者，帮助作者补充完善世界观设定。"
        "根据各领域缺失的内容，生成具体、不宽泛的提问。"
        "每个问题要给出选项或范例引导作者思考。"
        "输出必须是严格的JSON数组格式。"
    )

    async def _generate_questions(self, incomplete: dict) -> list[dict]:
        """根据缺失项生成提问"""
        gap_lines = []
        for domain, info in incomplete.items():
            dname = DOMAIN_COMPLETENESS_CRITERIA[domain]["name"]
            gap_lines.append(f"## {dname} (完备度: {info['score']}%)")
            for m in info.get("missing", []):
                gap_lines.append(f"  - 缺失: {m}")
            gap_lines.append("")

        gap_text = "\n".join(gap_lines)

        fragments_text = self.ctx.get_all_fragments_text()
        existing_context = ""
        if fragments_text:
            existing_context = (
                f"## 已有设定摘要（避免提问已有内容）\n"
                f"{fragments_text[:3000]}\n\n"
            )

        prompt = (
            f"以下领域设定不完善，需要向作者提问来补充:\n\n"
            f"{existing_context}"
            f"{gap_text}\n"
            f"## 要求\n"
            f"- 每轮最多5个问题，优先问最关键、最基础的缺口\n"
            f"- 问题必须具体，给出引导性的选项或范例（例如：'力量来源是什么？（例如：元素之力、神赐、灵能、科技）'）\n"
            f"- 避免宽泛问题（例如：'描述力量体系'）\n"
            f"- 按领域分组，优先问基础领域（地理、力量体系、种族）\n\n"
            f"输出JSON数组格式:\n"
            f'[{{"domain": "geography", "question": "xxx", "hint": "例如: xxx"}}, ...]\n'
            f"最多5个问题。"
        )

        try:
            response = await self.llm.chat(
                [{"role": "user", "content": prompt}],
                system=self._QUESTION_SYSTEM,
                max_tokens=2048,
            )
            return self._parse_questions_response(response.content)
        except Exception as e:
            print(f"[FAIL] 提问生成失败: {e}")
            return []

    def _parse_questions_response(self, raw: str) -> list[dict]:
        json_match = re.search(r'\[[\s\S]*\]', raw)
        if json_match:
            import json
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return []

    # ======== Step 3 & 4: 展示提问和收集回答 ========

    def _present_questions(self, questions: list[dict], round_num: int, scores: dict) -> None:
        """在终端展示问题"""
        print(f"\n--- 第 {round_num} 轮提问 ---\n")

        current_domain = None
        for i, q in enumerate(questions, 1):
            domain = q.get("domain", "general")
            if domain != current_domain:
                current_domain = domain
                dname = DOMAIN_COMPLETENESS_CRITERIA.get(domain, {}).get("name", domain)
                score = scores.get(domain, {}).get("score", 0)
                print(f"  [{dname}] (目前完备度: {score}%)")

            hint = q.get("hint", "")
            hint_text = f" ({hint})" if hint else ""
            print(f"  {i}. {q['question']}{hint_text}")

        print()
        print("请回答以上问题。多行输入以空行结束。")
        print("  特殊命令: /file <路径>  加载预准备的文本文件作为回答")
        print("            /done          结束本轮回答")
        print("            /skip          跳过本轮，重新评估")
        print("            /quit          保存进度并退出")

    async def _collect_answers(self) -> str | None:
        """交互式收集用户回答。返回 None 表示用户要退出。"""
        lines = []
        print()
        while True:
            try:
                line = (await asyncio.to_thread(input, "> ")).strip()
            except EOFError:
                break

            if not line:
                if lines:
                    break  # 空行结束多行输入
                continue

            # 处理特殊命令
            if line.startswith("/"):
                cmd, _, arg = line[1:].partition(" ")
                cmd = cmd.strip().lower()
                arg = arg.strip()

                if cmd == "done":
                    break
                elif cmd == "skip":
                    return ""
                elif cmd == "quit":
                    return None
                elif cmd == "file":
                    if not arg:
                        print("  用法: /file <文件路径>")
                        continue
                    file_content = self._read_file_input(arg)
                    if file_content:
                        lines.append(file_content)
                        print(f"  [OK] 已从文件加载 ({len(file_content)} 字符)")
                        break  # 加载文件后结束本轮
                    continue
                else:
                    print(f"  未知命令: /{cmd}")
                    continue

            lines.append(line)

        return "\n".join(lines).strip()

    @staticmethod
    def _read_file_input(path_str: str) -> str:
        """读取预准备的文本文件"""
        path = Path(path_str).expanduser().resolve()
        if not path.exists():
            print(f"  [FAIL] 文件不存在: {path}")
            return ""
        if not path.is_file():
            print(f"  [FAIL] 不是文件: {path}")
            return ""
        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                print(f"  [WARN] 文件为空: {path}")
                return ""
            return content
        except Exception as e:
            print(f"  [FAIL] 读取文件失败: {e}")
            return ""

    # ======== Step 5: 保存回答为碎片 ========

    def _save_premise_fragment(self, premise: str) -> str:
        """保存初始前提为碎片"""
        frag_id = self.ctx.next_fragment_id()
        content = (
            f"# {frag_id}: 初始设定前提\n\n"
            f"类型: 顶层设定\n\n"
            f"{premise}"
        )
        self.ctx.save_fragment(frag_id, content)
        return frag_id

    def _save_answer_as_fragment(self, domain: str, round_num: int, content: str) -> str:
        """将用户回答保存为碎片文件"""
        frag_id = self.ctx.next_fragment_id()
        dname = DOMAIN_COMPLETENESS_CRITERIA.get(domain, {}).get("name", domain)
        file_content = (
            f"# {frag_id}: {dname} 第{round_num}轮\n\n"
            f"类型: 世界观设定\n\n"
            f"{content}"
        )
        self.ctx.save_fragment(frag_id, file_content)
        return frag_id

    # ======== Step 6: 冲突检测 ========

    _CONFLICT_SYSTEM = (
        "你是一个世界观一致性审查专家。你的任务是检查设定片段之间是否存在逻辑矛盾。"
        "对于发现矛盾的每对设定，提供2-3个可行的解决方案。"
        "如果没有矛盾，明确说明。"
        "输出必须是严格的JSON数组格式。"
    )

    async def _detect_conflicts(self) -> list[dict]:
        """调用 LLM 检查碎片中的矛盾"""
        fragments_text = self.ctx.get_all_fragments_text()
        if not fragments_text.strip():
            return []

        prompt = (
            f"检查以下世界观设定片段之间是否存在逻辑矛盾:\n\n"
            f"{fragments_text[:12000]}\n\n"
            f"## 要求\n"
            f"- 找出所有逻辑不自洽的地方\n"
            f"- 对每个矛盾，列出矛盾的双方（引用原文或概述）\n"
            f"- 解释矛盾的原因\n"
            f"- 提供2-3个解决方案（方案A、方案B、方案C(共存)）\n\n"
            f"如果没有发现矛盾，输出: []\n\n"
            f"输出JSON数组格式:\n"
            f'[{{"description": "矛盾简述", '
            f'"item_a": {{"fragment_id": "001", "summary": "..."}}, '
            f'"item_b": {{"fragment_id": "005", "summary": "..."}}, '
            f'"reason": "矛盾原因", '
            f'"options": ["方案A: ...", "方案B: ...", "方案C: 两者共存，需进一步解释"]}}]'
        )

        try:
            response = await self.llm.chat(
                [{"role": "user", "content": prompt}],
                system=self._CONFLICT_SYSTEM,
                max_tokens=4096,
            )
            return self._parse_conflicts_response(response.content)
        except Exception as e:
            print(f"[FAIL] 冲突检测失败: {e}")
            return []

    def _parse_conflicts_response(self, raw: str) -> list[dict]:
        json_match = re.search(r'\[[\s\S]*\]', raw)
        if json_match:
            import json
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return []

    # ======== Step 7: 冲突解决 ========

    async def _resolve_conflicts(self, conflicts: list[dict]) -> None:
        """逐条展示冲突并让用户选择解决方案"""
        for i, conflict in enumerate(conflicts, 1):
            print(f"\n--- 矛盾 {i}: {conflict.get('description', '未知')} ---")
            item_a = conflict.get("item_a", {})
            item_b = conflict.get("item_b", {})
            print(f"  设定A (碎片 {item_a.get('fragment_id', '?')}): {item_a.get('summary', '?')}")
            print(f"  设定B (碎片 {item_b.get('fragment_id', '?')}): {item_b.get('summary', '?')}")
            print(f"  原因: {conflict.get('reason', '未知')}")
            print()
            options = conflict.get("options", [])
            for j, opt in enumerate(options):
                letter = chr(ord("A") + j)
                print(f"  {letter}. {opt}")
            print(f"  S. 跳过（暂时忽略此矛盾）")
            print(f"  C. 自定义解决方案")

            choice = ""
            while True:
                choice = (await asyncio.to_thread(input, "请选择 (A/B/C/.../S/C): ")).strip().upper()
                if choice == "S":
                    print("  [SKIP] 已跳过此矛盾。")
                    break
                elif choice == "C":
                    print("  请输入自定义解决方案:")
                    custom = (await asyncio.to_thread(input, "> ")).strip()
                    if custom:
                        self._save_conflict_resolution(conflict, custom)
                        print("  [OK] 已记录自定义解决方案。")
                    break
                elif choice and ord(choice) - ord("A") < len(options):
                    selected = options[ord(choice) - ord("A")]
                    print(f"  已选择: {selected}")
                    self._save_conflict_resolution(conflict, selected)
                    break
                else:
                    print(f"  无效选项: {choice}")

    def _save_conflict_resolution(self, conflict: dict, resolution: str) -> None:
        """保存冲突解决方案为碎片"""
        frag_id = self.ctx.next_fragment_id()
        description = conflict.get("description", "未知矛盾")
        content = (
            f"# {frag_id}: 冲突解决\n\n"
            f"类型: 世界观修正\n\n"
            f"## 矛盾\n{description}\n\n"
            f"## 原因\n{conflict.get('reason', '未知')}\n\n"
            f"## 解决方案\n{resolution}\n\n"
            f"## 涉及碎片\n"
            f"- 碎片 {conflict.get('item_a', {}).get('fragment_id', '?')}: "
            f"{conflict.get('item_a', {}).get('summary', '?')}\n"
            f"- 碎片 {conflict.get('item_b', {}).get('fragment_id', '?')}: "
            f"{conflict.get('item_b', {}).get('summary', '?')}\n"
        )
        self.ctx.save_fragment(frag_id, content)

    # ======== 展示完备度 ========

    def _print_completeness_report(self, scores: dict) -> None:
        """ASCII 进度条展示各领域完备度"""
        print()
        bar_width = 20
        for domain in DOMAIN_ORDER:
            info = scores.get(domain, {"score": 0, "missing": []})
            score = info["score"]
            dname = DOMAIN_COMPLETENESS_CRITERIA[domain]["name"]
            filled = int(bar_width * score / 100)
            bar = "#" * filled + "." * (bar_width - filled)
            missing = info.get("missing", [])
            missing_text = ""
            if missing and score < self.COMPLETENESS_THRESHOLD:
                missing_text = f"  missing: {', '.join(missing[:3])}"
                if len(missing) > 3:
                    missing_text += f" ...(+{len(missing) - 3})"
            status = "[OK]" if score >= self.COMPLETENESS_THRESHOLD else "    "
            print(f"  {status} {dname:8s} [{bar}] {score:3d}%{missing_text}")
        print()

    # ======== Final: 生成最终世界观文档 ========

    async def _generate_final_world(self) -> None:
        """从碎片整理生成最终的8个领域文档"""
        from novel_writer.core.workflow import WorkflowOrchestrator

        fragments = self.ctx.list_fragments()
        if not fragments:
            print("[WARN] 没有碎片，无法生成世界观文档。")
            return

        print(f"正在基于 {len(fragments)} 个碎片生成世界观文档...")
        print("(此步骤仅整理已有碎片，不会新增设定)")

        orch = WorkflowOrchestrator(
            Path(self.ctx.root),
            debug=self.log.debug_mode,
        )
        orch.log = self.log

        await orch.generate_world(premise="", allow_invent=False)


def _print_header() -> None:
    """打印启动横幅"""
    print("=" * 60)
    print("  交互式世界观构建器")
    print("  World Building Interactive Loop")
    print("=" * 60)
    print()
    print("系统会持续检查世界观完备度，针对缺失内容提问。")
    print("你的所有回答将保存为设定碎片，最终整理为完整世界观文档。")
    print()
    print("可用命令:")
    print("  /file <路径>  - 加载预准备的文本文件作为设定输入")
    print("  /done         - 结束当前轮次回答")
    print("  /skip         - 跳过当前轮次")
    print("  /quit         - 保存进度并退出循环")
    print()
