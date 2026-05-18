# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

基于 Python + Anthropic SDK 的 8 Agent 协作长篇小说创作系统（百万字规模）。本仓库无测试套件、无 lint 配置、无构建步骤——只有一个 CLI 入口和一组 Agent 模块。
该项目中所有的交互行为必须使用中文。

## 关键开发命令

```bash
# 修改 Agent system prompt 后必须重新生成 .py 文件
python setup_agents.py

# 运行 CLI（所有用户功能的唯一入口）
python -m novel_writer.main <command> ...

# 直接调试单个 Agent
python -c "from novel_writer.agents.world_builder import WorldBuilder; from novel_writer.core.llm import LLMClient; ..."
```

环境变量必须设置（已在 `.vscode/settings.json` 中配置 Windows 环境）：

| 变量 | 默认 |
|------|------|
| `ANTHROPIC_AUTH_TOKEN` | 必须 |
| `ANTHROPIC_BASE_URL` | `https://api.deepseek.com/anthropic` |
| `ANTHROPIC_MODEL` | `deepseek-v4-pro` |
| `ANTHROPIC_MAX_TOKENS` | `32768` |

LLM 客户端使用 Anthropic Python SDK，但 `base_url` 指向 DeepSeek 的 Anthropic 兼容端点。修改模型/服务商时只改环境变量，不改 `llm.py`。

## 架构核心

### 1. Agent 文件是生成产物，不要手动编辑

`novel_writer/agents/*.py`（除 `base.py`）是由 `setup_agents.py` 中的 `PROMPTS` 字典生成的。修改 Agent 的 system prompt：

1. 编辑 `setup_agents.py` 中对应 key 的 prompt 字符串
2. 运行 `python setup_agents.py` 重新生成

直接修改 `agents/<agent_id>.py` 会在下次运行 `setup_agents.py` 时被覆盖。

### 2. Agent 双 ``` 块响应协议（`base.py:_parse_response`）

每个 Agent 都被要求在响应中输出**两个** ``` 围栏块：
- 第一个块 → 正文内容（写入 `result.content`，最终落到对应的 `.md` 文件）
- 第二个块 → 记忆笔记（写入 `result.notes`，落到 `agents/<agent_id>.md`），格式形如 `[ACTIVE] ...` / `[CONTRADICTION] ...` / `[ARC] ...`

如果 LLM 漏掉一个块，`_parse_response` 会用 `_looks_like_notes` 启发式判断哪个是笔记、哪个是正文，避免把笔记误存为正文。修改 prompt 时必须保留"两个 ``` 块"的约定。

### 3. 写作流水线（`workflow.py:write_section`）

每节正文生成的核心流程。**正向**[1-7] 给指导（含检查→修订循环）→ 文风执行者写正文 → **逆向** 6 个 Agent 并行校验正文是否遵循指导（`_run_verification_checks`）→ **如有问题，触发文风执行者修订并二次验证** → 状态记录员更新 `state.md`（含验证反馈）。

正向指导阶段 Step 2（人物导演检查场景设计）和 Step 3（世界观管理员检查场景设计）发现问题会**立即触发场景设计修订**（剧情编剧重写场景设计），修订后的设计继续参与后续步骤。

逆向验证阶段发现问题会**触发正文修订**：汇总所有 Agent 的反馈意见，交由文风执行者针对性修订，修订后二次验证。最多 1 轮修订。遗留问题写入 `state.md` 供后续写作参考。

### 4. 分层上下文注入（`context_builder.py`）

`ContextBuilder.build(ctx, agent_id, vol, ch, sec)` 按 4 层拼接，Token 预算约 6000：

- **P1**（永远注入）：`state.md` + 碎片摘要 + 本章 `_meta.md` + 前一节结尾 + 故事时间线
- **P2**（卷级）：卷弧线 + 世界历史时间线 + 已写章节摘要
- **P3**（按 agent_id 选择性）：人物索引/世界领域索引/关系矩阵——见 `_build_p3` 中按 agent_id 分支
- **P4**：该 Agent 自己的记忆文件中 `[ACTIVE]` 标记的条目（最多 30 行）

新增 Agent 时需要在 `_build_p3` 添加分支决定它能看到哪些全局索引。

### 5. Markdown-only 持久化（`context.py` + `markdown_store.py`）

所有项目状态都是人类可读的 Markdown 文件，目录结构由 `ProjectContext.init_project_structure` 决定。没有数据库、没有 JSON 元数据——`_meta.md` / `status.md` 这类 KV 文件靠 `_parse_kv` / `_format_kv` 手工解析。

文件路径硬编码在 `ProjectContext` 的方法名里（`get_volume_outline(vol)` → `outline/volume_{vol:03d}.md`）。新增持久化对象时统一在 `ProjectContext` 加方法，不要绕过它直接读写文件。

### 6. WorldBuilder 的记忆合并（`workflow.py:_merge_agent_memory`）

`WorldBuilder` 是唯一逐领域调用的 Agent（8 个 world domain 顺序生成）。每个领域生成完会把笔记**合并**进 `agents/world_builder.md`，而不是覆盖——保留之前领域的 `[ACTIVE]` 规则。其他 Agent 用 `ctx.write_agent_memory` 直接覆盖。新增类似的逐对象生成流程时需要复用这套合并逻辑。

## 已知坑

- **Windows 终端中文乱码**：`main.py` 顶部检测 `sys.platform == "win32"` 并强制 UTF-8 stdout，跨平台改动时不要删。
- **`projects/` 与 `world copy/` 目录已在 `.gitignore` 中**：写测试或脚本不要把项目示例数据加进 git。
- **`NOVEL_WRITER_PROJECTS_DIR` 环境变量**可覆盖默认 `projects/` 位置，便于在多个工作区共享 CLI。

## ASCII-only 编码规则（Windows GBK 兼容）

**所有输出给终端或日志的字符必须是纯 ASCII。** Windows 中文环境默认 GBK 编码，任何 emoji 或非 ASCII Unicode 符号都会导致 `UnicodeEncodeError: 'gbk' codec can't encode character`。

### 已替换的符号

| 原符号 | 替换为 | 位置 |
|--------|--------|------|
| `✓` (U+2713) | `[OK]` | `logging.py:86` |
| `✗` (U+2717) | `[FAIL]` | `logging.py:86` |
| `⏭` (U+23ED) | `[SKIP]` | `logging.py:100` |
| `📥` (U+1F4E5) | `in:` | `logging.py:88` |
| `📤` (U+1F4E4) | `out:` | `logging.py:88` |
| `⏱` (U+23F1) | `time:` | `logging.py:91` |
| `📝` (U+1F4DD) | `chars:` | `logging.py:93` |

### 规则

- **`logging.py` 禁止使用任何 emoji 或非 ASCII 符号**，包括 status 标记和统计 detail 行。
- **绕过 `main.py` 直接运行 Python 代码时**（如 `python -c "..."` 或临时脚本），必须设置 `$env:PYTHONIOENCODING='utf-8'`，因为不会触发 `main.py` 的 UTF-8 stdout wrapper。
- **PowerShell here-string (`@"..."@`) 与 Python 字符串内的转义冲突**：不要在 PowerShell here-string 中嵌入 Python f-string 或包含 `\"` 的代码。改用临时 `.py` 文件。

## Agent 响应解析规范

`base.py:_parse_response` 负责从 LLM 响应中提取正文（第一个 ``` 块）和笔记（第二个 ``` 块）。关键常量：

- **`_NOTE_PREFIXES`**（`base.py:124-127`）：定义哪些行首标记属于笔记。当前包含 12 种前缀：`[ACTIVE]` `[CONTRADICTION]` `[待补充]` `[推断]` `[ARC]` `[STYLE]` `[VOICE]` `[CONSISTENCY]` `[FORESHADOWING]` `[RESOLVED]` `# 记忆更新` `[记忆更新]`。
- **新增 Agent 笔记标记时**，必须同步更新 `_NOTE_PREFIXES`，否则无 ``` 块的响应会被错误解析。
- **`_next_char_id`**（`workflow.py:631`）：使用最大 ID 号 +1 算法，不是计数法。删除角色条目后不会产生重复 ID。

## 用户 CLI 命令速查

完整工作流：`init → world → char → outline (synopsis/volume/chapters) → write`

```bash
# 项目
init <名称> --genre <类型> --logline <梗概> --volumes 10 --chapters 15 --sections 3
use <名称>            # 切换当前项目（写入 projects/.current）
status / list / progress / state

# 世界观（8 领域顺序生成）
world --premise "<前提>"

# 人物
char create <姓名> --role 主角|反派|配角|导师 --faction <势力> --specs "<>"
char list / show <id> / relation <a> <b> --type <类型> / faction <名称>

# 大纲（三层，逐卷生成不要一次性铺完）
outline synopsis
outline volume <N> --direction "<>"
outline chapters <N>

# 写作
write section <卷> <章> <节>   # 单节 14 步流水线
write chapter <卷> <章>        # 整章循环

# 碎片参考库（写作前自动 scan）
fragment add "<内容>" --type 风格参考|桥段设计|世界观修正|写作方向|人物细节
fragment list / show <id> / scan
```

## 项目目录约定

```
projects/<项目名>/
├── _meta.md / status.md / state.md          # KV 文件，由 _parse_kv 解析
├── world/                                    # 8 领域 + index.md + timeline.md
├── characters/                               # cards/<id>.md + index.md + factions/
├── outline/                                  # synopsis.md + volume_NNN.md
├── volumes/volume_NNN/chapter_NNN/           # _meta.md（场景设计）+ section_NNN.md
├── fragments/ + fragments_summary.md         # 碎片库 + LLM 生成的摘要
└── agents/<agent_id>.md                      # 每个 Agent 的记忆笔记
```

## 8 个 Agent 角色

| Agent | 类名 | 文件 | 主要职责 |
|-------|------|------|----------|
| 总编 | `EditorInChief` | `editor_in_chief.py` | 审校质量、写作方向指导 |
| 世界观管理员 | `WorldBuilder` | `world_builder.py` | 逐领域生成世界观、检测矛盾 |
| 人物导演 | `CharacterDirector` | `character_director.py` | 人物卡、关系、弧线追踪 |
| 剧情编剧 | `PlotWriter` | `plot_writer.py` | 三层大纲、场景设计、伏笔 |
| 情绪曲线管控 | `EmotionController` | `emotion_controller.py` | 情绪节奏、刀糖配比 |
| 断章决策者 | `ChapterBreakDirector` | `chapter_break_director.py` | 章末/节末/卷末悬念钩子 |
| 文风执行者 | `StyleExecutor` | `style_executor.py` | 按指导生成 3000-5000 字正文 |
| 状态记录员 | `StateManager` | `state_manager.py` | 每节后更新 `state.md` |
