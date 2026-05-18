import argparse
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


def _default_chars_json() -> Path:
    """批量人物 JSON 的默认查找路径(基于仓库根)"""
    return _WORKSPACE_ROOT / "input_config" / "chars.json"


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
        # .current 指向的项目目录已被删除/重命名,清理并提示
        print(f"当前项目 '{name}' 已不存在,清理 .current 并尝试切换到最近项目。")
        try:
            current_file.unlink()
        except OSError:
            pass
    path = find_latest_project()
    if not path:
        print("没有项目, 请先用 init 命令创建。")
        sys.exit(1)
    print(f"已自动切换到最近项目: {path.name}")
    return path


# ======== 项目管理命令 ========

def cmd_init(args) -> None:
    project_dir = _projects_root() / args.name
    if project_dir.exists():
        print(f"项目 '{args.name}' 已存在。")
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
    print(f"项目 '{args.name}' 创建完成。")
    print(f"  规划: {args.volumes} 卷 x {args.chapters} 章 x {args.sections} 节")
    print(f"  预估容量: 约 {args.volumes * args.chapters * args.sections * 3500:,} 字")

    # 设为当前项目
    current_file = _current_project_file()
    current_file.parent.mkdir(parents=True, exist_ok=True)
    current_file.write_text(args.name, encoding="utf-8")


def cmd_use(args) -> None:
    path = _projects_root() / args.name
    if not path.is_dir():
        print(f"项目 '{args.name}' 不存在。")
        sys.exit(1)
    current_file = _current_project_file()
    current_file.parent.mkdir(parents=True, exist_ok=True)
    current_file.write_text(args.name, encoding="utf-8")
    print(f"当前项目: {args.name}")


def cmd_status(args) -> None:
    path = get_project_path()
    ctx = ProjectContext(path)
    meta = ctx.get_meta()
    status = ctx.get_status()
    vols = ctx.list_volumes()
    total = ctx.get_total_sections_written()

    print(f"项目: {meta.get('name', path.name)}")
    print(f"类型: {meta.get('genre', '?')}")
    print(f"梗概: {meta.get('logline', '?')}")
    print(f"状态: {meta.get('status', '?')}")
    print(f"规划: {meta.get('target_volumes', '?')} 卷 x "
          f"{meta.get('target_chapters_per_volume', '?')} 章 x "
          f"{meta.get('target_sections_per_chapter', '?')} 节")
    print(f"已写: {len(vols)} 卷, {total} 节")
    cv = status.get("current_vol", "1")
    cc = status.get("current_ch", "1")
    cs = status.get("current_sec", "1")
    print(f"下一节: 第 {cv} 卷 第 {cc} 章 第 {cs} 节")


def cmd_list(args) -> None:
    projects_dir = _projects_root()
    if not projects_dir.exists():
        print("暂无项目。")
        return
    dirs = sorted(
        [d for d in projects_dir.iterdir() if d.is_dir() and not d.name.startswith(".")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not dirs:
        print("暂无项目。")
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
        print(f"  {d.name}{marker}")
        print(f"    [{meta.get('genre', '?')}] "
              f"{meta.get('target_volumes', '?')}卷, "
              f"{total} 节已写")


def cmd_progress(args) -> None:
    path = get_project_path()
    ctx = ProjectContext(path)
    cfg = ctx.get_config()
    total_target = cfg["volumes"] * cfg["chapters_per_volume"] * cfg["sections_per_chapter"]
    written = ctx.get_total_sections_written()
    pct = written * 100 / total_target if total_target > 0 else 0

    print(f"写作进度: {written}/{total_target} 节 ({pct:.1f}%)")
    print()
    for vol_idx in range(1, cfg["volumes"] + 1):
        chs = ctx.list_chapters(vol_idx)
        vol_sections = 0
        for ch_num in chs:
            vol_sections += len(ctx.list_sections(vol_idx, ch_num))
        bar_len = 20
        filled = int(bar_len * vol_sections / (cfg["chapters_per_volume"] * cfg["sections_per_chapter"]))
        bar = "#" * filled + "." * (bar_len - filled)
        marker = " <current>" if vol_idx == int(ctx.get_status().get("current_vol", "1")) else ""
        if vol_sections > 0 or vol_idx <= (ctx.list_volumes()[-1] if ctx.list_volumes() else 0) + 1:
            print(f"  第{vol_idx:02d}卷 [{bar}] {vol_sections}/{cfg['chapters_per_volume'] * cfg['sections_per_chapter']} 节{marker}")


def cmd_state(args) -> None:
    path = get_project_path()
    ctx = ProjectContext(path)
    state = ctx.get_state()
    if state and "尚未开始" not in state:
        print(state)
    else:
        print("状态尚未建立。写完第一节后自动生成。")


# ======== 碎片管理 ========


def cmd_world(args) -> None:
    path = get_project_path()
    orch = WorkflowOrchestrator(path)
    premise = getattr(args, "premise", "")
    allow_invent = getattr(args, "allow_invent", False)
    config_file = getattr(args, "config", "")
    if config_file:
        import json
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        premise = cfg.get("premise", premise)
        allow_invent = cfg.get("allow_invent", allow_invent)
    orch.generate_world(premise=premise, allow_invent=allow_invent)


def cmd_write(args) -> None:
    path = get_project_path()
    orch = WorkflowOrchestrator(path)
    sub = args.write_command

    if sub == "section":
        orch.write_section(args.vol, args.ch, args.sec)
    elif sub == "chapter":
        orch.write_chapter(args.vol, args.ch)
    else:
        print("用法: write <section|chapter> ...")


def cmd_outline(args) -> None:
    path = get_project_path()
    orch = WorkflowOrchestrator(path)
    sub = args.outline_command

    if sub == "synopsis":
        orch.generate_synopsis()
    elif sub == "volume":
        orch.generate_volume_outline(
            vol=args.volume,
            direction=getattr(args, "direction", ""),
        )
    elif sub == "chapters":
        orch.generate_volume_chapters(args.volume)
    else:
        print("用法: outline <synopsis|volume|chapters> ...")


def cmd_char(args) -> None:
    path = get_project_path()
    orch = WorkflowOrchestrator(path)
    sub = args.char_command

    if sub == "create":
        orch.create_character(
            name=args.name,
            role=getattr(args, "role", "配角"),
            faction=getattr(args, "faction", "无"),
            specs=getattr(args, "specs", ""),
        )
    elif sub == "list":
        idx = orch.ctx.get_character_index()
        if not idx:
            print("暂无人物。")
            return
        for e in idx:
            print(f"  [{e['id']}] {e['name']}  ({e['role']}, {e['faction']})  [{e['status']}]")
    elif sub == "show":
        content = orch.ctx.get_character(args.id)
        if content:
            print(content)
        else:
            print(f"人物 {args.id} 不存在。")
    elif sub == "relation":
        orch.create_relationship(args.char_a, args.char_b, args.type)
    elif sub == "faction":
        orch.create_faction(args.name, getattr(args, "description", ""))
    elif sub == "batch":
        import json
        with open(args.file, "r", encoding="utf-8") as f:
            chars = json.load(f)
        orch.create_characters_batch(chars)
    elif sub == "refresh":
        orch.refresh_character(
            char_id=args.id,
            specs=getattr(args, "specs", ""),
        )
    else:
        print("用法: char <create|list|show|relation|faction|batch|refresh> ...")


def cmd_fragment(args) -> None:
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
        print(f"碎片 {fragment_id} 已创建。")

    elif sub == "list":
        fragments = ctx.list_fragments()
        if not fragments:
            print("暂无碎片。")
            return
        for f in fragments:
            print(f"  [{f['id']}] {f['title'][:50]}  ({f['size']} 字)")

    elif sub == "show":
        fragment_id = args.id
        content = ctx.get_fragment(fragment_id)
        if content:
            print(content)
        else:
            print(f"碎片 {fragment_id} 不存在。")

    elif sub == "scan":
        from novel_writer.core.workflow import WorkflowOrchestrator
        orch = WorkflowOrchestrator(path)
        orch._scan_fragments(verbose=True)

    else:
        print("用法: fragment <add|list|show|scan> ...")


# ======== CLI ========

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novel-writer",
        description="AI 多 Agent 协作长篇创作系统 (百万字级)",
    )
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
    sub.add_parser("state", help="查看当前剧情状态")

    # fragment
    p_frag = sub.add_parser("fragment", help="碎片管理")
    p_frag_sub = p_frag.add_subparsers(dest="fragment_command")
    p_frag_add = p_frag_sub.add_parser("add", help="添加碎片")
    p_frag_add.add_argument("text", help="碎片内容")
    p_frag_add.add_argument("--type", default="未分类", help="碎片类型")
    p_frag_list = p_frag_sub.add_parser("list", help="列出碎片")
    p_frag_show = p_frag_sub.add_parser("show", help="查看碎片")
    p_frag_show.add_argument("id", help="碎片ID")
    p_frag_scan = p_frag_sub.add_parser("scan", help="扫描生成摘要")

    # 世界观
    p_world = sub.add_parser("world", help="生成世界观设定")
    p_world.add_argument("--premise", default="", help="核心设定前提（与 --config 互斥）")
    p_world.add_argument("--config", default="", help="JSON 配置文件路径（含 premise/allow_invent）")
    p_world.add_argument("--allow-invent", action="store_true", default=False,
                         help="允许 LLM 在碎片之外杜撰新的世界观元素（默认禁止）")

    # 人物
    p_char = sub.add_parser("char", help="人物管理")
    p_char_sub = p_char.add_subparsers(dest="char_command")
    p_char_create = p_char_sub.add_parser("create", help="创建人物")
    p_char_create.add_argument("name", help="人物姓名")
    p_char_create.add_argument("--role", default="配角", help="角色定位")
    p_char_create.add_argument("--faction", default="无", help="所属势力")
    p_char_create.add_argument("--specs", default="", help="补充要求")
    p_char_list = p_char_sub.add_parser("list", help="列出人物")
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
    p_char_batch.add_argument("--file", default=str(_default_chars_json()),
                              help=f"JSON 文件路径 (默认: {_default_chars_json()})，每项含 name/role/faction/specs")
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
    p_wc = p_write_sub.add_parser("chapter", help="写整章(逐节)")
    p_wc.add_argument("vol", type=int, help="卷号")
    p_wc.add_argument("ch", type=int, help="章号")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "init": cmd_init,
        "use": cmd_use,
        "status": cmd_status,
        "list": cmd_list,
        "progress": cmd_progress,
        "state": cmd_state,
        "fragment": cmd_fragment,
        "world": cmd_world,
        "char": cmd_char,
        "outline": cmd_outline,
        "write": cmd_write,
    }

    cmd = commands.get(args.command)
    if cmd:
        cmd(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
