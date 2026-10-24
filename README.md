# AtomicStates · Mindustry mlog 工具链

Mindustry mlog 逻辑的静态分析、规则审计、真执行器模拟，外加两个 DSH skill、一个 Agent 预设和一个本地知识库。

这是**完整工作区**：除工具/规则/测试/技能外，还包含个人语料、工作笔记、场景截图与 `Logic/` 下的示例程序。
公开的精简版在 https://github.com/EnernalIliary/mlog-agentskill （只含工具、规则、测试、技能文档）。

## 快速开始

```bash
python tools/mlog.py doctor                    # 环境自检：入口、Java、server jar
python tools/mlog.py selftest                  # 工具自检（430 项蓝图往返）
python tools/mlog.py check logic.mlog          # 静态检查
python tools/mlog.py check logic.mlog --cost   # 死代码 / 最坏指令数
python tools/mlogagent.py report logic.mlog    # 五层分析一次跑完
```

模拟器（真 v160.7 执行器，需要 Java 21 + server jar）：

```bash
export MLOGSIM_JAR=/path/to/server-release.jar
export MLOGSIM_JAVA=/path/to/java
python tools/mlogsim.py logic.mlog --steps 200
python tools/mlogsim.py logic.mlog --ticks 300 --trace trace.tsv --assert-last "chp < 1000"
python tools/mlogsim.py logic.mlog --save scene.msav --units mono:1 --core-items silicon:400
```

## 目录

| 路径 | 内容 |
|---|---|
| `tools/` | 统一入口 `mlog.py`、模拟器 `mlogsim.py`、检查器/IR/值域、MCP 服务、签名、知识库 |
| `mindustry-blueprint/` | 蓝图/逻辑技能文档（SKILL / REFERENCE / EMULATOR-CROSSCHECK）与参考数据 |
| `rules/` | 28 条规则，一条一个 JSON，供 `review.py` 逐条审计 |
| `tests/` | 36 个 golden 用例，`python tests/run_tests.py` |
| `docs/` | 本地知识库说明、`断言表.md`、`验证记录.md`、`游戏速查/`（物品/方块/单位/配方） |
| `data/game/` | 从 v160.7 真执行器导出的游戏事实（物品/液体/方块/单位/别名），供 `game.py` 与知识库使用 |
| `Logic/` | `逻辑代码规范.md` 与示例逻辑（个人程序） |
| `out/scenes/` | 5 张现实场景 `.msav`、3 个合成台（`benches/`：core / memory / processor）、快照 |
| `.dsh/skills/` | `mlog-agentskill`（可独立拷走）与 `mindustry-blueprint` 安装副本 |
| `dsh-preset-mlog/` | DeepSeek Harness 的 `mlog` Agent 预设（persona + 技能根 + 工具集） |

## 规则与边界

- 规则可以降级（自动提议），升级必须人点头；`rules/README.md` 说明字段与审计流程。
- 静态检查会误报：约 2 条/块，当提示器用，不当判决书。
- 模拟器覆盖逻辑层、单位运动（B 档）、世界方块更新、天气与子弹命中；战斗 AI/波次/电力图/地形碰撞不模拟，真游戏行为必须由玩家验收。
- 跨处理器按变量名 `read`/`write` 需要 `.msch` 里的链接表；裸 `.mlog` 用 `--links auto` 按名字推断。
- 知识库是快照：改完文档/工具后跑 `python tools/kb.py build`。

## 许可

MIT。技能文档中的校准数字来自作者本地语料，仅作量级参考。
