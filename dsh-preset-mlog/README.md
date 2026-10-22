# dsh-preset-mlog

DSH Agent 预设：Mindustry mlog / 蓝图 / 存档专家。

预设 id 是 **`mlog`**，`order: 5`（在官方 `standard` 之后）。插件清单完整照抄官方
`preset-standard`（**32 个插件条目**，含 delegation / workflow / compaction / plan-mode
及其子插件；对齐 DSH **0.2.1-rc.2**），只替换了两处：

1. **persona**：mlog 专家人设与两条长期规则（写新逻辑前先问 3-5 个问题；交付前过
   `mindustry-blueprint` 的九条自检）。
2. **skill-filesystem**：加了 `customSkillDirs`，把 `<repo>/.dsh/skills` 设为技能根
   （rank 300）。这样无论用哪个工作目录开新会话，`mindustry-blueprint` 与
   `mlog-agentskill` 都能加载；在本仓库内开会话时 project root（rank 100）优先，
   同名技能不会重复注册。

另外把官方 `preset-standard` 里 plan-mode 的 `config.section` 原文补了进来（旧版漏写，
计划模式的系统提示词会退回插件默认值）。

## 安装 / 卸载

```powershell
# 安装（desktop profile）
dsh plugin --profile desktop add "link:<repo>\dsh-preset-mlog"

# 卸载
dsh plugin --profile desktop remove dsh-preset-mlog
```

装完要**重启 DSH**（Electron 启动时组装 profile 的 bundle patch），然后在新建会话的
预设列表里选 `mlog`。

安装做的事：在 profile 的 `package.json` 里加
`"dsh-preset-mlog": "link:<repo>/dsh-preset-mlog"`，并把
`dsh-preset-mlog` 追加进 `dsh.profile.bundles`；`cordis.patch.yml` 由
`dsh.bundle.patch` 声明，启动时作为 patch 覆盖到 profile 上。

## 文件

- `package.json`：`dsh.bundle.patch` 指向 `cordis.patch.yml`。
- `cordis.patch.yml`：一份 `- insert:` 补丁，插入一个
  `@deepseek-ai/dsh-agent-preset` 行（`id: preset-mlog`，`config.id: mlog`）。

## 维护

- 当前对齐：DSH **0.2.1-rc.2**（2026-10-20 核对，32 个插件条目）。
- 补丁是**整份快照**，不是深合并：DSH 升级后官方 `preset-standard` 的插件清单可能变，
  需要重新对齐（升级后先跑 `dsh --version` 对照）。官方定义可以从 asar 里导出
  （`%LOCALAPPDATA%\Programs\DeepSeek Harness\resources\app.asar`，
  搜 `id: preset-standard`），再和这里的 `cordis.patch.yml` 逐项比对。
- `dsh --profile desktop --dump-config` 不可用（desktop profile 由 Electron 独占管理），
  所以验证只能靠：YAML 能解析、插件 id 与官方一致、重启后预设列表里出现 `mlog`。
- 全局技能副本 `~/.dsh/skills/mlog-agentskill` 可能过期（它指向
  `.dsh-pack/skills/default`，当前没有写权限）；本预设通过 `customSkillDirs` 用仓库内
  的 `.dsh/skills`，不依赖那份全局副本。
