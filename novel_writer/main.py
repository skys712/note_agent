import argparse
import asyncio
import os
import sys
from pathlib import Path

# 修复 Windows 终端中文乱码
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from novel_writer.core.context import ProjectContext
from novel_writer.core.workflow import WorkflowOrchestrator

# 仓库根: novel_writer/main.py -> 上两级
_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


def _projects_root() -> Path:
    """项目集根目录。优先使用 NOVEL_WRITER_PROJECTS_DIR 环境变量，否则回退到仓库内 projects/。"""
    override = os.environ.get("NOVEL_WRITER_PROJECTS_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _WORKSPACE_ROOT / "projects"


def _current_project_file() -> Path:
    return _projects_root() / ".current"


def find_latest_project() -> Path | None:
    projects_dir = _projects_root()
    if not projects_dir.exists():
        return None
    dirs = sorted(
        [d for d in projects_dir.iterdir() if d.is_dir() and not d.name.startswith(".")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return dirs[0] if dirs else None


def get_project_path() -> Path:
    current_file = _current_project_file()
    if current_file.exists():
        name = current_file.read_text("utf-8").strip()
        path = _projects_root() / name
        if path.is_dir():
            return path
        print(f"当前项目 '{name}' 已不存在,清理 .current 并尝试切换到最近项目。", flush=True)
        try:
            current_file.unlink()
        except OSError:
            pass
    path = find_latest_project()
    if not path:
        print("没有项目, 请先用 init 命令创建。", flush=True)
        sys.exit(1)
    print(f"已自动切换到最近项目: {path.name}", flush=True)
    return path


# ======== 项目管理命令 ========

def cmd_init(args) -> None:
    project_dir = _projects_root() / args.name
    if project_dir.exists():
        print(f"项目 '{args.name}' 已存在。", flush=True)
        return

    ctx = ProjectContext(project_dir)
    ctx.init_project_structure({
        "name": args.name,
        "genre": args.genre,
        "logline": args.logline,
        "target_volumes": str(args.volumes),
        "target_chapters_per_volume": str(args.chapters),
        "target_sections_per_chapter": str(args.sections),
    })
    print(f"项目 '{args.name}' 创建完成。", flush=True)
    print(f"  规划: {args.volumes} 卷 x {args.chapters} 章 x {args.sections} 节", flush=True)
    print(f"  预估容量: 约 {args.volumes * args.chapters * args.sections * 3500:,} 字", flush=True)

    current_file = _current_project_file()
    current_file.parent.mkdir(parents=True, exist_ok=True)
    current_file.write_text(args.name, encoding="utf-8")


def cmd_use(args) -> None:
    path = _projects_root() / args.name
    if not path.is_dir():
        print(f"项目 '{args.name}' 不存在。", flush=True)
        sys.exit(1)
    current_file = _current_project_file()
    current_file.parent.mkdir(parents=True, exist_ok=True)
    current_file.write_text(args.name, encoding="utf-8")
    print(f"当前项目: {args.name}", flush=True)


def cmd_status(args) -> None:
    path = get_project_path()
    ctx = ProjectContext(path)
    meta = ctx.get_meta()
    status = ctx.get_status()
    vols = ctx.list_volumes()
    total = ctx.get_total_sections_written()

    print(f"项目: {meta.get('name', path.name)}", flush=True)
    print(f"类型: {meta.get('genre', '?')}", flush=True)
    print(f"梗概: {meta.get('logline', '?')}", flush=True)
    print(f"状态: {meta.get('status', '?')}", flush=True)
    print(f"规划: {meta.get('target_volumes', '?')} 卷 x "
          f"{meta.get('target_chapters_per_volume', '?')} 章 x "
          f"{meta.get('target_sections_per_chapter', '?')} 节", flush=True)
    print(f"已写: {len(vols)} 卷, {total} 节", flush=True)
    cv = status.get("current_vol", "1")
    cc = status.get("current_ch", "1")
    cs = status.get("current_sec", "1")
    print(f"下一节: 第 {cv} 卷 第 {cc} 章 第 {cs} 节", flush=True)


def cmd_list(args) -> None:
    projects_dir = _projects_root()
    if not projects_dir.exists():
        print("暂无项目。", flush=True)
        return
    dirs = sorted(
        [d for d in projects_dir.iterdir() if d.is_dir() and not d.name.startswith(".")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not dirs:
        print("暂无项目。", flush=True)
        return

    current = ""
    current_file = _current_project_file()
    if current_file.exists():
        current = current_file.read_text("utf-8").strip()

    for d in dirs:
        ctx = ProjectContext(d)
        meta = ctx.get_meta()
        total = ctx.get_total_sections_written()
        marker = " (*)" if d.name == current else ""
        print(f"  {d.name}{marker}", flush=True)
        print(f"    [{meta.get('genre', '?')}] "
              f"{meta.get('target_volumes', '?')}卷, "
              f"{total} 节已写", flush=True)


def cmd_progress(args) -> None:
    path = get_project_path()
    ctx = ProjectContext(path)
    cfg = ctx.get_config()
    total_target = cfg["volumes"] * cfg["chapters_per_volume"] * cfg["sections_per_chapter"]
    written = ctx.get_total_sections_written()
    pct = written * 100 / total_target if total_target > 0 else 0
    stale_count = ctx.count_stale_sections()

    print(f"写作进度: {written}/{total_target} 节 ({pct:.1f}%)", end="", flush=True)
    if stale_count > 0:
        print(f"  [WARN] {stale_count} 节已失效(stale)，需重新生成", flush=True)
    else:
        print(flush=True)
    print(flush=True)

    # 读取 state index 获取节级有效性
    state_idx = ctx._read_state_index()

    for vol_idx in range(1, cfg["volumes"] + 1):
        chs = ctx.list_chapters(vol_idx)
        vol_sections = 0
        vol_stale = 0
        for ch_num in chs:
            for sec_num in ctx.list_sections(vol_idx, ch_num):
                vol_sections += 1
                key = ctx._state_key(vol_idx, ch_num, sec_num)
                if state_idx.get(key, "valid") == "stale":
                    vol_stale += 1

        bar_len = 20
        target = cfg["chapters_per_volume"] * cfg["sections_per_chapter"]
        filled = int(bar_len * vol_sections / target) if target > 0 else 0
        bar = "#" * filled + "." * (bar_len - filled)
        marker = " <current>" if vol_idx == int(ctx.get_status().get("current_vol", "1")) else ""
        stale_info = f" [{vol_stale} stale]" if vol_stale > 0 else ""
        if vol_sections > 0 or vol_idx <= (ctx.list_volumes()[-1] if ctx.list_volumes() else 0) + 1:
            print(f"  第{vol_idx:02d}卷 [{bar}] {vol_sections}/{target} 节{stale_info}{marker}", flush=True)


def cmd_state(args) -> None:
    path = get_project_path()
    ctx = ProjectContext(path)
    sub = getattr(args, "state_command", None)

    if sub == "list":
        versions = ctx.list_state_versions()
        if not versions:
            print("暂无状态版本。写完第一节后自动生成。", flush=True)
            return
        stale_count = ctx.count_stale_sections()
        print(f"状态版本历史 ({len(versions)} 个版本", end="", flush=True)
        if stale_count > 0:
            print(f", {stale_count} 节 stale", end="", flush=True)
        print("):", flush=True)
        print(flush=True)
        print(f"  {'位置':<16s} {'状态':<8s} {'文件':<6s}", flush=True)
        print(f"  {'-' * 30}", flush=True)
        for v in versions:
            pos = f"第{v['vol']}卷第{v['ch']}章第{v['sec']}节"
            status = "[OK]" if v["status"] == "valid" else "[STALE]"
            file_mark = "yes" if v["has_file"] else "no"
            print(f"  {pos:<16s} {status:<8s} {file_mark:<6s}", flush=True)
    elif sub == "show":
        vol = getattr(args, "vol", 1)
        ch = getattr(args, "ch", 1)
        sec = getattr(args, "sec", 1)
        content = ctx.get_state_version(vol, ch, sec)
        if content:
            is_valid = ctx.is_section_valid(vol, ch, sec)
            validity = "[OK] 有效" if is_valid else "[STALE] 已失效"
            print(f"State: 第{vol}卷第{ch}章第{sec}节 ({validity})", flush=True)
            print(flush=True)
            print(content, flush=True)
        else:
            print(f"第{vol}卷第{ch}章第{sec}节的状态版本不存在。", flush=True)
    else:
        # 默认: 显示当前全局 state.md
        state = ctx.get_state()
        if state and "尚未开始" not in state:
            print(state, flush=True)
        else:
            print("状态尚未建立。写完第一节后自动生成。", flush=True)
        print(flush=True)
        print("子命令: state list (查看版本历史) | state show <卷> <章> <节>", flush=True)


# ======== 碎片管理 ========


async def cmd_world_generate(args) -> None:
    path = get_project_path()
    orch = WorkflowOrchestrator(path, debug=args.debug)
    premise = getattr(args, "premise", "")
    allow_invent = getattr(args, "allow_invent", False)
    config_file = getattr(args, "config", "")
    if config_file:
        import json
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        premise = cfg.get("premise", premise)
        allow_invent = cfg.get("allow_invent", allow_invent)
    await orch.generate_world(premise=premise, allow_invent=allow_invent)


async def cmd_world_interactive(args) -> None:
    path = get_project_path()
    from novel_writer.core.llm import LLMClient
    from novel_writer.core.logging import ExecutionLogger
    from novel_writer.core.world_building_loop import WorldBuildingLoop

    ctx = ProjectContext(path)
    loop = WorldBuildingLoop(ctx, LLMClient(), ExecutionLogger(debug=args.debug))
    await loop.run(premise=getattr(args, "premise", ""))


async def cmd_world(args) -> None:
    sub = getattr(args, "world_command", None)
    if sub == "interactive":
        await cmd_world_interactive(args)
    else:
        # 默认为 generate（向后兼容）
        await cmd_world_generate(args)


async def cmd_write(args) -> None:
    path = get_project_path()
    orch = WorkflowOrchestrator(path, debug=args.debug)
    sub = args.write_command
    force = getattr(args, "force", False)
    auto = getattr(args, "auto", False)

    if sub == "section":
        await orch.write_section(args.vol, args.ch, args.sec, force=force, auto_mode=auto)
    elif sub == "chapter":
        await orch.write_chapter(args.vol, args.ch, force=force, auto_mode=auto)
    else:
        print("用法: write <section|chapter> ...", flush=True)


async def cmd_outline(args) -> None:
    path = get_project_path()
    orch = WorkflowOrchestrator(path, debug=args.debug)
    sub = args.outline_command

    if sub == "synopsis":
        await orch.generate_synopsis()
    elif sub == "volume":
        await orch.generate_volume_outline(
            vol=args.volume,
            direction=getattr(args, "direction", ""),
        )
    elif sub == "chapters":
        await orch.generate_volume_chapters(args.volume)
    else:
        print("用法: outline <synopsis|volume|chapters> ...", flush=True)


async def cmd_char(args) -> None:
    path = get_project_path()
    orch = WorkflowOrchestrator(path, debug=args.debug)
    sub = args.char_command

    if sub == "create":
        await orch.create_character(
            name=args.name,
            role=getattr(args, "role", "配角"),
            faction=getattr(args, "faction", "无"),
            specs=getattr(args, "specs", ""),
        )
    elif sub == "list":
        idx = orch.ctx.get_character_index()
        if not idx:
            print("暂无人物。", flush=True)
            return
        for e in idx:
            print(f"  [{e['id']}] {e['name']}  ({e['role']}, {e['faction']})  [{e['status']}]", flush=True)
    elif sub == "show":
        content = orch.ctx.get_character(args.id)
        if content:
            print(content, flush=True)
        else:
            print(f"人物 {args.id} 不存在。", flush=True)
    elif sub == "relation":
        await orch.create_relationship(args.char_a, args.char_b, args.type)
    elif sub == "faction":
        await orch.create_faction(args.name, getattr(args, "description", ""))
    elif sub == "batch":
        import json
        file_path = args.file or str(path / "input_config" / "chars.json")
        if not Path(file_path).exists():
            print(f"文件不存在: {file_path}", flush=True)
            print("提示: 使用 --file 指定路径，或确保项目的 input_config/chars.json 已配置。", flush=True)
            return
        with open(file_path, "r", encoding="utf-8") as f:
            chars = json.load(f)
        await orch.create_characters_batch(chars)
    elif sub == "refresh":
        await orch.refresh_character(
            char_id=args.id,
            specs=getattr(args, "specs", ""),
        )
    else:
        print("用法: char <create|list|show|relation|faction|batch|refresh> ...", flush=True)


def cmd_reset(args) -> None:
    path = get_project_path()
    ctx = ProjectContext(path)

    to_pos = getattr(args, "to", None)
    if to_pos:
        vol = to_pos[0]
        ch = to_pos[1] if len(to_pos) > 1 else 0
        sec = to_pos[2] if len(to_pos) > 2 else 0
        if ch == 0:
            target_desc = f"第{vol}卷末尾"
        else:
            target_desc = f"第{vol}卷第{ch}章" + (f"第{sec}节" if sec else "")
        print(f"将重置到 {target_desc} 之后，删除该位置之后的所有内容。", flush=True)
        print("确认? (y/n): ", end="", flush=True)
        choice = input().strip().lower()
        if choice not in ("y", "yes", "是"):
            print("已取消。", flush=True)
            return

        stats = ctx.reset_to(vol, ch, sec)
        nv, nc, ns = stats["next_position"]
        print("重置完成。", flush=True)
        print(f"  删除: {stats['deleted_volumes']} 卷, {stats['deleted_chapters']} 章, {stats['deleted_sections']} 节", flush=True)
        print(f"  下一写作位置: 第 {nv} 卷 第 {nc} 章 第 {ns} 节", flush=True)
    else:
        stats = ctx.get_total_sections_written()
        vols_count = len(ctx.list_volumes())
        print("将完全重置写作进度：", flush=True)
        print(f"  已写: {vols_count} 卷, {stats} 节", flush=True)
        print("  将删除所有已写章节、剧情状态、故事时间线、Agent 记忆。", flush=True)
        print("  保留：世界观、人物卡、大纲、碎片。", flush=True)
        print(f"确认? 输入项目名 '{ctx.project_name}' 以确认: ", end="", flush=True)
        choice = input().strip()
        if choice != ctx.project_name:
            print("已取消。", flush=True)
            return

        stats = ctx.reset_full()
        print("重置完成。", flush=True)
        print(f"  删除: {stats['deleted_volumes']} 卷, {stats['deleted_sections']} 节", flush=True)
        print("  下一写作位置: 第 1 卷 第 1 章 第 1 节", flush=True)


async def cmd_publish(args) -> None:
    path = get_project_path()
    from novel_writer.core.publisher import Publisher
    publisher = Publisher(path)
    output = await publisher.publish(
        output=args.output or None,
        skip_check=args.no_check,
        max_workers=args.workers,
    )
    if output:
        print("\n发布完成。", flush=True)


async def cmd_fragment(args) -> None:
    path = get_project_path()
    ctx = ProjectContext(path)
    sub = args.fragment_command

    if sub == "add":
        fragment_id = ctx.next_fragment_id()
        text = args.text
        frag_type = getattr(args, "type", "未分类")
        title = text[:30].replace("\n", " ")
        content = f"# {fragment_id}: {title}\n\n类型: {frag_type}\n\n{text}"
        ctx.save_fragment(fragment_id, content)
        print(f"碎片 {fragment_id} 已创建。", flush=True)

    elif sub == "list":
        fragments = ctx.list_fragments()
        if not fragments:
            print("暂无碎片。", flush=True)
            return
        for f in fragments:
            print(f"  [{f['id']}] {f['title'][:50]}  ({f['size']} 字)", flush=True)

    elif sub == "show":
        fragment_id = args.id
        content = ctx.get_fragment(fragment_id)
        if content:
            print(content, flush=True)
        else:
            print(f"碎片 {fragment_id} 不存在。", flush=True)

    elif sub == "scan":
        orch = WorkflowOrchestrator(path, debug=args.debug)
        await orch._scan_fragments(verbose=True)

    else:
        print("用法: fragment <add|list|show|scan> ...", flush=True)


# ======== CLI ========

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novel-writer",
        description="AI 多 Agent 协作长篇创作系统 (百万字级)",
    )
    parser.add_argument("--debug", action="store_true", default=False,
                       help="输出详细调试信息")
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # 项目管理
    p_init = sub.add_parser("init", help="创建新项目")
    p_init.add_argument("name", help="项目名称")
    p_init.add_argument("--genre", default="未分类", help="小说类型")
    p_init.add_argument("--logline", default="", help="一句话梗概")
    p_init.add_argument("--volumes", type=int, default=10, help="目标卷数")
    p_init.add_argument("--chapters", type=int, default=15, help="每卷章数")
    p_init.add_argument("--sections", type=int, default=3, help="每章节数")

    p_use = sub.add_parser("use", help="切换当前项目")
    p_use.add_argument("name", help="项目名称")

    sub.add_parser("status", help="查看项目状态")
    sub.add_parser("list", help="列出所有项目")
    sub.add_parser("progress", help="查看写作进度")
    # state (支持子命令)
    p_state = sub.add_parser("state", help="剧情状态管理")
    p_state_sub = p_state.add_subparsers(dest="state_command")
    p_state_sub.add_parser("list", help="查看状态版本历史")
    p_state_show = p_state_sub.add_parser("show", help="查看指定节的状态版本")
    p_state_show.add_argument("vol", type=int, help="卷号")
    p_state_show.add_argument("ch", type=int, help="章号")
    p_state_show.add_argument("sec", type=int, help="节号")

    # reset
    p_reset = sub.add_parser("reset", help="重置写作进度")
    p_reset.add_argument("--to", nargs="+", type=int, metavar="POS",
                         help="重置到指定位置之后: <卷> <章> [节]")

    # fragment
    p_frag = sub.add_parser("fragment", help="碎片管理")
    p_frag_sub = p_frag.add_subparsers(dest="fragment_command")
    p_frag_add = p_frag_sub.add_parser("add", help="添加碎片")
    p_frag_add.add_argument("text", help="碎片内容")
    p_frag_add.add_argument("--type", default="未分类", help="碎片类型")
    p_frag_sub.add_parser("list", help="列出碎片")
    p_frag_show = p_frag_sub.add_parser("show", help="查看碎片")
    p_frag_show.add_argument("id", help="碎片ID")
    p_frag_sub.add_parser("scan", help="扫描生成摘要")

    # 世界观
    # 世界观
    p_world = sub.add_parser("world", help="世界观设定管理")
    p_world_sub = p_world.add_subparsers(dest="world_command")

    # generate — 保留原有 LLM 自动生成
    p_world_gen = p_world_sub.add_parser("generate", help="LLM 自动生成（原有功能）")
    p_world_gen.add_argument("--premise", default="", help="核心设定前提")
    p_world_gen.add_argument("--config", default="", help="JSON 配置文件路径（含 premise/allow_invent）")
    p_world_gen.add_argument("--allow-invent", action="store_true", default=False,
                             help="允许 LLM 在碎片之外杜撰新的世界观元素（默认禁止）")

    # interactive — 新的交互式问答构建
    p_world_int = p_world_sub.add_parser("interactive", help="交互式问答构建（推荐）")
    p_world_int.add_argument("--premise", default="", help="初始设定前提")

    # 人物
    p_char = sub.add_parser("char", help="人物管理")
    p_char_sub = p_char.add_subparsers(dest="char_command")
    p_char_create = p_char_sub.add_parser("create", help="创建人物")
    p_char_create.add_argument("name", help="人物姓名")
    p_char_create.add_argument("--role", default="配角", help="角色定位")
    p_char_create.add_argument("--faction", default="无", help="所属势力")
    p_char_create.add_argument("--specs", default="", help="补充要求")
    p_char_sub.add_parser("list", help="列出人物")
    p_char_show = p_char_sub.add_parser("show", help="查看人物")
    p_char_show.add_argument("id", help="人物ID")
    p_char_rel = p_char_sub.add_parser("relation", help="创建人物关系")
    p_char_rel.add_argument("char_a", help="人物A的ID")
    p_char_rel.add_argument("char_b", help="人物B的ID")
    p_char_rel.add_argument("--type", default="关联", help="关系类型")
    p_char_fac = p_char_sub.add_parser("faction", help="创建势力")
    p_char_fac.add_argument("name", help="势力名称")
    p_char_fac.add_argument("--description", default="", help="补充描述")
    p_char_batch = p_char_sub.add_parser("batch", help="批量并行创建人物")
    p_char_batch.add_argument("--file", default="",
                              help="JSON 文件路径 (默认: 项目 input_config/chars.json)，每项含 name/role/faction/specs")
    p_char_refresh = p_char_sub.add_parser("refresh", help="刷新人物卡（基于最新上下文重新生成）")
    p_char_refresh.add_argument("id", help="人物ID")
    p_char_refresh.add_argument("--specs", default="", help="补充要求或修改方向")

    # 大纲
    p_ol = sub.add_parser("outline", help="大纲设计")
    p_ol_sub = p_ol.add_subparsers(dest="outline_command")
    p_ol_sub.add_parser("synopsis", help="生成全书梗概")
    p_ol_vol = p_ol_sub.add_parser("volume", help="生成卷大纲")
    p_ol_vol.add_argument("volume", type=int, help="卷号")
    p_ol_vol.add_argument("--direction", default="", help="本卷方向")
    p_ol_ch = p_ol_sub.add_parser("chapters", help="生成逐章场景设计")
    p_ol_ch.add_argument("volume", type=int, help="卷号")

    # 写作
    p_write = sub.add_parser("write", help="写作")
    p_write_sub = p_write.add_subparsers(dest="write_command")
    p_ws = p_write_sub.add_parser("section", help="写指定节")
    p_ws.add_argument("vol", type=int, help="卷号")
    p_ws.add_argument("ch", type=int, help="章号")
    p_ws.add_argument("sec", type=int, help="节号")
    p_ws.add_argument("--force", action="store_true", default=False,
                      help="强制重写已有节（后续节将失效）")
    p_ws.add_argument("--auto", action="store_true", default=False,
                      help="全自动模式，跳过所有人类确认提示")
    p_wc = p_write_sub.add_parser("chapter", help="写整章(逐节)")
    p_wc.add_argument("vol", type=int, help="卷号")
    p_wc.add_argument("ch", type=int, help="章号")
    p_wc.add_argument("--force", action="store_true", default=False,
                      help="强制重写已有节（后续节将失效）")
    p_wc.add_argument("--auto", action="store_true", default=False,
                      help="全自动模式，跳过所有人类确认提示")

    # 发布
    p_publish = sub.add_parser("publish", help="发布：审校全文并打包为单文档")
    p_publish.add_argument("--output", "-o", default="",
                           help="输出路径（默认: publish/<项目名>_完整稿.md）")
    p_publish.add_argument("--no-check", action="store_true", default=False,
                           help="跳过 LLM 语法检查（仅打包）")
    p_publish.add_argument("--workers", type=int, default=4,
                           help="并行处理线程数（默认: 4）")

    return parser


async def main_async():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # 同步命令（不需要 async）
    sync_commands = {
        "init": cmd_init,
        "use": cmd_use,
        "status": cmd_status,
        "list": cmd_list,
        "progress": cmd_progress,
        "state": cmd_state,
        "reset": cmd_reset,
    }

    if args.command in sync_commands:
        sync_commands[args.command](args)
        return

    # 异步命令
    if args.command == "world":
        await cmd_world(args)
    elif args.command == "char":
        await cmd_char(args)
    elif args.command == "outline":
        await cmd_outline(args)
    elif args.command == "write":
        await cmd_write(args)
    elif args.command == "publish":
        await cmd_publish(args)
    elif args.command == "fragment":
        await cmd_fragment(args)
    else:
        parser.print_help()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
