import asyncio
import re
from pathlib import Path

from novel_writer.agents.base import AgentTask
from novel_writer.agents.chapter_break_director import ChapterBreakDirector
from novel_writer.agents.character_director import CharacterDirector
from novel_writer.agents.editor_in_chief import EditorInChief
from novel_writer.agents.emotion_controller import EmotionController
from novel_writer.agents.plot_writer import PlotWriter
from novel_writer.agents.state_manager import StateManager
from novel_writer.agents.style_executor import StyleExecutor
from novel_writer.agents.world_builder import WorldBuilder
from novel_writer.core.context import ProjectContext
from novel_writer.core.context_builder import ContextBuilder
from novel_writer.core.llm import LLMClient
from novel_writer.core.logging import ExecutionLogger


class WorkflowOrchestrator:
    """编排 Agent 协作流程"""

    _WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent

    def __init__(self, project_path: Path, debug: bool = False):
        self.ctx = ProjectContext(project_path)
        self.llm = LLMClient()
        self.log = ExecutionLogger(debug=debug)

        self.editor = EditorInChief(self.llm)
        self.world = WorldBuilder(self.llm)
        self.character = CharacterDirector(self.llm)
        self.plot = PlotWriter(self.llm)
        self.style = StyleExecutor(self.llm)
        self.state = StateManager(self.llm)
        self.emotion = EmotionController(self.llm)
        self.chapter_break = ChapterBreakDirector(self.llm)
        self.context_builder = ContextBuilder()

        for agent in [self.editor, self.world, self.character, self.plot,
                       self.style, self.state, self.emotion, self.chapter_break]:
            agent.logger = self.log

    # ======== 世界观构建 ========

    WORLD_DOMAINS = ProjectContext.WORLD_DOMAINS

    DOMAIN_NAMES = {
        "geography": "地理环境", "magic_system": "力量体系", "races": "种族",
        "politics": "政治格局", "history": "历史背景", "culture": "文化风俗",
        "glossary": "术语表", "timeline": "世界时间线",
    }

    DOMAIN_PROMPTS = {
        "geography": "详细描述世界的地理环境: 大陆/海洋分布、主要地形区域、气候带、重要地点和城市、交通路线。",
        "magic_system": "详细描述力量/魔法体系: 力量来源、分级制度、使用规则与限制、代价与反噬、与科技/蒸汽的关系。",
        "races": "详细描述世界中的种族/物种: 每个种族的特征、能力、栖息地、社会地位、文化差异。",
        "politics": "详细描述政治势力格局: 国家/城邦、统治体制、势力间关系与矛盾、军事力量分布。",
        "history": "详细描述历史背景(不包含创世神话, 那是timeline的内容): 重大历史事件、战争、王朝更迭、文明兴衰。",
        "culture": "详细描述文化风俗: 宗教信仰、节日庆典、婚丧习俗、社会禁忌、艺术与建筑风格。",
        "glossary": "整理世界观的术语词典: 所有专有名词、地名、人名、概念的定义和解释。每个条目一句话。",
        "timeline": (
            "生成世界历史时间线, 从创世神话到预期故事结局。必须包含以下六个时代:\n"
            "1. 创世神话 - 世界的起源、创世神明或初始混沌 (故事级叙事)\n"
            "2. 远古纪元 - 古神时代、最初文明、世界规则的确立\n"
            "3. 中古纪元 - 重要文明的兴衰、远古战争、力量体系的起源\n"
            "4. 近世纪元 - 故事发生前的近代历史、王国建立、上一次大规模冲突\n"
            "5. 故事时代 - 小说主线剧情的时间段, 标注预期的大事件节点\n"
            "6. 预言与终局 - 故事预期的最终结局、文明走向\n\n"
            "每个时代的关键时间点必须有故事级别的叙事描述, 不只是干巴巴的年份列表。"
        ),
    }

    async def _generate_domain(self, domain: str, premise: str, cross_refs: str,
                               fragment_summary: str = "", allow_invent: bool = False,
                               raw_fragments: str = "",
                               mem_lock: asyncio.Lock = None,
                               skip_index: bool = False) -> bool:
        """生成单个领域: WorldBuilder → Editor 审校 → (可选) 修订"""
        name = self.DOMAIN_NAMES.get(domain, domain)

        memory = self.ctx.read_agent_memory("world_builder")
        context = "" if skip_index else self.ctx.get_relevant_world_domains(
            [d for d in self.WORLD_DOMAINS if d != domain and self.ctx.get_world_domain(d)]
        )

        # Step 1: 生成
        detail = self.DOMAIN_PROMPTS.get(domain, "")
        prefix = f"[{name}] " if skip_index else ""
        self.log.step_start(1, 3, "世界观管理员", f"{prefix}generate",
                           input_size=len(detail) + len(premise))

        fragment_context = ""
        if raw_fragments or fragment_summary:
            fragment_context = "## 碎片参考（权威来源，所有设定必须来源于此）\n\n"
            if raw_fragments:
                fragment_context += (
                    f"### 原始碎片全文\n"
                    f"{raw_fragments}\n\n"
                )
            if fragment_summary:
                fragment_context += (
                    f"### 碎片摘要（快速索引）\n"
                    f"{fragment_summary}\n\n"
                )

        invent_rule = ""
        if not allow_invent:
            invent_rule = (
                "## 创作约束\n"
                "**禁止杜撰碎片参考中不存在的新世界观元素。**\n"
                "只能整理、扩展、细化碎片中已提及的设定，不得凭空创造碎片中未出现的地名、种族名、魔法体系、"
                "势力名称、历史事件等专有名词和核心概念。如需描述碎片未覆盖的空白领域，标注 [待补充] 即可。\n"
                "每个设定要点后标注碎片来源，如 (来源: 武者体系设定片段)。\n\n"
            )
        else:
            invent_rule = (
                "## 创作约束\n"
                "可以在碎片参考基础上合理杜撰新元素，但必须标注新增内容来源于推断而非已有设定。\n\n"
            )

        task = AgentTask(
            action="generate",
            input_text=(
                f"前提: {premise}\n\n"
                f"领域: {name}\n"
                f"{detail}\n\n"
                f"{fragment_context}"
                f"{invent_rule}"
                f"{cross_refs}\n"
                "确保本领域内容自洽, 且与已生成的其他领域保持一致。"
            ),
        )
        result = await self.world.execute(task, context=context, memory=memory)
        if not result.success:
            print(f"  {prefix}生成失败: {result.error}", flush=True)
            return False
        if not result.content.strip():
            print(f"  {prefix}生成内容为空 (LLM 可能未按格式输出), 跳过 {domain}", flush=True)
            if mem_lock:
                async with mem_lock:
                    self._merge_agent_memory("world_builder", result.notes)
            else:
                self._merge_agent_memory("world_builder", result.notes)
            return False
        self.ctx.save_world_domain(domain, result.content)
        if mem_lock:
            async with mem_lock:
                self._merge_agent_memory("world_builder", result.notes)
        else:
            self._merge_agent_memory("world_builder", result.notes)

        # Step 2: 总编审校
        self.log.step_start(2, 3, "总编", f"{prefix}review")
        review_task_text = (
            f"审校 {name} 设定。\n\n"
            f"审校维度:\n"
            f"1. 完整性 — 该领域是否覆盖了碎片中所有相关信息？是否遗漏了碎片中已有的设定点？\n"
            f"2. 自洽性 — 设定内部有无逻辑矛盾？\n"
            f"3. 碎片一致性 — 逐条检查设定内容是否与上方碎片原文一致。标记所有碎片中不存在的地名、种族名、魔法体系、势力名称、历史事件等专有名词。\n"
            f"4. 整体协调性 — 是否与已生成的其他领域协调？\n\n"
            f"如果没有问题回复[通过], 否则按维度列出修改意见。"
        )
        review_context = context or ""
        if raw_fragments:
            review_context = f"{review_context}\n\n## 碎片原文（供一致性对比）\n{raw_fragments[:30000]}"
        task = AgentTask(action="review", input_text=review_task_text)
        review = await self.editor.execute(task, context=review_context, memory=memory)
        if review.success and "通过" not in review.content:
            print(f"  {prefix}审校意见: {review.content[:200]}...", flush=True)
            self.log.step_start(3, 3, "世界观管理员", f"{prefix}revise")
            task = AgentTask(
                action="revise",
                input_text=(
                    f"当前 {name} 设定:\n{result.content[:2000]}\n\n"
                    f"修改意见:\n{review.content}\n\n请输出修订版。"
                ),
            )
            revised = await self.world.execute(task, context=context, memory=memory)
            if revised.success and revised.content.strip():
                self.ctx.save_world_domain(domain, revised.content)
                if mem_lock:
                    async with mem_lock:
                        self._merge_agent_memory("world_builder", revised.notes)
                else:
                    self._merge_agent_memory("world_builder", revised.notes)
            elif revised.success:
                print(f"  {prefix}修订内容为空, 保留初版。", flush=True)
        else:
            print(f"  {prefix}审校通过。", flush=True)

        if not skip_index:
            idx = self.ctx.get_world_index()
            content = self.ctx.get_world_domain(domain)
            idx[domain] = content.split("\n")[0].lstrip("#").strip()[:60] if content else "已生成"
            self.ctx.save_world_index(idx)
        return True

    async def generate_world(self, premise: str = "", allow_invent: bool = False) -> None:
        """逐领域生成完整世界观。先扫描碎片生成参考摘要，在此基础上构建世界观。"""
        self.log.phase("世界观生成 (逐领域)")

        if not premise:
            meta = self.ctx.get_meta()
            premise = f"类型: {meta.get('genre', '未知')}, 梗概: {meta.get('logline', '未知')}"

        # Step 0: 扫描碎片
        fragment_summary = ""
        raw_fragments = ""
        fragments = self.ctx.list_fragments()
        if fragments:
            self.log.section(f"碎片扫描: 检测到 {len(fragments)} 个碎片，正在生成参考摘要...")
            await self._scan_fragments(verbose=False)
            fragment_summary = self.ctx.get_fragments_summary() or ""
            if fragment_summary:
                print(f"  碎片摘要已生成 ({len(fragment_summary)} 字符)，将作为世界观生成的基础参考。", flush=True)

            priority_keywords = ["顶层设定", "设定", "时间线的框架", "行文风格准则"]
            def _fragment_priority(f):
                title = f.get("title", "")
                for i, kw in enumerate(priority_keywords):
                    if kw in title:
                        return i
                return len(priority_keywords)
            fragments.sort(key=_fragment_priority)

            raw_parts = []
            for f in fragments:
                content = self.ctx.get_fragment(f["id"])
                if content:
                    truncated = content[:20000]
                    if len(content) > 20000:
                        truncated += "\n...[截断]"
                    label = "【权威裁决】" if "顶层设定" in f.get("title", "") else ""
                    raw_parts.append(
                        f"=== {label}碎片: {f['title']} (ID: {f['id']}) ===\n{truncated}"
                    )
            raw_fragments = "\n\n".join(raw_parts)
            print(f"  原始碎片已收集 ({len(raw_fragments)} 字符)，将作为一级参考注入。", flush=True)
        else:
            print("  未检测到碎片，将基于前提直接生成。", flush=True)

        domains = self.WORLD_DOMAINS
        succeeded = 0
        mem_lock = asyncio.Lock()

        max_workers = min(len(domains), 5)
        self.log.section(f"并行生成 {len(domains)} 个领域 (max_workers={max_workers})")

        tasks = []
        for domain in domains:
            tasks.append(self._generate_domain(
                domain, premise, "",
                fragment_summary=fragment_summary,
                allow_invent=allow_invent,
                raw_fragments=raw_fragments,
                mem_lock=mem_lock,
                skip_index=True,
            ))

        # 使用 Semaphore 控制并发数
        sem = asyncio.Semaphore(max_workers)

        async def _bounded(coro, dname):
            async with sem:
                return await coro, dname

        bounded_tasks = [_bounded(t, self.DOMAIN_NAMES.get(d, d)) for t, d in zip(tasks, domains, strict=False)]

        for coro in asyncio.as_completed(bounded_tasks):
            try:
                result, dname = await coro
                if result:
                    succeeded += 1
                    print(f"  [OK] {dname}", flush=True)
                else:
                    print(f"  [SKIP] {dname}", flush=True)
            except Exception as e:
                print(f"  [FAIL] domain: {e}", flush=True)

        self._rebuild_world_index()
        self._update_status("world_building")
        self.log.phase(f"世界观生成完成! ({succeeded}/{len(domains)} 领域)")
        self.log.summary()

    # ======== 人物系统 ========

    async def create_character(self, name: str, role: str = "主角",
                               faction: str = "无", specs: str = "") -> None:
        """创建单个人物卡"""
        self.log.phase(f"创建人物: {name} ({role})")

        world_context = self._get_world_context_summary()
        fragment_context = self._collect_fragment_context()

        self.log.step_start(1, 3, "人物导演", "generate",
                           input_size=len(name) + len(specs) + len(fragment_context))
        memory = self.ctx.read_agent_memory("character_director")
        extra = f"\n补充要求: {specs}" if specs else ""
        task = AgentTask(
            action="generate",
            input_text=(
                f"创建一个人物: 姓名={name}, 定位={role}, 所属势力={faction}{extra}\n\n"
                f"{fragment_context}"
                f"世界背景:\n{world_context}\n\n"
                "基于碎片参考创建完整的人物卡, 每个信息点标注碎片来源:\n"
                "1. 姓名 (含别名/称号)\n"
                "2. 角色定位\n"
                "3. 性格特征 (外在表现 + 内在真实)\n"
                "4. 背景故事 (含与世界时间线的关联)\n"
                "5. 人物弧光 (跨卷成长轨迹)\n"
                "6. 说话风格与习惯用语\n"
                "7. 关键关系 (与其他人物的初始关系, 标注待创建)\n"
                "8. 与世界时间线的锚点 (出生/关键事件对应时间线中的哪个时代)"
            ),
        )
        result = await self.character.execute(task, memory=memory)
        if not result.success:
            print(f"错误: 生成失败 - {result.error}", flush=True)
            return

        self.log.step_start(2, 3, "世界观管理员", "check")
        task = AgentTask(
            action="check",
            input_text=(
                f"世界时间线摘要:\n{self.ctx.get_world_timeline()[:1500]}\n\n"
                f"人物卡:\n{result.content[:2000]}\n\n"
                "检查人物设定是否与世界时间线和世界观有矛盾。\n"
                "同时检查人物卡中的信息是否与碎片原文一致，标记碎片中不存在的人物细节。\n"
                "一致回复[一致], 否则列出具体矛盾。"
            ),
        )
        check = await self.world.execute(task)
        if check.success and "一致" not in check.content:
            print(f"  发现问题:\n{_indent(check.content[:300])}", flush=True)
        else:
            print("  检查通过。", flush=True)

        self.log.step_start(3, 3, "总编", "review")
        task = AgentTask(
            action="review",
            input_text=(
                f"审校人物卡, 从丰满度、商业吸引力、与已有角色的平衡性、碎片一致性评估。\n"
                f"人物卡:\n{result.content[:2000]}"
            ),
        )
        review = await self.editor.execute(task)
        if review.success and "通过" not in review.content:
            print(f"  审校意见: {review.content[:300]}", flush=True)
            if "通过" not in review.content:
                self.log.step_start(4, 4, "人物导演", "revise")
                task = AgentTask(
                    action="revise",
                    input_text=(
                        f"当前人物卡:\n{result.content[:2000]}\n\n"
                        f"修改意见:\n{review.content}\n\n输出修订版。"
                    ),
                )
                revised = await self.character.execute(task, memory=memory)
                if revised.success:
                    result = revised

        char_id = self._next_char_id(role)
        self.ctx.save_character(char_id, result.content)
        self.ctx.write_agent_memory("character_director", result.notes)

        idx = self.ctx.get_character_index()
        idx.append({
            "id": char_id,
            "name": name,
            "role": role,
            "faction": faction,
            "status": "活跃",
            "first_appearance": "待定",
        })
        self.ctx.save_character_index(idx)
        self._update_status("character_creation")
        print(f"\n人物 {name} ({char_id}) 创建完成!", flush=True)
        self.log.summary()

    async def refresh_character(self, char_id: str, specs: str = "") -> None:
        """刷新已有的人物卡: 基于最新碎片和世界设定重新生成并覆盖原卡"""
        self.log.phase(f"刷新人物: {char_id}")

        existing_card = self.ctx.get_character(char_id)
        if not existing_card:
            print(f"错误: 人物 {char_id} 不存在。", flush=True)
            return

        idx = self.ctx.get_character_index()
        current_entry = None
        for entry in idx:
            if entry["id"] == char_id:
                current_entry = entry
                break
        if not current_entry:
            print(f"错误: 人物 {char_id} 不在索引中。", flush=True)
            return

        name = current_entry["name"]
        role = current_entry["role"]
        faction = current_entry["faction"]

        world_context = self._get_world_context_summary()
        fragment_context = self._collect_fragment_context()

        self.log.step_start(1, 3, "人物导演", "refresh")
        memory = self.ctx.read_agent_memory("character_director")
        extra = f"\n补充要求: {specs}" if specs else ""
        task = AgentTask(
            action="generate",
            input_text=(
                f"刷新已有的人物卡: ID={char_id}, 姓名={name}, "
                f"定位={role}, 所属势力={faction}{extra}\n\n"
                f"{fragment_context}"
                f"世界背景:\n{world_context}\n\n"
                f"## 当前人物卡（请在其基础上优化）\n{existing_card}\n\n"
                "基于最新的碎片参考和世界背景, 刷新以上人物卡:\n"
                "1. 保留已有的人物核心设定（姓名、性格基调、背景主线）\n"
                "2. 补充和丰富各维度内容，包括最新碎片中提及的相关信息\n"
                "3. 修正过时或不一致的内容（基于最新的世界观和碎片）\n"
                "4. 完善人物弧光（跨卷成长轨迹）\n"
                "5. 更新与世界观时间线的锚点\n"
                "6. 如有碎片新增了与此人物相关的信息，必须纳入\n"
                "每个信息点标注碎片来源:\n"
                "  姓名 (含别名/称号)\n"
                "  角色定位\n"
                "  性格特征 (外在表现 + 内在真实)\n"
                "  背景故事 (含与世界时间线的关联)\n"
                "  人物弧光 (跨卷成长轨迹)\n"
                "  说话风格与习惯用语\n"
                "  关键关系 (与其他人物的关系)\n"
                "  与世界时间线的锚点"
            ),
        )
        result = await self.character.execute(task, memory=memory)
        if not result.success:
            print(f"错误: 刷新失败 - {result.error}", flush=True)
            return

        self.log.step_start(2, 3, "世界观管理员", "check")
        task = AgentTask(
            action="check",
            input_text=(
                f"世界时间线摘要:\n{self.ctx.get_world_timeline()[:1500]}\n\n"
                f"刷新后的人物卡:\n{result.content[:2000]}\n\n"
                "检查刷新后的人物设定是否与世界时间线和世界观有矛盾。\n"
                "同时检查人物卡中的信息是否与碎片原文一致，"
                "标记碎片中不存在的人物细节。\n"
                "一致回复[一致], 否则列出具体矛盾。"
            ),
        )
        check = await self.world.execute(task)
        if check.success and "一致" not in check.content:
            print(f"  发现问题:\n{_indent(check.content[:300])}", flush=True)
        else:
            print("  检查通过。", flush=True)

        self.log.step_start(3, 3, "总编", "review")
        task = AgentTask(
            action="review",
            input_text=(
                "审校刷新后的人物卡, 从丰满度、商业吸引力、"
                "与已有角色的平衡性、碎片一致性评估。\n"
                f"人物卡:\n{result.content[:2000]}"
            ),
        )
        review = await self.editor.execute(task)
        if review.success and "通过" not in review.content:
            print(f"  审校意见: {review.content[:300]}", flush=True)
            self.log.step_start(4, 4, "人物导演", "revise")
            task = AgentTask(
                action="revise",
                input_text=(
                    f"当前人物卡:\n{result.content[:2000]}\n\n"
                    f"修改意见:\n{review.content}\n\n输出修订版。"
                ),
            )
            revised = await self.character.execute(task, memory=memory)
            if revised.success:
                result = revised

        self.ctx.save_character(char_id, result.content)
        self.ctx.write_agent_memory("character_director", result.notes)

        idx = self.ctx.get_character_index()
        for entry in idx:
            if entry["id"] == char_id:
                entry["name"] = name
                entry["role"] = role
                entry["faction"] = faction
                entry["status"] = "活跃"
                break
        self.ctx.save_character_index(idx)

        print(f"\n人物 {name} ({char_id}) 刷新完成!", flush=True)
        self.log.summary()

    async def create_characters_batch(self, chars: list[dict]) -> None:
        """并行创建多个人物。chars 每项含 name/role/faction/specs"""
        if not chars:
            return
        self.log.phase(f"并行创建 {len(chars)} 个人物")

        fragment_context = self._collect_fragment_context()
        world_context = self._get_world_context_summary()
        id_lock = asyncio.Lock()
        mem_lock = asyncio.Lock()
        succeeded = 0

        async def _create_one(info: dict) -> tuple[str, str, str, str]:
            """创建单个人物，返回 (name, char_id, content, notes)"""
            name = info["name"]
            role = info.get("role", "配角")
            faction = info.get("faction", "无")
            specs = info.get("specs", "")

            memory = self.ctx.read_agent_memory("character_director")
            extra = f"\n补充要求: {specs}" if specs else ""
            task = AgentTask(
                action="generate",
                input_text=(
                    f"创建一个人物: 姓名={name}, 定位={role}, 所属势力={faction}{extra}\n\n"
                    f"{fragment_context}"
                    f"世界背景:\n{world_context}\n\n"
                    "基于碎片参考创建完整的人物卡, 每个信息点标注碎片来源:\n"
                    "1. 姓名 (含别名/称号)\n2. 角色定位\n3. 性格特征 (外在表现 + 内在真实)\n"
                    "4. 背景故事 (含与世界时间线的关联)\n5. 人物弧光 (跨卷成长轨迹)\n"
                    "6. 说话风格与习惯用语\n7. 关键关系\n8. 与世界时间线的锚点"
                ),
            )
            result = await self.character.execute(task, memory=memory)
            if not result.success or not result.content.strip():
                return (name, "", "", result.notes if result else "")

            review_task = AgentTask(
                action="review",
                input_text=(
                    f"审校人物卡, 从丰满度、商业吸引力、与已有角色的平衡性、碎片一致性评估。\n"
                    f"人物卡:\n{result.content[:2000]}"
                ),
            )
            review = await self.editor.execute(review_task)
            if review.success and "通过" not in review.content:
                revise_task = AgentTask(
                    action="revise",
                    input_text=(
                        f"当前人物卡:\n{result.content[:2000]}\n\n"
                        f"修改意见:\n{review.content}\n\n输出修订版。"
                    ),
                )
                revised = await self.character.execute(revise_task, memory=memory)
                if revised.success and revised.content.strip():
                    result = revised

            async with id_lock:
                char_id = self._next_char_id(role)
                self.ctx.save_character(char_id, result.content)
                idx = self.ctx.get_character_index()
                idx.append({
                    "id": char_id,
                    "name": name,
                    "role": role,
                    "faction": faction,
                    "status": "活跃",
                    "first_appearance": "待定",
                })
                self.ctx.save_character_index(idx)
            async with mem_lock:
                self.ctx.write_agent_memory("character_director", result.notes)
            return (name, char_id, role, faction)

        max_workers = min(len(chars), 5)
        sem = asyncio.Semaphore(max_workers)

        async def _bounded(info):
            async with sem:
                try:
                    return await _create_one(info)
                except Exception as e:
                    return (info["name"], "", "", str(e))

        tasks = [_bounded(c) for c in chars]
        for coro in asyncio.as_completed(tasks):
            name, char_id, role, faction = await coro
            if char_id:
                succeeded += 1
                print(f"  [OK] {name} ({char_id})", flush=True)
            else:
                print(f"  [SKIP] {name} (生成失败)", flush=True)

        self._update_status("character_creation")
        self.log.phase(f"角色创建完成! ({succeeded}/{len(chars)})")
        self.log.summary()

    async def create_relationship(self, char_a: str, char_b: str,
                                  rel_type: str = "关联") -> None:
        """生成两个人物间的关系描述"""
        self.log.section(f"人物关系: {char_a} <-> {char_b} ({rel_type})")

        card_a = self.ctx.get_character(char_a)
        card_b = self.ctx.get_character(char_b)
        if not card_a or not card_b:
            print("  错误: 人物卡不存在。", flush=True)
            return

        current_rels = self.ctx.get_relationships()
        self.log.step_start(1, 1, "人物导演", "generate")
        task = AgentTask(
            action="generate",
            input_text=(
                f"人物A:\n{card_a[:1000]}\n\n"
                f"人物B:\n{card_b[:1000]}\n\n"
                f"关系类型: {rel_type}\n"
                f"现有关系矩阵:\n{current_rels[:1000] if '尚未建立' not in current_rels else '无'}\n\n"
                "请生成两个人物之间的关系描述, 包含:\n"
                "1. 关系类型\n"
                "2. 关系演变 (从初识到故事结束的预期变化)\n"
                "3. 关键事件 (至少3个影响关系的节点)\n\n"
                "输出格式:\n"
                f"### {char_a} → {char_b}  (第一段用```包裹)\n"
            ),
        )
        result = await self.character.execute(task)
        if result.success:
            new_content = current_rels if "尚未建立" not in current_rels else "# 人物关系矩阵\n\n"
            new_content += f"\n{result.content}\n"
            self.ctx.save_relationships(new_content)
            print("  关系已保存。", flush=True)
        else:
            print(f"  生成失败: {result.error}", flush=True)

    async def create_faction(self, name: str, description: str = "") -> None:
        """创建势力"""
        self.log.phase(f"创建势力: {name}")

        if not self.ctx.get_faction_index():
            self.ctx.save_faction_index("# 势力索引\n\n")

        world_context = self._get_full_world_context()
        fragment_context = self._collect_fragment_context()
        constraints = self._get_story_constraints()
        char_summary = self._get_character_summary()
        self.log.step_start(1, 1, "人物导演", "generate",
                           input_size=len(name) + len(description))
        task = AgentTask(
            action="generate",
            input_text=(
                f"{constraints}\n\n"
                f"{fragment_context}\n\n"
                f"创建势力: {name}\n"
                f"补充说明: {description}\n\n"
                f"## 完整世界观设定（所有地名、历史事件、力量体系的权威参考）\n{world_context[:5000]}\n\n"
                f"## 关联人物卡\n{char_summary[:3000]}\n\n"
                "基于以上碎片、世界观、人物卡和故事约束，生成势力描述。**所有信息必须来自已有设定，不得生造碎片中不存在的地名、组织名、历史事件、专有名词。**\n\n"
                "势力描述内容:\n"
                "1. 势力全称和简称（如果碎片中未给出全称，标注 [推断] 或直接用势力名）\n"
                "2. 势力定位（引用世界观中的具体设定）\n"
                "3. 核心理念与目标（引用碎片来源）\n"
                "4. 组织结构（基于碎片推断，标注 [推断]）\n"
                "5. 历史渊源（严格引用世界时间线中的具体事件）\n"
                "6. 主要资源与力量（引用力量体系设定中的具体元素）\n"
                "7. 与其他势力的关系（只描述碎片中已有的关系，未知关系标注 [待补充]）"
            ),
        )
        result = await self.character.execute(task)
        if result.success:
            self.ctx.save_faction(name, result.content)
            fidx = self.ctx.get_faction_index()
            if "尚未建立" in fidx:
                fidx = "# 势力索引\n\n"
            fidx += f"\n## {name}\n{result.content[:200]}...\n"
            self.ctx.save_faction_index(fidx)
            print(f"\n势力 {name} 创建完成!", flush=True)
            self.log.summary()
        else:
            print(f"创建失败: {result.error}", flush=True)

    def _rebuild_world_index(self) -> None:
        """从已生成的世界领域文件重建索引（并行生成后调用）"""
        idx = {}
        for domain in self.WORLD_DOMAINS:
            content = self.ctx.get_world_domain(domain)
            if content and "待生成" not in content:
                idx[domain] = content.split("\n")[0].lstrip("#").strip()[:60]
        if idx:
            self.ctx.save_world_index(idx)

    def _get_world_context_summary(self) -> str:
        """获取世界观上下文摘要(供人物创建使用)"""
        parts = []
        tl = self.ctx.get_world_timeline()
        if tl and "待生成" not in tl:
            parts.append("## 世界时间线概览")
            for line in tl.splitlines():
                if line.startswith("## 第") or line.startswith("### "):
                    parts.append(line)
            parts.append("")
        idx = self.ctx.get_world_index()
        if idx:
            parts.append("## 世界领域\n" + "\n".join(
                f"- {d}: {s}" for d, s in idx.items() if "待生成" not in s
            ))
        return "\n".join(parts) if parts else "尚未建立世界观。"

    _CONSTRAINT_RELATIVE = "input_config/story_constraints.md"

    def _get_story_constraints(self) -> str:
        """从项目配置文件读取故事级约束（禁止元素/时间线规则）。"""
        project_constraints = self.ctx.root / "constraints.md"
        if project_constraints.exists():
            content = project_constraints.read_text(encoding="utf-8").strip()
            if content:
                return f"## 故事级约束（最高优先级，必须严格遵守）\n\n{content}"

        workspace_constraint = self._WORKSPACE_ROOT / self._CONSTRAINT_RELATIVE
        if workspace_constraint.exists():
            content = workspace_constraint.read_text(encoding="utf-8").strip()
            if content:
                return f"## 故事级约束（最高优先级，必须严格遵守）\n\n{content}"

        meta = self.ctx.get_meta()
        logline = meta.get("logline", "")
        name = meta.get("name", "")
        return (
            f"## 故事级约束（最高优先级，必须严格遵守）\n\n"
            f"**故事名称**: {name}\n"
            f"**核心前提**: {logline}\n\n"
            f"严格基于上述前提，不得引入与前提冲突的角色或事件。"
        )

    def _collect_fragment_context(self) -> str:
        """收集碎片上下文（供人物创建等流程使用）"""
        fragments = self.ctx.list_fragments()
        if not fragments:
            return ""

        priority_keywords = ["顶层设定", "设定", "时间线的框架", "行文风格准则"]
        fragments.sort(key=lambda f: next(
            (i for i, kw in enumerate(priority_keywords) if kw in f.get("title", "")),
            len(priority_keywords)))

        raw_parts = []
        for f in fragments:
            content = self.ctx.get_fragment(f["id"])
            if content:
                truncated = content[:20000]
                if len(content) > 20000:
                    truncated += "\n...[截断]"
                label = "【权威裁决】" if "顶层设定" in f.get("title", "") else ""
                raw_parts.append(
                    f'=== {label}碎片: {f["title"]} (ID: {f["id"]}) ===\n{truncated}'
                )
        raw_fragments = "\n\n".join(raw_parts)

        fragment_summary = self.ctx.get_fragments_summary() or ""

        parts = []
        parts.append("## 碎片参考（权威来源，所有人设必须来源于此）\n")
        if raw_fragments:
            parts.append(f"### 原始碎片全文\n{raw_fragments}\n")
        if fragment_summary:
            parts.append(f"### 碎片摘要\n{fragment_summary}\n")
        return "\n".join(parts)

    def _next_char_id(self, role: str) -> str:
        idx = self.ctx.get_character_index()
        prefix = {
            "主角": "protagonist", "反派": "antagonist",
            "配角": "supporting", "导师": "mentor",
        }.get(role, "character")
        max_n = 0
        for e in idx:
            if e["id"].startswith(prefix):
                try:
                    n = int(e["id"].split("_")[-1])
                    if n > max_n:
                        max_n = n
                except ValueError:
                    pass
        return f"{prefix}_{max_n + 1:03d}"

    # ======== 大纲设计（三层） ========

    async def generate_synopsis(self) -> None:
        """第一层: 全书梗概 (500-1000字)"""
        self.log.phase("全书梗概")

        world_context = self._get_full_world_context()
        char_summary = self._get_character_summary()
        fragment_context = self._collect_fragment_context()
        constraints = self._get_story_constraints()
        meta = self.ctx.get_meta()
        cfg = self.ctx.get_config()

        n_vols = cfg["volumes"]
        n_chs = cfg["chapters_per_volume"]
        n_secs = cfg["sections_per_chapter"]

        self.log.step_start(1, 2, "剧情编剧", "generate",
                           input_size=len(world_context) + len(char_summary))
        task = AgentTask(
            action="generate",
            input_text=(
                f"{constraints}\n\n"
                f"{fragment_context}\n\n"
                f"类型: {meta.get('genre', '?')}, 梗概: {meta.get('logline', '?')}\n"
                f"## 结构约束（不可违反）\n"
                f"- 全书仅有 **{n_vols} 卷**，{n_chs} 章，每章 {n_secs} 节\n"
                f"- 三幕式结构必须在 {n_vols} 卷 x {n_chs} 章的框架内完成\n"
                f"- 不得规划超出此范围的第{n_vols+1}卷或更远的续篇\n"
                f"- 所有人物弧线必须在 {n_chs} 章内完成收束\n\n"
                f"## 完整世界观设定\n{world_context}\n\n"
                f"## 人物卡（注意各人物的「当前状态」——在押/已死亡/活跃）\n{char_summary}\n\n"
                "基于以上碎片、世界观和人物卡，设计全书梗概 (500-1000字):\n"
                "1. 主线剧情一句话\n"
                "2. 核心矛盾与主题 (必须引用具体世界观元素)\n"
                "3. 三幕式整体结构——注意：全部 {n_vols} 卷 {n_chs} 章内完成三幕\n"
                "4. 主要人物的角色轨迹概述 (必须基于人物卡的当前状态，已入狱的角色从狱中开始)\n"
                "5. 预设的结局方向\n\n"
                "## 输出格式（严格遵守）\n"
                "将完整的全书梗概用第一个 ``` 包裹。"
                "只有 [FORESHADOWING]/[ACTIVE] 标记的记忆笔记才放入第二个 ``` 块。"
            ).replace("{n_vols}", str(n_vols)).replace("{n_chs}", str(n_chs)).replace("{n_secs}", str(n_secs)),
        )
        result = await self.plot.execute(task)
        if not result.success:
            print(f"错误: {result.error}", flush=True)
            return
        self.ctx.write_agent_memory("plot_writer", result.notes)

        self.log.step_start(2, 2, "总编", "review")
        review_task = AgentTask(
            action="review",
            input_text=(
                f"审校全书梗概, 从商业吸引力、结构完整度、矛盾设置、与碎片和世界观的一致性评估。\n"
                f"梗概:\n{result.content}"
            ),
        )
        review = await self.editor.execute(review_task)
        if review.success:
            self.ctx.write_agent_memory("editor_in_chief", review.notes)
            if "通过" not in review.content:
                print(f"  审校意见: {review.content[:300]}", flush=True)
                self.log.step_start(3, 3, "剧情编剧", "revise")
                revise_task = AgentTask(
                    action="revise",
                    input_text=(
                        f"当前全书梗概:\n{result.content[:2000]}\n\n"
                        f"修改意见:\n{review.content}\n\n输出修订版。"
                    ),
                )
                revised = await self.plot.execute(revise_task)
                if revised.success and revised.content.strip():
                    result = revised
                    self.ctx.write_agent_memory("plot_writer", revised.notes)
            else:
                print("  审校通过。", flush=True)

        self.ctx.save_synopsis(result.content)
        self._update_status("outlining")
        print("\n全书梗概完成!", flush=True)
        self.log.summary()

    async def generate_volume_outline(self, vol: int, direction: str = "") -> None:
        """第二层: 卷级弧线 (本卷核心冲突/角色成长/每章概要)"""
        self.log.phase(f"第 {vol} 卷大纲")

        synopsis = self.ctx.get_synopsis()
        prev_vol_outline = ""
        if vol > 1:
            prev_vol_outline = self.ctx.get_volume_outline(vol - 1)[:1000]

        world_context = self._get_full_world_context()
        char_summary = self._get_character_summary()
        fragment_context = self._collect_fragment_context()
        constraints = self._get_story_constraints()
        cfg = self.ctx.get_config()

        n_vols = cfg["volumes"]
        n_chs = cfg["chapters_per_volume"]

        self.log.step_start(1, 2, "剧情编剧", "generate",
                           input_size=len(synopsis) + len(world_context))
        extra = f"\n本卷方向: {direction}" if direction else ""
        task = AgentTask(
            action="generate",
            input_text=(
                f"{constraints}\n\n"
                f"{fragment_context}\n\n"
                f"全书梗概:\n{synopsis}\n\n"
                f"上一卷结尾:\n{prev_vol_outline[:500] if prev_vol_outline else '无 (第1卷)'}\n"
                f"## 结构约束（不可违反）\n"
                f"- 全书仅 {n_vols} 卷，本卷是第 {vol} 卷（{'唯一一卷' if n_vols == 1 else f'共{n_vols}卷'}) \n"
                f"- 本卷包含 {n_chs} 章，每章 {cfg['sections_per_chapter']} 节\n"
                f"- 不得规划第{n_vols+1}卷或引用「后续卷」\n"
                f"- 所有伏笔必须在 {n_chs} 章内完成埋设→回收的闭环\n\n"
                f"## 完整世界观设定\n{world_context}\n"
                f"## 人物卡（注意各人物的当前状态——在押/已死亡/活跃）\n{char_summary}\n"
                f"本卷规划: {cfg['chapters_per_volume']}章 x {cfg['sections_per_chapter']}节{extra}\n\n"
                "请设计第 {vol} 卷大纲（必须包含以下所有内容）:\n"
                "1. 本卷标题和核心主题\n"
                f"2. 本卷主线冲突和矛盾升级方向\n"
                "3. 本卷涉及的主要人物及其成长（注意：已入狱角色从狱中开始，已死亡角色仅以遗产/回忆形式出现）\n"
                "--- 以下为逐章概要（必须写满 {n_chs} 章）---\n"
                f"第1章「章名」: 核心冲突 + 主要场景概述 + 本章结尾钩子\n"
                f"第2章「章名」: 核心冲突 + 主要场景概述 + 本章结尾钩子\n"
                f"第3章「章名」: 核心冲突 + 主要场景概述 + 本章结尾钩子\n"
                "---\n"
                "5. 本卷伏笔埋设计划（在 {n_chs} 章内闭环）\n"
                "6. 本卷与全书结局的关联\n\n"
                "## 输出格式（严格遵守）\n"
                "将_完整_的卷大纲（以上 1-6 全部内容）用第一个 ``` 包裹。\n"
                "只有 [FORESHADOWING]/[ACTIVE]/[ARC] 标记的记忆笔记才放入第二个 ``` 块。\n"
                "大纲正文中的伏笔计划用叙述性文字描述，不要用 [FORESHADOWING] 标记——\n"
                "这些标记只在第二个 ``` 笔记块中使用。"
            ).replace("{vol}", str(vol)).replace("{n_vols}", str(n_vols)).replace("{n_chs}", str(n_chs)),
        )
        result = await self.plot.execute(task)
        if not result.success:
            print(f"错误: {result.error}", flush=True)
            return
        self.ctx.write_agent_memory("plot_writer", result.notes)

        self.log.step_start(2, 2, "总编", "review")
        review_task = AgentTask(
            action="review",
            input_text=(
                f"审校第{vol}卷大纲。从矛盾升级梯度、节奏、与前卷的衔接、伏笔合理性评估。\n"
                f"卷大纲:\n{result.content[:2000]}"
            ),
        )
        review = await self.editor.execute(review_task)
        if review.success:
            self.ctx.write_agent_memory("editor_in_chief", review.notes)
            if "通过" not in review.content:
                print(f"  审校意见: {review.content[:300]}", flush=True)
                self.log.step_start(3, 3, "剧情编剧", "revise")
                revise_task = AgentTask(
                    action="revise",
                    input_text=(
                        f"当前第{vol}卷大纲:\n{result.content[:2000]}\n\n"
                        f"修改意见:\n{review.content}\n\n输出修订版。"
                    ),
                )
                revised = await self.plot.execute(revise_task)
                if revised.success and revised.content.strip():
                    result = revised
                    self.ctx.write_agent_memory("plot_writer", revised.notes)
            else:
                print("  审校通过。", flush=True)

        self.ctx.save_volume_outline(vol, result.content)
        self._update_status("outlining")
        print(f"\n第 {vol} 卷大纲完成!", flush=True)
        self.log.summary()

    async def generate_chapter_scenes(self, vol: int, ch: int) -> None:
        """第三层: 章节场景设计 (_meta.md)"""
        self.log.section(f"第 {vol} 卷 第 {ch} 章 场景设计")

        vol_outline = self.ctx.get_volume_outline(vol)
        if not vol_outline:
            print(f"  错误: 第{vol}卷大纲尚未生成。", flush=True)
            return

        char_summary = self._get_character_summary()
        world_context = self._get_full_world_context()
        fragment_context = self._collect_fragment_context()
        constraints = self._get_story_constraints()
        cfg = self.ctx.get_config()

        self.log.step_start(1, 2, "剧情编剧", "design",
                           input_size=len(vol_outline) + len(world_context))
        task = AgentTask(
            action="design",
            input_text=(
                f"{constraints}\n\n"
                f"{fragment_context}\n\n"
                f"第{vol}卷大纲:\n{vol_outline}\n\n"
                f"## 完整世界观设定\n{world_context}\n"
                f"## 人物卡\n{char_summary}\n\n"
                f"请为第{vol}卷第{ch}章设计场景序列 ({cfg['sections_per_chapter']}个场景):\n\n"
                "格式:\n"
                "## 场景N (section_00N): 场景标题\n"
                "- POV: 视角人物\n"
                "- 地点: 具体地点 (必须是世界观中已设定的地点)\n"
                "- 出场人物: 人物名列表\n"
                "- 世界观元素: [领域:具体元素]\n"
                "- 核心冲突: 一句话冲突描述\n"
                "- 字数目标: 3000-5000\n\n"
                "要求: 场景间有机衔接, 本章整体有冲突升级和结尾钩子。所有地点和世界观元素必须来自已有设定。"
            ),
        )
        result = await self.plot.execute(task)
        if not result.success:
            print(f"  错误: {result.error}", flush=True)
            return
        self.ctx.write_agent_memory("plot_writer", result.notes)

        self.log.step_start(2, 2, "总编", "review")
        review_task = AgentTask(
            action="review",
            input_text=(
                f"审校第{vol}卷第{ch}章场景设计。从场景衔接、冲突升级、钩子设置、与卷大纲的一致性评估。\n"
                f"场景设计:\n{result.content[:2000]}"
            ),
        )
        review = await self.editor.execute(review_task)
        if review.success:
            self.ctx.write_agent_memory("editor_in_chief", review.notes)
            if "通过" not in review.content:
                print(f"  审校意见: {review.content[:300]}", flush=True)
                self.log.step_start(3, 3, "剧情编剧", "revise")
                revise_task = AgentTask(
                    action="revise",
                    input_text=(
                        f"当前第{vol}卷第{ch}章场景设计:\n{result.content[:2000]}\n\n"
                        f"修改意见:\n{review.content}\n\n输出修订版。"
                    ),
                )
                revised = await self.plot.execute(revise_task)
                if revised.success and revised.content.strip():
                    result = revised
                    self.ctx.write_agent_memory("plot_writer", revised.notes)
            else:
                print("  审校通过。", flush=True)

        self.ctx.save_chapter_meta(vol, ch, result.content)

    async def generate_volume_chapters(self, vol: int) -> None:
        """为整卷生成所有章的逐章场景设计"""
        cfg = self.ctx.get_config()
        cpc = cfg["chapters_per_volume"]
        self.log.phase(f"第 {vol} 卷: 逐章场景设计 ({cpc}章)")
        for ch in range(1, cpc + 1):
            await self.generate_chapter_scenes(vol, ch)
        self.log.summary()

    def _get_full_world_context(self) -> str:
        """获取完整世界观上下文（含领域内容，供大纲/写作使用）"""
        parts = []
        for domain in self.WORLD_DOMAINS:
            content = self.ctx.get_world_domain(domain)
            if content and "待生成" not in content:
                parts.append(f"### {self.DOMAIN_NAMES.get(domain, domain)}\n{content[:3000]}")
        return "\n\n".join(parts) if parts else "尚未建立世界观。"

    def _get_character_summary(self) -> str:
        """获取人物摘要（含关键信息和当前状态，供大纲/写作使用）"""
        idx = self.ctx.get_character_index()
        if not idx:
            return "尚未创建人物。"
        lines = []
        for e in idx:
            card = self.ctx.get_character(e["id"])
            if card:
                status = e.get("status", "活跃")
                header = (f"### {e['name']} ({e['role']}, {e['faction']}) "
                          f"— 当前状态: {status}")
                lines.append(f"{header}\n{card[:1000]}")
            else:
                lines.append(f"- [{e['id']}] {e['name']} ({e['role']}, {e['faction']})")
        return "\n\n".join(lines)

    # ======== 章节写作 ========

    async def write_section(self, vol: int, ch: int, sec: int, force: bool = False,
                            auto_mode: bool = False) -> None:
        """写指定节: 7 正向指导 + 逆向验证及修订 + 状态更新

        Args:
            force: True 允许重写已有节，并自动失效后续节。
            auto_mode: True 跳过所有人类确认提示，自动修订。
        """
        self.log.phase(f"第 {vol} 卷 第 {ch} 章 第 {sec} 节 写作 (正向指导 + 逆向验证及修订 + 状态更新)")

        cfg = self.ctx.get_config()

        # 检查是否已有内容（重写检测）
        existing_content = self.ctx.get_section(vol, ch, sec)
        is_rewrite = bool(existing_content and existing_content.strip())
        if is_rewrite and not force:
            print(f"  本节已有内容 ({len(existing_content)} 字)。", flush=True)
            print("  使用 --force 可强制重写（重写后后续节将失效）。", flush=True)
            return
        if is_rewrite:
            print(f"  [重写模式] 本节已有 {len(existing_content)} 字内容，将覆盖。", flush=True)
            self.log.debug(f"rewrite section v{vol:03d}_c{ch:03d}_s{sec:03d}")

        await self._auto_scan_fragments()

        fragment_context = self._collect_fragment_context()
        full_world = self._get_full_world_context()
        char_summary = self._get_character_summary()
        constraints = self._get_story_constraints()

        chapter_meta = self.ctx.get_chapter_meta(vol, ch)
        chapter_outline = chapter_meta or self._get_chapter_outline(vol, ch)

        full_synopsis = self.ctx.get_synopsis()
        full_volume_outline = self.ctx.get_volume_outline(vol)

        prev_section = self.ctx.get_prev_section(vol, ch, sec)

        is_last_in_chapter = (sec == cfg["sections_per_chapter"])
        is_last_in_volume = is_last_in_chapter and (ch == cfg["chapters_per_volume"])

        # Step 1: 剧情编剧提取并细化 _meta.md 中已规划的权威场景
        self.log.step_start(1, 14, "剧情编剧", "elaborate")
        section_plan = self._extract_section_from_meta(chapter_outline, sec)
        context = self.context_builder.build(self.ctx, "plot_writer", vol, ch, sec, constraints=constraints)
        memory = self.ctx.read_agent_memory("plot_writer")
        task = AgentTask(
            action="elaborate",
            input_text=(
                f"{constraints}\n\n"
                f"{fragment_context}\n\n"
                f"## 权威参考材料\n\n"
                f"### 完整世界观设定（所有地点、力量体系、历史事件）\n{full_world}\n\n"
                f"### 人物卡（所有角色必须严格遵循）\n{char_summary}\n\n"
                f"---\n\n"
                f"## 本章权威大纲 — 第{sec}节场景规划（_meta.md 原文，不可更改）\n\n"
                f"{section_plan}\n\n"
                f"---\n\n"
                f"## 全书梗概（全局方向参考）\n{full_synopsis[:2000] if full_synopsis else '尚未设计'}\n\n"
                f"## 本卷大纲（卷级方向参考）\n{full_volume_outline[:2000] if full_volume_outline else '尚未设计'}\n\n"
                f"## 前一节结尾\n{prev_section[-800:] if prev_section else '无'}\n\n"
                f"---\n\n"
                f"## 任务：将权威大纲细化为可执行场景方案\n\n"
                f"**上方「本章权威大纲」中的场景规划已经过审核，是本节写作的最高准则。**\n"
                f"你的任务不是重新设计场景，而是在不改变权威大纲的前提下做执行级细化：\n\n"
                f"1. **确认不可变元素**：POV、主要地点、核心冲突、主要出场人物、关键情节走向——"
                f"这些由权威大纲确定，**一个都不能改**\n"
                f"2. **拆解场景概要**：将大纲中的「场景概要」逐段拆解为具体执行节拍，"
                f"每拍标注对应的原文段落和预计字数\n"
                f"3. **补充执行细节**：关键对话的要点（不是全文）、场景节奏标注（慢/中/快）、"
                f"情感高点位置\n"
                f"4. **标注衔接**：与前一节的衔接点和与后一节的铺垫\n\n"
                f"输出格式:\n"
                f"## 场景 (section_{sec:03d}): [沿用权威大纲的标题]\n"
                f"- POV: [沿用权威大纲]\n"
                f"- 地点: [沿用权威大纲]\n"
                f"- 出场人物: [沿用权威大纲]\n"
                f"- 核心冲突: [沿用权威大纲]\n"
                f"- 字数目标: [沿用权威大纲]\n"
                f"- 世界观元素: [沿用权威大纲]\n\n"
                f"### 执行节拍\n"
                f"1. [节拍描述] — 参考大纲段落: \"...\" — 预计XXX字\n"
                f"2. ...\n\n"
                f"**禁止事项**：不得更改 POV 人物、不得更换地点、不得改变核心冲突方向、"
                f"不得增删主要出场人物。如需微调，必须在输出中明确标注变更理由。"
            ),
        )
        plot_design = await self.plot.execute(task, context=context, memory=memory)
        if not plot_design.success:
            print(f"错误: 场景设计失败 - {plot_design.error}", flush=True)
            return
        print("  场景设计完成。", flush=True)

        # Step 2+3: 人物导演 + 世界观管理员并行检查场景设计
        self.log.step_start(2, 14, "人物导演+世界观管理员", "check")
        char_context = self.context_builder.build(self.ctx, "character_director", vol, ch, sec, constraints=constraints)
        char_memory = self.ctx.read_agent_memory("character_director")
        world_context_b = self.context_builder.build(self.ctx, "world_builder", vol, ch, sec, constraints=constraints)
        world_memory = self.ctx.read_agent_memory("world_builder")

        char_task = AgentTask(
            action="check",
            input_text=(
                f"本节场景设计: {plot_design.content}\n"
                f"## 人物卡\n{char_summary}\n"
                "检查是否有角色行为不符合人物卡设定的情况。如果没有问题, 回复[一致]。"
            ),
        )
        world_task = AgentTask(
            action="check",
            input_text=(
                f"本节场景设计: {plot_design.content}\n"
                f"## 完整世界观设定\n{full_world}\n"
                "检查是否有与世界观设定矛盾的地方。如果没有问题, 回复[一致]。"
            ),
        )

        char_check, world_check = await asyncio.gather(
            self.character.execute(char_task, context=char_context, memory=char_memory),
            self.world.execute(world_task, context=world_context_b, memory=world_memory),
        )

        char_issues = ""
        world_issues = ""
        if char_check.success and "一致" not in char_check.content:
            print(f"  人物导演提出注意: {char_check.content[:300]}", flush=True)
            char_issues = char_check.content
        else:
            print("  角色行为检查通过。", flush=True)
        self.ctx.write_agent_memory("character_director", char_check.notes)

        if world_check.success and "一致" not in world_check.content:
            print(f"  世界观管理员提出注意: {world_check.content[:300]}", flush=True)
            world_issues = world_check.content
        else:
            print("  世界观设定检查通过。", flush=True)
        self.ctx.write_agent_memory("world_builder", world_check.notes)

        if char_issues or world_issues:
            combined_issues = "\n\n".join(
                p for p in [
                    f"## 人物检查问题\n{char_issues}" if char_issues else "",
                    f"## 世界观检查问题\n{world_issues}" if world_issues else "",
                ] if p
            )
            self.log.step_start(3, 14, "剧情编剧", "revise")
            revise_context = self.context_builder.build(self.ctx, "plot_writer", vol, ch, sec, constraints=constraints)
            revise_task = AgentTask(
                action="revise",
                input_text=(
                    f"当前场景设计:\n{plot_design.content[:2000]}\n\n"
                    f"{combined_issues}\n\n"
                    "请根据以上所有检查意见修订场景设计，输出完整的修订版。"
                ),
            )
            revised = await self.plot.execute(revise_task, context=revise_context,
                                              memory=self.ctx.read_agent_memory("plot_writer"))
            if revised.success and revised.content.strip():
                plot_design = revised
                self.ctx.write_agent_memory("plot_writer", revised.notes)
                print("  场景设计已根据检查结果修订。", flush=True)

        # Step 4: 情绪曲线管控
        self.log.step_start(4, 14, "情绪曲线管控", "direct")
        context = self.context_builder.build(self.ctx, "emotion_controller", vol, ch, sec, constraints=constraints)
        memory = self.ctx.read_agent_memory("emotion_controller")
        section_level = "卷末" if is_last_in_volume else ("章末" if is_last_in_chapter else "普通节")
        task = AgentTask(
            action="direct",
            input_text=(
                f"本节场景设计: {plot_design.content}\n"
                f"前一节结尾: {prev_section[-500:] if prev_section else '无'}\n"
                f"本节层级: {section_level}\n"
                f"卷号: {vol}, 章号: {ch}, 节号: {sec}\n"
                f"是否为章末节: {is_last_in_chapter}\n"
                f"是否为卷末节: {is_last_in_volume}\n\n"
                "请给出本节的情绪指导:\n"
                "1. 本节情绪目标和强度\n"
                "2. 情绪节奏 (起点→中段→结尾)\n"
                "3. 刀/糖标记\n"
                "4. 与前节的情绪衔接关系\n"
                "5. 注意事项 (情绪疲劳预警)"
            ),
        )
        emotion_guide = await self.emotion.execute(task, context=context, memory=memory)
        if emotion_guide.success:
            self.ctx.write_agent_memory("emotion_controller", emotion_guide.notes)
            print(f"  情绪指导: {emotion_guide.content[:300]}", flush=True)
        else:
            print("  情绪分析异常, 继续执行。", flush=True)

        # Step 5: 总编给出写作方向指导
        self.log.step_start(5, 14, "总编", "direct")
        context = self.context_builder.build(self.ctx, "editor_in_chief", vol, ch, sec, constraints=constraints)
        memory = self.ctx.read_agent_memory("editor_in_chief")
        task = AgentTask(
            action="direct",
            input_text=(
                f"本节场景设计: {plot_design.content}\n"
                f"人物检查: {char_issues[:1000] if char_issues else '无'}\n"
                f"世界观检查: {world_issues[:1000] if world_issues else '无'}\n"
                f"情绪指导: {emotion_guide.content if emotion_guide.success else '无'}\n"
                "请给出本节的写作重点、情绪基调、节奏控制建议。注意综合上述检查意见中的问题点。"
            ),
        )
        direction = await self.editor.execute(task, context=context, memory=memory)
        if direction.success:
            self.ctx.write_agent_memory("editor_in_chief", direction.notes)
            print(f"  写作指导: {direction.content[:300]}", flush=True)

        # Step 6: 断章决策者
        self.log.step_start(6, 14, "断章决策者", "design")
        context = self.context_builder.build(self.ctx, "chapter_break_director", vol, ch, sec, constraints=constraints)
        memory = self.ctx.read_agent_memory("chapter_break_director")
        if is_last_in_volume:
            break_level = "[VOLUME_END]"
        elif is_last_in_chapter:
            break_level = "[CHAPTER_END]"
        else:
            break_level = "[SECTION]"
        task = AgentTask(
            action="design",
            input_text=(
                f"本节场景设计: {plot_design.content}\n"
                f"情绪指导: {emotion_guide.content if emotion_guide.success else '无'}\n"
                f"写作指导: {direction.content if direction.success else '无'}\n"
                f"前一节结尾: {prev_section[-500:] if prev_section else '无'}\n"
                f"断章层级: {break_level}\n"
                f"卷{vol}章{ch}节{sec}\n\n"
                "请设计本节的断章策略:\n"
                "1. 推荐悬念类型\n"
                "2. 建议断点位置\n"
                "3. 结尾段落的具体写法建议\n"
                "4. 钩子衔接 (回收了上一节的什么悬念? 新埋了什么?)\n"
                "5. 避免重复的模式提醒"
            ),
        )
        break_plan = await self.chapter_break.execute(task, context=context, memory=memory)
        if break_plan.success:
            self.ctx.write_agent_memory("chapter_break_director", break_plan.notes)
            print(f"  断章策略: {break_plan.content[:300]}", flush=True)
        else:
            print("  断章策略异常, 继续执行。", flush=True)

        # Step 7: 文风执行者写正文
        self.log.step_start(7, 14, "文风执行者", "write",
                           input_size=len(full_world) + len(char_summary) + len(plot_design.content))
        context = self.context_builder.build(self.ctx, "style_executor", vol, ch, sec, constraints=constraints)
        memory = self.ctx.read_agent_memory("style_executor")
        task = AgentTask(
            action="write",
            input_text=(
                f"{constraints}\n\n"
                f"{fragment_context}\n\n"
                f"## 写作前必读: 权威参考材料\n\n"
                f"**在开始写作之前，必须仔细阅读以下世界观设定和人物卡。"
                f"正文中的所有地名、力量体系术语、势力名称、人物行为都必须能在以下材料中找到依据。**\n\n"
                f"### 完整世界观设定（所有地点、力量体系、历史事件）\n{full_world}\n\n"
                f"### 人物卡（所有角色必须严格遵循）\n{char_summary}\n\n"
                f"---\n\n"
                f"## 参考方向\n\n"
                f"### 全书梗概（全局方向参考）\n{full_synopsis[:2000] if full_synopsis else '尚未设计'}\n\n"
                f"### 本卷大纲（卷级方向参考）\n{full_volume_outline[:2000] if full_volume_outline else '尚未设计'}\n\n"
                f"---\n\n"
                f"## 本章权威大纲 — 第{sec}节场景规划（_meta.md 原文，最高优先级，不可违反）\n\n"
                f"{section_plan}\n\n"
                f"---\n\n"
                f"## 本节场景执行方案（基于权威大纲细化，必须与上方权威大纲一致）\n{plot_design.content}\n\n"
                f"---\n\n"
                f"## 写作指导\n\n"
                f"### 情绪指导\n{emotion_guide.content if emotion_guide.success else '按大纲自由发挥'}\n\n"
                f"### 总编指导\n{direction.content if direction.success else '按大纲自由发挥'}\n\n"
                f"### 断章策略\n{break_plan.content if break_plan.success else '按大纲自由发挥'}\n\n"
                f"---\n\n"
                f"## 前置检查意见（必须在写作中处理）\n\n"
                f"### 人物检查意见\n{char_issues if char_issues else '无特殊意见'}\n\n"
                f"### 世界观检查意见\n{world_issues if world_issues else '无特殊意见'}\n\n"
                f"---\n\n"
                f"## 前一节结尾 (请保持连贯)\n{prev_section[-1500:] if prev_section else '无'}\n\n"
                f"---\n\n"
                f"## 写作要求（逐条检查，违反任何一条都视为不合格）\n"
                f"0. **POV 视角人物必须与权威大纲一致** — 大纲指定谁就是谁，不得更换\n"
                f"1. **所有地点必须来自上方世界观设定**，不得生造新地名\n"
                f"2. **所有力量体系使用必须符合上方世界观设定中的规则**，不得创造新的魔法/武学名称\n"
                f"3. **人物行为必须严格符合上方人物卡**，说话风格必须与人物卡一致\n"
                f"4. **引用上方碎片和世界观中的具体设定点**，而非自由发挥\n"
                f"5. 保持与前文一致的叙事风格和人物语气\n"
                f"6. 本节字数 3000-5000 字\n"
                f"7. 开头承接前节, 结尾严格按断章策略执行\n"
                f"8. 包含完整场景 (环境描写+人物互动+冲突)\n"
                f"9. 情绪基调严格按照情绪指导\n"
                f"10. **文中出现的每个专有名词（地名/人名/势力名/技能名）必须可追溯到上方参考材料**"
            ),
        )
        result = await self.style.execute(task, context=context, memory=memory)
        if not result.success:
            print(f"错误: 正文生成失败 - {result.error}", flush=True)
            return

        self.ctx.save_section(vol, ch, sec, result.content)
        self.ctx.write_agent_memory("style_executor", result.notes)
        print(f"  正文: {len(result.content)} 字", flush=True)

        generated_text = result.content

        # ======== 逆向检查：验证 → 用户决定 → 修订 → 再验证（无限循环） ========
        all_verify_notes: list[str] = []
        verify_round = 0

        while True:
            verify_round += 1
            round_label = f"第 {verify_round} 轮" if verify_round > 1 else ""

            verify_feedback = await self._run_verification_checks(
                generated_text, full_world, char_summary, plot_design,
                break_plan, direction, emotion_guide, constraints=constraints,
                chapter_outline=chapter_outline,
                synopsis=full_synopsis or "",
                volume_outline=full_volume_outline or "",
                section_plan=section_plan,
            )

            if not verify_feedback:
                print(f"  {round_label}所有验证通过。" if verify_round > 1 else "  所有逆向验证通过。", flush=True)
                break

            print(f"\n{'='*60}", flush=True)
            print(f"  {round_label}验证: {len(verify_feedback)} 个 Agent 发现问题", flush=True)
            print(f"{'='*60}", flush=True)
            for i, (name, content) in enumerate(verify_feedback, 1):
                print(f"\n  [{i}] {name} -- 问题和修改意见:", flush=True)
                print(f"{_indent(content, '      ')}", flush=True)
            print(f"\n{'='*60}", flush=True)

            header = f"## {round_label}验证问题\n" if verify_round > 1 else "## 验证问题\n"
            all_verify_notes.append(
                header + "\n".join(
                    f"### {name}\n{content[:500]}" for name, content in verify_feedback
                )
            )

            # 自动判断是否需要修订
            decision = self._analyze_verification_feedback(verify_feedback)
            if auto_mode and decision == "ask":
                decision = "revise"  # auto 模式下连轻微问题也自动修订

            if decision == "revise":
                reason_parts = []
                critical = sum(
                    1 for _n, c in verify_feedback
                    for kw in self._CRITICAL_KEYWORDS if kw in c
                )
                if critical > 0:
                    reason_parts.append(f"{critical} 项严重问题")
                if len(verify_feedback) >= 2:
                    reason_parts.append(f"{len(verify_feedback)} 个 Agent 一致发现")
                if auto_mode:
                    reason_parts.append("auto 模式")
                reason = ", ".join(reason_parts) if reason_parts else "保守策略"
                print(f"\n  [AUTO] 自动修订 ({reason})。", flush=True)

            elif decision == "ask":
                # 单一轻微问题，让人类判断
                name, content = verify_feedback[0]
                print(f"\n  [REVIEW] {name} 提出轻微建议，是否需要根据此意见修订?", flush=True)
                print(f"  {_indent(content[:200], '  ')}", flush=True)
                print("\n  是否修订? (y/n/回车=修订): ", end="", flush=True)
                choice = (await asyncio.to_thread(input)).strip().lower()
                if choice in ("n", "no", "否"):
                    print("  跳过修订，验证问题将记录到 state.md 供后续参考。", flush=True)
                    break
                print("  开始修订...", flush=True)
            else:
                # skip — 不应发生（verify_feedback 非空时不应为 skip）
                break

            feedback_text = "\n\n".join(
                f"### {name}\n{content}" for name, content in verify_feedback
            )
            revise_task = AgentTask(
                action="revise",
                input_text=(
                    f"{constraints}\n\n"
                    f"## 当前正文\n{generated_text}\n\n"
                    f"## 验证反馈（必须逐条修正）\n\n{feedback_text}\n\n"
                    "请根据以上验证反馈修正正文。逐条处理每个问题，输出完整的修正后正文。"
                ),
            )
            context = self.context_builder.build(self.ctx, "style_executor", vol, ch, sec, constraints=constraints)
            memory = self.ctx.read_agent_memory("style_executor")
            revised = await self.style.execute(revise_task, context=context, memory=memory)
            if revised.success and revised.content.strip():
                generated_text = revised.content
                self.ctx.save_section(vol, ch, sec, generated_text)
                self.ctx.write_agent_memory("style_executor", revised.notes)
                print(f"  修订后正文: {len(generated_text)} 字", flush=True)
            else:
                print("  修订失败，保留当前正文。", flush=True)
                break

        all_verify_notes_str = "\n".join(all_verify_notes)

        # Step 14: 状态记录员更新剧情状态（含版本化保存）
        await self._update_state(vol, ch, sec, generated_text, all_verify_notes_str)

        # 重写模式下，失效后续所有节
        if is_rewrite:
            stale_count = self.ctx.invalidate_sections_after(vol, ch, sec)
            if stale_count > 0:
                print(f"  [WARN] 重写完本节，后续 {stale_count} 节状态已标记为 stale。", flush=True)
                print("  请按顺序重新生成后续节以恢复有效状态。", flush=True)

        self.ctx.mark_progress(vol, ch, sec)
        self._update_status("writing")
        print(f"\n第 {vol} 卷 第 {ch} 章 第 {sec} 节写作完成!", flush=True)
        self.log.summary()

    async def write_chapter(self, vol: int, ch: int, force: bool = False,
                           auto_mode: bool = False) -> None:
        """写整章: 循环写每节"""
        cfg = self.ctx.get_config()
        spc = cfg["sections_per_chapter"]
        for sec in range(1, spc + 1):
            await self.write_section(vol, ch, sec, force=force, auto_mode=auto_mode)

    # ======== 逆向验证决策 ========

    # 判定反馈严重程度的关键词
    _CRITICAL_KEYWORDS = [
        "矛盾", "不一致", "违背", "违反", "不符合", "生造", "不存在于",
        "与.*冲突", "错误", "严重偏差", "完全偏离", "未遵循",
    ]
    _MINOR_KEYWORDS = [
        "建议", "可优化", "略微", "轻微", "可考虑", "可改进",
        "调整", "微调", "增强", "补充", "丰富",
    ]

    @classmethod
    def _analyze_verification_feedback(cls, feedback: list[tuple[str, str]]) -> str:
        """分析逆向验证反馈，返回决策: 'revise' | 'ask' | 'skip'

        决策逻辑:
        - 无反馈 → skip
        - 含严重关键词（矛盾/不一致/违背） → revise
        - >=2 个 Agent 同时发现问题 → revise
        - 仅 1 个 Agent 报告非严重问题 → ask（让人类判断）
        - 其他 → revise（默认保守修订）
        """
        if not feedback:
            return "skip"

        total = len(feedback)
        critical_count = 0
        for _name, content in feedback:
            for kw in cls._CRITICAL_KEYWORDS:
                if kw in content:
                    critical_count += 1
                    break

        if critical_count > 0:
            return "revise"
        if total >= 2:
            return "revise"

        # 单 Agent 报告，检查是否为轻微问题
        _name, content = feedback[0]
        for kw in cls._MINOR_KEYWORDS:
            if kw in content:
                return "ask"

        # 默认为修订（保守策略）
        return "revise"

    # ======== 状态更新 ========

    async def _update_state(self, vol: int, ch: int, sec: int, section_content: str,
                            verify_notes: str = "") -> None:
        """调用 StateManager 根据最新正文更新 state.md，并保存版本化快照"""
        # 获取本节对应的前置 state（而非全局 state.md）
        current_state = self.ctx.get_state_for_section(vol, ch, sec)
        timeline = self.ctx.get_timeline()
        memory = self.ctx.read_agent_memory("state_manager")

        task = AgentTask(
            action="update",
            input_text=(
                f"当前进度: 第 {vol} 卷 第 {ch} 章 第 {sec} 节\n\n"
                f"## 最新正文内容\n{section_content[:3000]}\n\n"
                f"## 当前时间线\n{timeline[:500] if timeline else '无'}\n\n"
                f"## 验证反馈（已知问题，供后续写作参考）\n{verify_notes if verify_notes else '无'}\n\n"
                f"## 当前状态文件\n{current_state if current_state else '无 (首次创建)'}\n\n"
                "请根据最新正文内容和时间推进, 更新完整的 state.md。"
                "注意更新: 角色状态、主线推进、伏笔变化 (新的/回收的)、"
                "支线推进 (含背景推演)、时间线变化。"
                "验证反馈中的已知问题也要记录到状态文件中，供后续写作参考。"
            ),
        )
        result = await self.state.execute(task, memory=memory)
        if result.success:
            # 保存全局 state.md（向后兼容）
            self.ctx.save_state(result.content)
            # 保存版本化 state 快照
            self.ctx.save_state_version(vol, ch, sec, result.content)
            # 标记本节状态有效
            self.ctx.mark_section_valid(vol, ch, sec)
            self.ctx.write_agent_memory("state_manager", result.notes)
            print("  状态已更新。", flush=True)
            if result.notes:
                print(f"  观察笔记: {result.notes[:200]}", flush=True)
        else:
            print(f"  状态更新失败: {result.error}", flush=True)

    # ======== 碎片扫描 ========

    async def _auto_scan_fragments(self) -> None:
        """检查碎片是否有变更，有则重新生成摘要"""
        fragments = self.ctx.list_fragments()
        if not fragments:
            return

        last_scan = self.ctx.get_fragment_scan_status()
        newest_mtime = max(f["modified"] for f in fragments)
        if newest_mtime <= last_scan:
            return

        self.log.section(f"碎片扫描: 检测到 {len(fragments)} 个碎片, 正在生成参考摘要...")
        await self._scan_fragments()

    async def _scan_fragments(self, verbose: bool = True) -> None:
        """扫描所有碎片，调用 LLM 生成 fragments_summary.md"""
        fragments = self.ctx.list_fragments()
        if not fragments:
            self.ctx.save_fragments_summary("# 碎片参考摘要\n\n尚无碎片。")
            return

        priority_keywords = ["顶层设定", "设定", "时间线的框架", "行文风格准则"]
        fragments.sort(key=lambda f: next((i for i, kw in enumerate(priority_keywords) if kw in f.get("title", "")), len(priority_keywords)))
        parts = []
        for f in fragments:
            content = self.ctx.get_fragment(f["id"])
            parts.append(f"## 碎片 {f['id']}: {f['title']}\n{content[:10000]}")

        all_fragments = "\n\n---\n\n".join(parts)

        self.log.step_start(1, 1, "文风执行者", "summarize",
                           input_size=len(all_fragments))
        task = AgentTask(
            action="summarize",
            input_text=(
                f"以下是创作过程中积累的碎片化参考文字。请按以下分类整理为一个精炼的参考摘要:\n\n"
                f"分类:\n"
                f"1. 风格参考 - 行文风格、语言节奏、描写方式的要求\n"
                f"2. 桥段素材 - 具体的场景、情节、对话片段\n"
                f"3. 世界观补充/修正 - 对设定的补充、修改、澄清\n"
                f"4. 写作方向 - 情节走向、人物处理、节奏控制的建议\n"
                f"5. 人物细节 - 角色行为、语气、关系的补充说明\n\n"
                f"每个条目保留核心信息(2-3句话), 标注碎片来源ID。\n"
                f"忽略标记为[废弃]或[已使用]的内容。\n\n"
                f"碎片内容:\n{all_fragments}"
            ),
        )
        result = await self.style.execute(task)
        if result.success:
            summary = f"# 碎片参考摘要\n\n最后更新: 共 {len(fragments)} 个碎片\n\n{result.content}"
            self.ctx.save_fragments_summary(summary)
            self.ctx.set_fragment_scan_status(
                max(f["modified"] for f in fragments)
            )
            if verbose:
                print(f"摘要已更新 ({len(summary)} 字符)。", flush=True)
        else:
            if verbose:
                print(f"摘要生成失败: {result.error}", flush=True)

    # ======== 辅助 ========

    def _get_chapter_outline(self, vol: int, ch: int) -> str:
        meta = self.ctx.get_chapter_meta(vol, ch)
        if meta and "待生成" not in meta:
            return meta

        vol_outline = self.ctx.get_volume_outline(vol)
        if not vol_outline:
            print(f"  [WARN] 第 {vol} 卷大纲尚未生成,第 {ch} 章无可参考的大纲。", flush=True)
            return f"第 {ch} 章 (大纲尚未设计)"

        lines = vol_outline.splitlines()
        capture = False
        chapter_lines = []
        markers = [f"第{ch}章", f"第 {ch} 章", f"Chapter {ch}"]
        for line in lines:
            if any(m in line for m in markers):
                capture = True
            if capture:
                chapter_lines.append(line)
                for i in range(ch + 1, ch + 10):
                    if f"第{i}章" in line or f"Chapter {i}" in line:
                        capture = False
                        break
            if capture is False and chapter_lines:
                break
        if chapter_lines:
            return "\n".join(chapter_lines)
        print(f"  [WARN] 第 {vol} 卷大纲中未找到第 {ch} 章的标记,将使用卷大纲前 500 字作回退。", flush=True)
        return f"第 {ch} 章 (大纲未明确指定本章)\n\n卷大纲摘要:\n{vol_outline[:500]}"

    async def _run_verification_checks(self, generated_text: str, full_world: str,
                                        char_summary: str, plot_design,
                                        break_plan, direction, emotion_guide,
                                        constraints: str = "",
                                        chapter_outline: str = "",
                                        synopsis: str = "",
                                        volume_outline: str = "",
                                        section_plan: str = "",
                                        ) -> list[tuple[str, str]]:
        """运行全部 6 个逆向验证步骤（并行），返回未通过的 [(agent_name, feedback), ...]"""
        checks: list[tuple[str, object, AgentTask]] = []

        if break_plan and break_plan.success:
            checks.append(("断章决策者", self.chapter_break, AgentTask(
                action="verify",
                input_text=(
                    f"## 你的断章策略\n{break_plan.content}\n\n"
                    f"## 实际生成的正文 (结尾部分)\n{generated_text[-2000:]}\n\n"
                    "请检查正文结尾是否严格按你的断章策略执行。如果完全符合回复 [通过]，否则列出偏差。"
                ),
            )))

        if direction and direction.success:
            checks.append(("总编", self.editor, AgentTask(
                action="verify",
                input_text=(
                    f"## 全书梗概（全局方向参考）\n{synopsis[:1000] if synopsis else '无'}\n\n"
                    f"## 本卷大纲（卷级弧线参考）\n{volume_outline[:1000] if volume_outline else '无'}\n\n"
                    f"## 本章权威大纲 — 本节规划（_meta.md 原文）\n{section_plan if section_plan else chapter_outline[:1000] if chapter_outline else '无'}\n\n"
                    f"## 你的写作指导\n{direction.content}\n\n"
                    f"## 实际生成的正文\n{generated_text[:3000]}\n\n"
                    "请检查正文是否遵循了你的写作指导，且不偏离全书梗概、卷大纲及章大纲的方向。如果完全符合回复 [通过]，否则列出偏差。"
                ),
            )))

        if emotion_guide and emotion_guide.success:
            checks.append(("情绪曲线管控", self.emotion, AgentTask(
                action="verify",
                input_text=(
                    f"## 你的情绪指导\n{emotion_guide.content}\n\n"
                    f"## 实际生成的正文\n{generated_text[:3000]}\n\n"
                    "请检查正文的实际情绪执行是否符合你的指导。如果完全符合回复 [通过]，否则列出偏差。"
                ),
            )))

        checks.append(("世界观管理员", self.world, AgentTask(
            action="verify",
            input_text=(
                f"{constraints}\n\n"
                f"## 完整世界观设定\n{full_world}\n\n"
                f"## 实际生成的正文\n{generated_text[:3000]}\n\n"
                "请逐项检查正文是否违背了世界观设定。也检查是否违反了上方故事约束中的规则。如果完全符合回复 [通过]，否则列出矛盾。"
            ),
        )))

        checks.append(("人物导演", self.character, AgentTask(
            action="verify",
            input_text=(
                f"## 人物卡\n{char_summary}\n\n"
                f"## 实际生成的正文\n{generated_text[:3000]}\n\n"
                "请检查正文中的角色行为是否符合人物卡设定。如果完全符合回复 [通过]，否则列出偏差。"
            ),
        )))

        checks.append(("剧情编剧", self.plot, AgentTask(
            action="verify",
            input_text=(
                f"{constraints}\n\n"
                f"## 全书梗概（最高层大纲参考）\n{synopsis[:1500] if synopsis else '无'}\n\n"
                f"## 本卷大纲（卷级弧线参考）\n{volume_outline[:1500] if volume_outline else '无'}\n\n"
                f"## 本章权威大纲 — 本节规划（_meta.md，最高优先级）\n{section_plan if section_plan else chapter_outline[:2000] if chapter_outline else '无'}\n\n"
                f"## 你的节级场景设计\n{plot_design.content}\n\n"
                f"## 实际生成的正文\n{generated_text[:3000]}\n\n"
                "请检查正文是否按场景设计执行，且不偏离章节大纲、卷大纲及全书梗概的方向。如果完全符合回复 [通过]，否则列出偏差。"
            ),
        )))

        feedback: list[tuple[str, str]] = []

        async def _run_one(name: str, agent, task: AgentTask):
            try:
                result = await agent.execute(task)
                return name, result
            except Exception as e:
                print(f"  {name}验证异常: {e}", flush=True)
                return name, None

        tasks = [_run_one(name, agent, task) for name, agent, task in checks]
        for coro in asyncio.as_completed(tasks):
            name, result = await coro
            if result is None or not result.success:
                continue
            memory_map = {
                "断章决策者": "chapter_break_director",
                "总编": "editor_in_chief",
                "情绪曲线管控": "emotion_controller",
                "世界观管理员": "world_builder",
                "人物导演": "character_director",
                "剧情编剧": "plot_writer",
            }
            agent_file = memory_map.get(name, "")
            if agent_file:
                self.ctx.write_agent_memory(agent_file, result.notes)
            if "通过" not in result.content:
                feedback.append((name, result.content))
                print(f"  {name}验证发现偏差: {result.content[:200]}", flush=True)
            else:
                print(f"  {name}验证通过。", flush=True)

        return feedback

    def _merge_agent_memory(self, agent_id: str, new_notes: str) -> None:
        """合并新的 Agent 记忆而不是覆写，保留之前领域的 [ACTIVE] 规则"""
        if not new_notes:
            return
        existing = self.ctx.read_agent_memory(agent_id)
        if not existing or "尚未开始" in existing:
            self.ctx.write_agent_memory(agent_id, new_notes)
            return
        new_blocks = self._extract_note_blocks(new_notes)
        existing_blocks = self._extract_note_blocks(existing)
        merged_blocks = []
        seen = set()
        for entry, kind in existing_blocks:
            key = entry.split("\n")[0].strip()[:80]
            if key not in seen:
                merged_blocks.append((entry, kind))
                seen.add(key)
        for entry, kind in new_blocks:
            key = entry.split("\n")[0].strip()[:80]
            if key not in seen:
                merged_blocks.append((entry, kind))
                seen.add(key)
        merged = "\n\n".join(f"[{kind}] {entry}" for entry, kind in merged_blocks)
        self.ctx.write_agent_memory(agent_id, merged)

    @staticmethod
    def _extract_section_from_meta(chapter_meta: str, sec: int) -> str:
        if not chapter_meta:
            return ""

        target = f"section_{sec:03d}"
        lines = chapter_meta.splitlines()
        start = None
        for i, line in enumerate(lines):
            if f"(section_{sec:03d})" in line or (
                "section_" in line and target in line and line.strip().startswith("##")
            ):
                start = i
                break

        if start is None:
            for i, line in enumerate(lines):
                if re.match(rf"^##\s+场景{sec}\b", line):
                    start = i
                    break
            if start is None:
                return chapter_meta

        end = len(lines)
        for i in range(start + 1, len(lines)):
            if re.match(r"^##\s+场景\d+", lines[i]):
                end = i
                break

        return "\n".join(lines[start:end])

    @staticmethod
    def _extract_note_blocks(text: str) -> list[tuple[str, str]]:
        blocks = []
        current_kind = ""
        current_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[ACTIVE]") or stripped.startswith("[CONTRADICTION]"):
                if current_lines and current_kind:
                    blocks.append(("\n".join(current_lines), current_kind))
                tag_end = stripped.index("]") + 1
                current_kind = stripped[1:tag_end - 1]
                current_lines = [stripped[tag_end:].strip()]
            elif stripped.startswith("#") or stripped.startswith("```"):
                continue
            elif stripped:
                current_lines.append(stripped)
            elif not stripped and current_lines:
                current_lines.append("")
        if current_lines and current_kind:
            blocks.append(("\n".join(current_lines), current_kind))
        return blocks

    def _update_status(self, status: str) -> None:
        meta = self.ctx.get_meta()
        meta["status"] = status
        self.ctx.save_meta(meta)


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())
