# mlog-agentskill

Mindustry mlog 逻辑的静态分析、规则审计与真执行器模拟工具链，外加两个 DSH skill 与一个 Agent 预设。

公开版只包含工具、规则、测试和技能文档；**个人语料、工作笔记、存档/蓝图扫描脚本、个人程序不在这个仓库里**。

## 快速开始

```bash
python tools/mlog.py selftest                 # 工具自检（430 项蓝图往返）
python tools/mlog.py check logic.mlog         # 静态检查
python tools/mlog.py check logic.mlog --cost  # 死代码 / 最坏指令数
python tools/mlogagent.py report logic.mlog   # 五层分析一次跑完
```

模拟器（真 v160.7 执行器，需要 Java 21 + server jar）：

```bash
export MLOGSIM_JAR=/path/to/server-release.jar
export MLOGSIM_JAVA=/path/to/java
python tools/mlogsim.py logic.mlog --steps 200
python tools/mlogsim.py logic.mlog --ticks 300 --trace trace.tsv --assert-last "chp < 1000"
```

## 目录

| 路径 | 内容 |
|---|---|
| `tools/` | 统一入口 `mlog.py`、模拟器 `mlogsim.py`、检查器、IR、值域、打包、规则审计、签名 |
| `mindustry-blueprint/` | 蓝图/逻辑技能文档（SKILL / REFERENCE / BUILDS）与参考数据 |
| `rules/` | 25+ 条规则，一条一个 JSON，供 `review.py` 逐条审计 |
| `tests/` | 30 个 golden 用例，`python tests/run_tests.py` |
| `.dsh/skills/mlog-agentskill/` | 可独立拷走的 mlog 分析技能（含一份 `tools/`） |
| `dsh-preset-mlog/` | DeepSeek Harness 的 `mlog` Agent 预设（persona + 技能根 + 工具集） |

## 规则与边界

- 规则可以降级（自动提议），升级必须人点头；`rules/README.md` 说明字段与审计流程。
- 静态检查会误报：约 2 条/块，当提示器用，不当判决书。
- 模拟器覆盖逻辑层、单位运动（B 档）、世界方块更新与天气；战斗/波次/电力图/地形碰撞不模拟，真游戏行为必须由玩家验收。
- 跨处理器按变量名 `read`/`write` 需要 `.msch` 里的链接表；裸 `.mlog` 只能靠名字推断。

## 许可

MIT。技能文档中的校准数字来自作者本地语料，仅作量级参考。
