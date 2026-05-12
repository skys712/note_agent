# 小说创作系统 — 用户说明书

基于 Python + LLM 的 6 Agent 协作长篇创作系统，支持百万字规模。

## 系统架构

### 6 个专业 Agent

| Agent | 角色 | 职责 |
|-------|------|------|
| **总编** | EditorInChief | 审校质量、把控节奏和商业可读性 |
| **世界观管理员** | WorldBuilder | 构建设定、检测逻辑矛盾 |
| **人物导演** | CharacterDirector | 创建人物卡、确保角色行为一致性 |
| **剧情编剧** | PlotWriter | 设计大纲、场景序列、伏笔管理 |
| **文风执行者** | StyleExecutor | 按指定风格生成正文 |
| **状态记录员** | StateManager | 追踪剧情状态、伏笔、支线、时间线 |

### 创作阶段

```
立项 → 世界观 → 人物 → 大纲(三层) → 写作(逐节) → 审校
```

## 快速开始

```bash
# 1. 创建项目
python -m novel_writer.main init <项目名> --genre <类型> --logline <梗概> \
    --volumes 10 --chapters 15 --sections 3

# 2. 生成世界观（8个领域，含从创世到结局的时间线）
python -m novel_writer.main world --premise "<设定前提>"

# 3. 创建人物
python -m novel_writer.main char create <姓名> --role 主角 --faction <势力>
python -m novel_writer.main char create <姓名> --role 反派 --faction <势力>
python -m novel_writer.main char relation <ID_A> <ID_B> --type <关系>

# 4. 设计大纲（三层：梗概 → 卷弧线 → 逐章场景）
python -m novel_writer.main outline synopsis
python -m novel_writer.main outline volume 1 --direction "<本卷方向>"
python -m novel_writer.main outline chapters 1

# 5. 写作（逐节 6 步流水线）
python -m novel_writer.main write section 1 1 1
python -m novel_writer.main write chapter 1 1
```

## 完整命令参考

### 项目管理

```bash
init <名称> [--genre 类型] [--logline 梗概] [--volumes 10] [--chapters 15] [--sections 3]
use <名称>              # 切换当前项目
status                  # 查看项目状态
list                    # 列出所有项目
progress                # 写作进度（卷级进度条）
```

### 世界观

```bash
world --premise "<前提>"  # 逐领域生成完整世界观(8领域+审校)
```

生成文件：`world/` 目录下 8 个领域文件 + `index.md`

| 领域 | 文件 | 内容 |
|------|------|------|
| geography | 地理环境 | 大陆/地形/气候/重要地点 |
| magic_system | 力量体系 | 力量来源/分级/规则/代价 |
| politics | 政治格局 | 国家/势力/统治体制 |
| history | 历史背景 | 重大事件/战争/文明兴衰 |
| races | 种族 | 各物种特征/能力/文化 |
| culture | 文化风俗 | 宗教/节日/禁忌/艺术 |
| glossary | 术语表 | 专有名词/地名/概念 |
| timeline | 世界时间线 | 创世神话→远古→中古→近代→故事→终局 |

### 人物系统

```bash
# 创建人物（生成→世界观检查→总编审校→修订）
char create <姓名> --role 主角|反派|配角|导师 --faction <势力> --specs "<补充>"

# 管理
char list                                    # 人物索引
char show <protagonist_001>                 # 查看人物卡

# 关系与势力
char relation <ID_A> <ID_B> --type <类型>    # 创建人物关系
char faction <名称> --description <描述>     # 创建势力
```

### 大纲（三层结构）

```bash
outline synopsis                      # 全书梗概 (500-1000字)
outline volume <N> --direction "<>"   # 卷级弧线+章概要
outline chapters <N>                  # 逐章场景设计（含POV/地点/人物/世界观元素）
```

### 写作（6 步流水线）

每节写作自动执行完整的 6 Agent 协作流程：

```
[1/6] 剧情编剧       → 刷新场景设计
[2/6] 人物导演       → 检查角色行为一致性
[3/6] 世界观管理员   → 检查世界观矛盾
[4/6] 总编           → 给出写作方向指导
[5/6] 文风执行者     → 生成正文 (3000-5000字)
[6/6] 状态记录员     → 更新剧情状态 (角色/伏笔/支线/时间线)
```

```bash
write section <卷> <章> <节>    # 写单节（完整 6 步）
write chapter <卷> <章>         # 写整章（逐节循环）
```

写作前自动：
- 扫描 `fragments/` 目录是否有新增/变更的碎片，自动重新生成参考摘要
- 注入当前剧情状态（state.md）供所有 Agent 参考

### 碎片参考库

```bash
fragment add "<内容>" --type 风格参考|桥段设计|世界观修正|写作方向|人物细节
fragment list                             # 列出碎片
fragment show <ID>                        # 查看碎片
fragment scan                             # 手动生成摘要
```

### 状态查看

```bash
state                                     # 查看当前剧情状态
```

## 项目文件结构

```
projects/<项目名>/
├── _meta.md                    # 项目元信息
├── status.md                   # 写作进度追踪
├── state.md                    # 当前剧情状态（角色/伏笔/支线/时间线）
│
├── world/                      # 世界观（8 领域）
│   ├── index.md
│   ├── geography.md
│   ├── magic_system.md
│   ├── politics.md
│   ├── history.md
│   ├── races.md
│   ├── culture.md
│   ├── glossary.md
│   └── timeline.md             # 世界历史时间线
│
├── characters/                 # 人物系统
│   ├── index.md                # 人物索引表
│   ├── cards/                  # 单人单文件
│   ├── relationships.md        # 关系矩阵
│   └── factions/               # 势力
│
├── outline/                    # 三层大纲
│   ├── synopsis.md             # 全书梗概
│   └── volume_001.md           # 卷弧线
│
├── volumes/                    # 正文
│   └── volume_001/
│       ├── _meta.md            # 卷元信息
│       └── chapter_001/
│           ├── _meta.md        # 场景设计（POV/地点/人物/世界观元素）
│           ├── section_001.md  # 正文 (3000-5000字)
│           ├── section_002.md
│           └── section_003.md
│
├── fragments/                  # 碎片参考
├── fragments_summary.md        # 碎片摘要（自动生成）
├── timeline.md                 # 故事时间线
└── agents/                     # Agent 结构化记忆
```

## 配置

环境变量（已在 `.vscode/settings.json` 配置）：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_AUTH_TOKEN` | API 密钥 | - |
| `ANTHROPIC_BASE_URL` | API 地址 | `https://api.deepseek.com/anthropic` |
| `ANTHROPIC_MODEL` | 模型 | `deepseek-v4-pro` |
| `ANTHROPIC_MAX_TOKENS` | 最大 Token | `8192` |

## 关键设计原则

- **Metadata 驱动上下文注入**：不随机截断，由场景设计的元数据精确决定每个 Agent 看到什么
- **纯 Markdown 持久化**：零依赖，人类可直接编辑任何文件
- **逐卷生成大纲**：写完一卷再设计下一卷，保持灵活性
- **每节自动状态刷新**：状态记录员在每节完成后更新剧情状态，下节所有 Agent 自动获取

## 维护脚本

```bash
python setup_agents.py      # 重新生成所有 Agent 文件（修改 prompt 后运行）
```
