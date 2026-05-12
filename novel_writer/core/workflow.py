from pathlib import Path

from novel_writer.core.context import ProjectContext
from novel_writer.core.llm import LLMClient
from novel_writer.agents.base import AgentTask
from novel_writer.agents.editor_in_chief import EditorInChief
from novel_writer.agents.world_builder import WorldBuilder
from novel_writer.agents.character_director import CharacterDirector
from novel_writer.agents.plot_writer import PlotWriter
from novel_writer.agents.style_executor import StyleExecutor
from novel_writer.agents.state_manager import StateManager
from novel_writer.core.context_builder import ContextBuilder


class WorkflowOrchestrator:
    """编排 Agent 协作流程"""

    def __init__(self, project_path: Path):
        self.ctx = ProjectContext(project_path)
        self.llm = LLMClient()
        self.editor = EditorInChief(self.llm)
        self.world = WorldBuilder(self.llm)
        self.character = CharacterDirector(self.llm)
        self.plot = PlotWriter(self.llm)
        self.style = StyleExecutor(self.llm)
        self.state = StateManager(self.llm)
        self.context_builder = ContextBuilder()

    # ======== 世界观构建 ========

    # 生成顺序: 基础领域先, 时间线放到最后 (需要引用所有其他领域)
    WORLD_DOMAINS = [
        "geography", "magic_system", "races",
        "politics", "history", "culture", "glossary", "timeline",
    ]

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

    def _generate_domain(self, domain: str, premise: str, cross_refs: str) -> bool:
        """生成单个领域: WorldBuilder → Editor 审校 → (可选) 修订"""
        name = self.DOMAIN_NAMES.get(domain, domain)
        print(f"\n{'─' * 40}")
        print(f"  领域: {name} ({domain})")
        print(f"{'─' * 40}")

        # 收集已有领域作为交叉引用
        memory = self.ctx.read_agent_memory("world_builder")
        context = self.ctx.get_relevant_world_domains(
            [d for d in self.WORLD_DOMAINS if d != domain and self.ctx.get_world_domain(d)]
        )

        # Step 1: 生成
        detail = self.DOMAIN_PROMPTS.get(domain, "")
        task = AgentTask(
            action="generate",
            input_text=(
                f"前提: {premise}\n\n"
                f"领域: {name}\n"
                f"{detail}\n\n"
                f"{cross_refs}\n"
                "确保本领域内容自洽, 且与已生成的其他领域保持一致。"
            ),
        )
        result = self.world.execute(task, context=context, memory=memory)
        if not result.success:
            print(f"  生成失败: {result.error}")
            return False
        self.ctx.save_world_domain(domain, result.content)
        self.ctx.write_agent_memory("world_builder", result.notes)
        print(f"  生成: {len(result.content)} 字")

        # Step 2: 总编审校
        task = AgentTask(
            action="review",
            input_text=(
                f"审校 {name} 设定。从完整性、自洽性、与整体世界观的协调性评估。\n"
                "如果没有问题回复[通过], 否则给出修改意见。"
            ),
        )
        review = self.editor.execute(task, context=context, memory=memory)
        if review.success and "通过" not in review.content:
            print(f"  审校意见: {review.content[:200]}...")
            # 修订
            task = AgentTask(
                action="revise",
                input_text=(
                    f"当前 {name} 设定:\n{result.content[:2000]}\n\n"
                    f"修改意见:\n{review.content}\n\n请输出修订版。"
                ),
            )
            revised = self.world.execute(task, context=context, memory=memory)
            if revised.success:
                self.ctx.save_world_domain(domain, revised.content)
                print(f"  修订: {len(revised.content)} 字")
        else:
            print(f"  审校通过。")

        # 更新索引
        idx = self.ctx.get_world_index()
        content = self.ctx.get_world_domain(domain)
        idx[domain] = content.split("\n")[0].lstrip("#").strip()[:60] if content else "已生成"
        self.ctx.save_world_index(idx)
        return True

    def generate_world(self, premise: str = "") -> None:
        """逐领域生成完整世界观"""
        print("=" * 50)
        print("  世界观生成 (逐领域)")
        print("=" * 50)

        if not premise:
            meta = self.ctx.get_meta()
            premise = f"类型: {meta.get('genre', '未知')}, 梗概: {meta.get('logline', '未知')}"

        domains = self.WORLD_DOMAINS
        succeeded = 0

        for i, domain in enumerate(domains, 1):
            print(f"\n{'=' * 40}")
            print(f"  [{i}/{len(domains)}] {self.DOMAIN_NAMES.get(domain, domain)}")
            print(f"{'=' * 40}")

            # 交叉引用: 告诉 LLM 已生成的内容摘要
            cross_refs = ""
            if i > 1:
                generated = [d for d in domains[:i-1]
                           if self.ctx.get_world_domain(d) and "待生成" not in self.ctx.get_world_domain(d)]
                if generated:
                    cross_refs = "已生成领域摘要:\n" + "\n".join(
                        f"- {self.DOMAIN_NAMES.get(d, d)}: {self.ctx.get_world_index().get(d, '')}"
                        for d in generated
                    )

            if self._generate_domain(domain, premise, cross_refs):
                succeeded += 1
            else:
                print(f"  跳过 {domain}, 继续下一个。")

        self._update_status("world_building")
        print(f"\n{'=' * 50}")
        print(f"  世界观生成完成! ({succeeded}/{len(domains)} 领域)")
        print(f"{'=' * 50}")

    # ======== 人物创建 ========

    # ======== 人物系统 ========

    def create_character(self, name: str, role: str = "主角",
                         faction: str = "无", specs: str = "") -> None:
        """创建单个人物卡"""
        print("=" * 50)
        print(f"  创建人物: {name}")
        print("=" * 50)

        # 收集世界观上下文
        world_context = self._get_world_context_summary()

        # Step 1: 人物导演生成人物卡
        print("\n[1/3] 人物导演生成人物卡...")
        memory = self.ctx.read_agent_memory("character_director")
        extra = f"\n补充要求: {specs}" if specs else ""
        task = AgentTask(
            action="generate",
            input_text=(
                f"创建一个人物: 姓名={name}, 定位={role}, 所属势力={faction}{extra}\n\n"
                f"世界背景:\n{world_context}\n\n"
                "请创建完整的人物卡:\n"
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
        result = self.character.execute(task, memory=memory)
        if not result.success:
            print(f"错误: 生成失败 - {result.error}")
            return
        print(f"  生成: {len(result.content)} 字")

        # Step 2: 世界观管理员检查一致性
        print("\n[2/3] 世界观管理员检查人物与设定一致性...")
        task = AgentTask(
            action="check",
            input_text=(
                f"世界时间线摘要:\n{self.ctx.get_world_timeline()[:1500]}\n\n"
                f"人物卡:\n{result.content[:2000]}\n\n"
                "检查人物设定是否与世界时间线和世界观有矛盾。一致回复[一致], 否则列出具体矛盾。"
            ),
        )
        check = self.world.execute(task)
        if check.success and "一致" not in check.content:
            print(f"  发现问题:\n{_indent(check.content[:300])}")
        else:
            print("  检查通过。")

        # Step 3: 总编审校
        print("\n[3/3] 总编审校人物卡...")
        task = AgentTask(
            action="review",
            input_text=(
                f"审校人物卡, 从丰满度、商业吸引力、与其他已有角色的平衡性评估。\n"
                f"人物卡:\n{result.content[:2000]}"
            ),
        )
        review = self.editor.execute(task)
        if review.success and "通过" not in review.content:
            print(f"  审校意见: {review.content[:300]}")
            # 修订
            if "通过" not in review.content:
                task = AgentTask(
                    action="revise",
                    input_text=(
                        f"当前人物卡:\n{result.content[:2000]}\n\n"
                        f"修改意见:\n{review.content}\n\n输出修订版。"
                    ),
                )
                revised = self.character.execute(task, memory=memory)
                if revised.success:
                    result = revised
                    print(f"  修订完成: {len(revised.content)} 字")

        # 分配人物ID并保存
        char_id = self._next_char_id(role)
        self.ctx.save_character(char_id, result.content)
        self.ctx.write_agent_memory("character_director", result.notes)

        # 更新人物索引
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
        print(f"\n人物 {name} ({char_id}) 创建完成!")

    def create_relationship(self, char_a: str, char_b: str,
                            rel_type: str = "关联") -> None:
        """生成两个人物间的关系描述"""
        print(f"\n生成人物关系: {char_a} ↔ {char_b} ({rel_type})")

        card_a = self.ctx.get_character(char_a)
        card_b = self.ctx.get_character(char_b)
        if not card_a or not card_b:
            print(f"  错误: 人物卡不存在。")
            return

        current_rels = self.ctx.get_relationships()
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
        result = self.character.execute(task)
        if result.success:
            # 追加到关系文件
            new_content = current_rels if "尚未建立" not in current_rels else "# 人物关系矩阵\n\n"
            new_content += f"\n{result.content}\n"
            self.ctx.save_relationships(new_content)
            print(f"  关系已保存。")
        else:
            print(f"  生成失败: {result.error}")

    def create_faction(self, name: str, description: str = "") -> None:
        """创建势力"""
        print("=" * 50)
        print(f"  创建势力: {name}")
        print("=" * 50)

        world_context = self._get_world_context_summary()
        task = AgentTask(
            action="generate",
            input_text=(
                f"创建势力: {name}\n"
                f"补充说明: {description}\n\n"
                f"世界背景:\n{world_context}\n\n"
                "请生成势力描述:\n"
                "1. 势力全称和简称\n"
                "2. 势力定位 (国家/宗门/组织/地下势力等)\n"
                "3. 核心理念与目标\n"
                "4. 组织结构 (领导层/分支/成员构成)\n"
                "5. 历史渊源 (与世界时间线的关联)\n"
                "6. 主要资源与力量\n"
                "7. 与其他势力的关系"
            ),
        )
        result = self.character.execute(task)
        if result.success:
            self.ctx.save_faction(name, result.content)
            # 更新势力索引
            fidx = self.ctx.get_faction_index()
            if "尚未建立" in fidx:
                fidx = "# 势力索引\n\n"
            fidx += f"\n## {name}\n{result.content[:200]}...\n"
            self.ctx.save_faction_index(fidx)
            print(f"\n势力 {name} 创建完成!")
        else:
            print(f"创建失败: {result.error}")

    def _get_world_context_summary(self) -> str:
        """获取世界观上下文摘要(供人物创建使用)"""
        parts = []
        # 世界时间线摘要
        tl = self.ctx.get_world_timeline()
        if tl and "待生成" not in tl:
            # 提取各时代标题
            parts.append("## 世界时间线概览")
            for line in tl.splitlines():
                if line.startswith("## 第") or line.startswith("### "):
                    parts.append(line)
            parts.append("")
        # 世界领域索引
        idx = self.ctx.get_world_index()
        if idx:
            parts.append("## 世界领域\n" + "\n".join(
                f"- {d}: {s}" for d, s in idx.items() if "待生成" not in s
            ))
        return "\n".join(parts) if parts else "尚未建立世界观。"

    def _next_char_id(self, role: str) -> str:
        idx = self.ctx.get_character_index()
        prefix = {
            "主角": "protagonist", "反派": "antagonist",
            "配角": "supporting", "导师": "mentor",
        }.get(role, "character")
        count = sum(1 for e in idx if e["id"].startswith(prefix))
        return f"{prefix}_{count + 1:03d}"

    # ======== 大纲设计（三层） ========

    def generate_synopsis(self) -> None:
        """第一层: 全书梗概 (500-1000字)"""
        print("=" * 50)
        print("  全书梗概")
        print("=" * 50)

        world_summary = self._get_world_context_summary()
        char_summary = self._get_character_summary()
        meta = self.ctx.get_meta()

        print("\n[1/2] 剧情编剧生成全书梗概...")
        task = AgentTask(
            action="generate",
            input_text=(
                f"类型: {meta.get('genre', '?')}, 梗概: {meta.get('logline', '?')}\n"
                f"规划: {meta.get('target_volumes', 10)}卷 x "
                f"{meta.get('target_chapters_per_volume', 15)}章 x "
                f"{meta.get('target_sections_per_chapter', 3)}节\n\n"
                f"世界观摘要:\n{world_summary}\n\n"
                f"人物摘要:\n{char_summary}\n\n"
                "请设计全书梗概 (500-1000字):\n"
                "1. 主线剧情一句话\n"
                "2. 核心矛盾与主题\n"
                "3. 三幕式整体结构 (每幕对应哪些卷)\n"
                "4. 主要人物的角色轨迹概述\n"
                "5. 预设的结局方向"
            ),
        )
        result = self.plot.execute(task)
        if not result.success:
            print(f"错误: {result.error}")
            return
        self.ctx.save_synopsis(result.content)
        self.ctx.write_agent_memory("plot_writer", result.notes)
        print(f"  梗概: {len(result.content)} 字")

        # 总编审校
        print("\n[2/2] 总编审校梗概...")
        task = AgentTask(
            action="review",
            input_text=(
                f"审校全书梗概, 从商业吸引力、结构完整度、矛盾设置评估。\n"
                f"梗概:\n{result.content}"
            ),
        )
        review = self.editor.execute(task)
        if review.success:
            print(f"  审校: {review.content[:300]}")
            self.ctx.write_agent_memory("editor_in_chief", review.notes)

        self._update_status("outlining")
        print("\n全书梗概完成!")

    def generate_volume_outline(self, vol: int, direction: str = "") -> None:
        """第二层: 卷级弧线 (本卷核心冲突/角色成长/每章概要)"""
        print("=" * 50)
        print(f"  第 {vol} 卷大纲")
        print("=" * 50)

        synopsis = self.ctx.get_synopsis()
        prev_vol_outline = ""
        if vol > 1:
            prev_vol_outline = self.ctx.get_volume_outline(vol - 1)[:1000]

        world_summary = self._get_world_context_summary()
        char_summary = self._get_character_summary()
        cfg = self.ctx.get_config()

        print("\n[1/2] 剧情编剧设计卷弧线...")
        extra = f"\n本卷方向: {direction}" if direction else ""
        task = AgentTask(
            action="generate",
            input_text=(
                f"全书梗概:\n{synopsis[:1500]}\n\n"
                f"上一卷结尾:\n{prev_vol_outline[:500] if prev_vol_outline else '无 (第1卷)'}\n"
                f"世界观摘要:\n{world_summary[:1500]}\n"
                f"人物摘要:\n{char_summary[:1000]}\n"
                f"本卷规划: {cfg['chapters_per_volume']}章 x {cfg['sections_per_chapter']}节{extra}\n\n"
                "请设计第 {vol} 卷大纲:\n"
                "1. 本卷标题和核心主题\n"
                f"2. 本卷主线冲突和矛盾升级方向\n"
                "3. 本卷涉及的主要人物及其成长\n"
                f"4. 每章概要 (一句话核心冲突+钩子)\n"
                "5. 本卷伏笔埋设计划\n"
                "6. 本卷与全书结局的关联"
            ).replace("{vol}", str(vol)),
        )
        result = self.plot.execute(task)
        if not result.success:
            print(f"错误: {result.error}")
            return
        self.ctx.save_volume_outline(vol, result.content)
        self.ctx.write_agent_memory("plot_writer", result.notes)
        print(f"  卷大纲: {len(result.content)} 字")

        print("\n[2/2] 总编审校卷大纲...")
        task = AgentTask(
            action="review",
            input_text=(
                f"审校第{vol}卷大纲。从矛盾升级梯度、节奏、与前卷的衔接、伏笔合理性评估。\n"
                f"卷大纲:\n{result.content[:2000]}"
            ),
        )
        review = self.editor.execute(task)
        if review.success:
            self.ctx.write_agent_memory("editor_in_chief", review.notes)
            print(f"  审校: {review.content[:300]}")

        self._update_status("outlining")
        print(f"\n第 {vol} 卷大纲完成!")

    def generate_chapter_scenes(self, vol: int, ch: int) -> None:
        """第三层: 章节场景设计 (_meta.md)"""
        print(f"\n第 {vol} 卷 第 {ch} 章场景设计...")

        vol_outline = self.ctx.get_volume_outline(vol)
        if not vol_outline:
            print(f"  错误: 第{vol}卷大纲尚未生成。")
            return

        char_summary = self._get_character_summary()
        world_context = self._get_world_context_summary()
        cfg = self.ctx.get_config()

        task = AgentTask(
            action="design",
            input_text=(
                f"第{vol}卷大纲:\n{vol_outline[:2000]}\n\n"
                f"人物摘要:\n{char_summary[:1000]}\n"
                f"世界观摘要:\n{world_context[:1000]}\n\n"
                f"请为第{vol}卷第{ch}章设计场景序列 ({cfg['sections_per_chapter']}个场景):\n\n"
                "格式:\n"
                "## 场景N (section_00N): 场景标题\n"
                "- POV: 视角人物\n"
                "- 地点: 具体地点\n"
                "- 出场人物: 人物名列表\n"
                "- 世界观元素: [领域:具体元素]\n"
                "- 核心冲突: 一句话冲突描述\n"
                "- 字数目标: 3000-5000\n\n"
                "要求: 场景间有机衔接, 本章整体有冲突升级和结尾钩子。"
            ),
        )
        result = self.plot.execute(task)
        if result.success:
            self.ctx.save_chapter_meta(vol, ch, result.content)
            self.ctx.write_agent_memory("plot_writer", result.notes)
            print(f"  第{ch}章场景: {len(result.content)} 字")
        else:
            print(f"  错误: {result.error}")

    def generate_volume_chapters(self, vol: int) -> None:
        """为整卷生成所有章的逐章场景设计"""
        cfg = self.ctx.get_config()
        cpc = cfg["chapters_per_volume"]
        print("=" * 50)
        print(f"  第 {vol} 卷: 逐章场景设计 ({cpc}章)")
        print("=" * 50)
        for ch in range(1, cpc + 1):
            self.generate_chapter_scenes(vol, ch)

    def _get_character_summary(self) -> str:
        """获取人物摘要"""
        idx = self.ctx.get_character_index()
        if not idx:
            return "尚未创建人物。"
        return "\n".join(
            f"- [{e['id']}] {e['name']} ({e['role']}, {e['faction']}) [{e['status']}]"
            for e in idx
        )

    # ======== 章节写作 ========

    def write_section(self, vol: int, ch: int, sec: int) -> None:
        """写指定节: 6 步流水线 (含状态更新)"""
        print("=" * 50)
        print(f"  第 {vol} 卷 第 {ch} 章 第 {sec} 节 写作")
        print("=" * 50)

        cfg = self.ctx.get_config()

        # 自动扫描碎片: 检查是否有新增/变更
        self._auto_scan_fragments()

        # 提取本章大纲/场景设计
        chapter_meta = self.ctx.get_chapter_meta(vol, ch)
        chapter_outline = chapter_meta or self._get_chapter_outline(vol, ch)

        # 前一节
        prev_section = self.ctx.get_prev_section(vol, ch, sec)

        # Step 1: 剧情编剧设计/刷新场景
        print(f"\n[1/6] 剧情编剧刷新场景...")
        task = AgentTask(
            action="design",
            input_text=(
                f"本章概要: {chapter_outline[:1500]}\n"
                f"第{sec}节场景要求: 设计本节的完整场景, 标注目标/冲突/转折\n"
                f"前一节结尾: {prev_section[:500] if prev_section else '无'}\n"
                f"人物卡: {self._get_character_summary()[:1500]}"
            ),
        )
        plot_design = self.plot.execute(task)
        if not plot_design.success:
            print(f"错误: 场景设计失败 - {plot_design.error}")
            return
        print("  场景设计完成。")

        # Step 2: 人物导演检查角色行为
        print(f"\n[2/6] 人物导演检查角色行为...")
        task = AgentTask(
            action="check",
            input_text=(
                f"本节场景设计: {plot_design.content}\n"
                f"人物卡: {self._get_character_summary()[:1500]}\n"
                "检查是否有角色行为不符合人物卡设定的情况。如果没有问题, 回复[一致]。"
            ),
        )
        char_check = self.character.execute(task)
        if char_check.success and "一致" not in char_check.content:
            print(f"  人物导演提出注意: {char_check.content[:300]}")
        else:
            print("  角色行为检查通过。")

        # Step 3: 世界观管理员检查设定
        print(f"\n[3/6] 世界观管理员检查设定...")
        task = AgentTask(
            action="check",
            input_text=(
                f"本节场景设计: {plot_design.content}\n"
                f"世界观设定: {self._get_world_context_summary()[:1500]}\n"
                "检查是否有与世界观设定矛盾的地方。如果没有问题, 回复[一致]。"
            ),
        )
        world_check = self.world.execute(task)
        if world_check.success and "一致" not in world_check.content:
            print(f"  世界观管理员提出注意: {world_check.content[:300]}")
        else:
            print("  世界观设定检查通过。")

        # Step 4: 总编指导
        print(f"\n[4/6] 总编给出写作指导...")
        context = self.context_builder.build(self.ctx, "editor_in_chief", vol, ch, sec)
        memory = self.ctx.read_agent_memory("editor_in_chief")
        task = AgentTask(
            action="direct",
            input_text=(
                f"本节场景设计: {plot_design.content}\n"
                f"人物检查: {char_check.content[:300] if char_check.success else '无'}\n"
                f"世界观检查: {world_check.content[:300] if world_check.success else '无'}\n"
                "请给出本节的写作重点、情绪基调、节奏控制建议。"
            ),
        )
        direction = self.editor.execute(task, context=context, memory=memory)
        if direction.success:
            self.ctx.write_agent_memory("editor_in_chief", direction.notes)
            print(f"  写作指导: {direction.content[:300]}")

        # Step 5: 文风执行者写正文
        print(f"\n[5/6] 文风执行者生成正文...")
        context = self.context_builder.build(self.ctx, "style_executor", vol, ch, sec)
        memory = self.ctx.read_agent_memory("style_executor")
        task = AgentTask(
            action="write",
            input_text=(
                f"### 本节场景设计\n{plot_design.content}\n\n"
                f"### 写作指导\n{direction.content if direction.success else '按大纲自由发挥'}\n\n"
                f"### 前一节结尾 (请保持连贯)\n{prev_section[:800] if prev_section else '无'}\n\n"
                f"### 要求\n"
                f"1. 保持与前文一致的叙事风格和人物语气\n"
                f"2. 本节字数 3000-5000 字\n"
                f"3. 开头承接前节, 结尾留钩子\n"
                f"4. 包含完整场景 (环境描写+人物互动+冲突)"
            ),
        )
        result = self.style.execute(task, context=context, memory=memory)
        if not result.success:
            print(f"错误: 正文生成失败 - {result.error}")
            return

        self.ctx.save_section(vol, ch, sec, result.content)
        self.ctx.write_agent_memory("style_executor", result.notes)
        print(f"  正文: {len(result.content)} 字")

        # Step 6: 状态记录员更新剧情状态
        print(f"\n[6/6] 状态记录员更新剧情状态...")
        self._update_state(vol, ch, sec, result.content)

        self.ctx.mark_progress(vol, ch, sec)
        self._update_status("writing")
        print(f"\n第 {vol} 卷 第 {ch} 章 第 {sec} 节写作完成!")

    def write_chapter(self, vol: int, ch: int) -> None:
        """写整章: 循环写每节"""
        cfg = self.ctx.get_config()
        spc = cfg["sections_per_chapter"]
        for sec in range(1, spc + 1):
            self.write_section(vol, ch, sec)

    # ======== 状态更新 ========

    def _update_state(self, vol: int, ch: int, sec: int, section_content: str) -> None:
        """调用 StateManager 根据最新正文更新 state.md"""
        current_state = self.ctx.get_state()
        timeline = self.ctx.get_timeline()
        memory = self.ctx.read_agent_memory("state_manager")

        task = AgentTask(
            action="update",
            input_text=(
                f"当前进度: 第 {vol} 卷 第 {ch} 章 第 {sec} 节\n\n"
                f"## 最新正文内容\n{section_content[:3000]}\n\n"
                f"## 当前时间线\n{timeline[:500] if timeline else '无'}\n\n"
                f"## 当前状态文件\n{current_state if current_state else '无 (首次创建)'}\n\n"
                "请根据最新正文内容和时间推进, 更新完整的 state.md。"
                "注意更新: 角色状态、主线推进、伏笔变化 (新的/回收的)、"
                "支线推进 (含背景推演)、时间线变化。"
            ),
        )
        result = self.state.execute(task, memory=memory)
        if result.success:
            self.ctx.save_state(result.content)
            self.ctx.write_agent_memory("state_manager", result.notes)
            print(f"  状态已更新。")
            if result.notes:
                print(f"  观察笔记: {result.notes[:200]}")
        else:
            print(f"  状态更新失败: {result.error}")

    # ======== 碎片扫描 ========

    def _auto_scan_fragments(self) -> None:
        """检查碎片是否有变更，有则重新生成摘要"""
        fragments = self.ctx.list_fragments()
        if not fragments:
            return

        last_scan = self.ctx.get_fragment_scan_status()
        # 检查是否有文件在最后扫描之后被修改
        newest_mtime = max(f["modified"] for f in fragments)
        if newest_mtime <= last_scan:
            return  # 没有变更

        print(f"\n检测到 {len(fragments)} 个碎片, 正在生成参考摘要...")
        self._scan_fragments()

    def _scan_fragments(self, verbose: bool = True) -> None:
        """扫描所有碎片，调用 LLM 生成 fragments_summary.md"""
        fragments = self.ctx.list_fragments()
        if not fragments:
            self.ctx.save_fragments_summary("# 碎片参考摘要\n\n尚无碎片。")
            return

        # 收集碎片内容
        parts = []
        for f in fragments:
            content = self.ctx.get_fragment(f["id"])
            parts.append(f"## 碎片 {f['id']}: {f['title']}\n{content[:2000]}")

        all_fragments = "\n\n---\n\n".join(parts)

        # 调用 LLM 生成摘要 (使用轻量 prompt)
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
        result = self.style.execute(task)  # 复用 style executor 做摘要
        if result.success:
            summary = f"# 碎片参考摘要\n\n最后更新: 共 {len(fragments)} 个碎片\n\n{result.content}"
            self.ctx.save_fragments_summary(summary)
            self.ctx.set_fragment_scan_status(
                max(f["modified"] for f in fragments)
            )
            if verbose:
                print(f"摘要已更新 ({len(summary)} 字符)。")
        else:
            if verbose:
                print(f"摘要生成失败: {result.error}")

    # ======== 辅助 ========

    def _get_chapter_outline(self, vol: int, ch: int) -> str:
        # 优先使用已生成的 _meta.md
        meta = self.ctx.get_chapter_meta(vol, ch)
        if meta and "待生成" not in meta:
            return meta

        # 回退到卷大纲中查找
        vol_outline = self.ctx.get_volume_outline(vol)
        if not vol_outline:
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
        return "\n".join(chapter_lines) if chapter_lines else f"第 {ch} 章 (大纲未指定)"


    def _update_status(self, status: str) -> None:
        meta = self.ctx.get_meta()
        meta["status"] = status
        self.ctx.save_meta(meta)


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())
