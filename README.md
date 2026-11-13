# mlog-agentskill · Mindustry mlog 工具链

Mindustry mlog 逻辑的静态分析、规则审计、真执行器模拟，外加两个 DSH skill、一个 Agent 预设，以及一套关于 mlog 语义的知识库。

**本仓只含工具与知识库**：`tools/`、`rules/`、`tests/`、`docs/`（断言表 / 验证记录 / 速查卡 / 游戏速查）、
`mindustry-blueprint/`（技能文档）、`.dsh/skills/`（技能安装副本）、`dsh-preset-mlog/`（Agent 预设）、`data/game/`（从 v160.7 导出的游戏事实）。
个人语料、工作笔记、场景截图、两个游戏内模组、本地 sidecar（`tools/logicd.py`）、门禁脚本（`gate.py`）
以及 `tools/dev/` 下的一次性拓荒脚本都不在本仓；文档里保留的、指向这些内容的命令与路径是作者本地的执行记录。

## 快速开始

```bash
python tools/mlog.py doctor                    # 环境自检：入口、Java、server jar
python tools/mlog.py selftest                  # 工具自检（430 项蓝图往返）
python tools/mlog.py check logic.mlog          # 静态检查
python tools/mlog.py check logic.mlog --cost   # 死代码 / 最坏指令数
python tools/mlogagent.py report logic.mlog    # 五层分析一次跑完
python tests/run_tests.py                      # golden 用例（副本陈旧时直接拒绝运行）
python tests/docsig/run_docsig.py              # 文档里的语句签名与语义表逐项机检
python tests/ruleids/run_ruleids.py            # 每条规则必须在某个用例上真点火一次
python tests/shapes/run_shapes.py              # 检查器自身的语句形状不变量
python tests/probes/run_probes.py              # 运行期探针（真执行器，需要 JRE + server jar）
```

四套测试各有分工：`tests/run_tests.py` 是 golden 断言；`tests/docsig/` 防文档教错语法（槽位数、槽位序、
示例参数数、枚举槽名字——`ucontrol`/`draw`/`ulocate` 子命令、`status` 布尔第一槽、`sensor` 属性必须是 LAccess/Content）；
`tests/ruleids/` 断言没有死规则（只写反例、从不点火的规则在这里红）；`tests/shapes/` 在语句尾部追加惰性 token，
要求规则仍然开火——防整行锚定正则 fail-open。`tests/probes/` 用真 v160.7 执行器跑程序并比对数字
（例如「裸状态名在 v160.7 施加 1200 tick、`@wet` 是静默 no-op」）：静态检查说什么都不算数，运行的数字才算；
没有 JRE 或 server jar 时该步骤报 SKIP 而不是失败。

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
| `tools/` | 统一入口 `mlog.py`、模拟器 `mlogsim.py`、检查器/IR/值域、MCP 服务、签名、知识库构建（见 `tools/README.md`） |
| `mindustry-blueprint/` | 蓝图/逻辑技能文档（SKILL / REFERENCE / EMULATOR-CROSSCHECK）与参考数据 |
| `rules/` | 47 条规则（12 ERR / 12 WARN / 15 INFO / 8 SUPPRESSED），一条一个 JSON，供 `review.py` 逐条审计 |
| `tests/` | 75 个 golden 用例，`python tests/run_tests.py`；外加 `tests/docsig/`、`tests/ruleids/`、`tests/shapes/` 与运行期探针 `tests/probes/` |
| `docs/` | `断言表.md`（每条结论的出处与验证方式）、`验证记录.md`（逐条实测）、`速查卡.md`（速查）、`游戏速查/`（物品/方块/单位/配方） |
| `data/game/` | 从 v160.7 真执行器导出的游戏事实（物品/液体/方块/单位/别名），供 `game.py` 与知识库使用 |
| `.dsh/skills/` | `mlog-agentskill`（可独立拷走）与 `mindustry-blueprint` 安装副本 |
| `dsh-preset-mlog/` | DeepSeek Harness 的 `mlog` Agent 预设（persona + 技能根 + 工具集） |

## 规则与边界

- 规则可以降级（自动提议），升级必须人点头；`rules/README.md` 说明字段与审计流程。
- 静态检查会误报：约 2 条/块，当提示器用，不当判决书。
- 模拟器覆盖逻辑层、单位运动（B 档）、世界方块更新、天气与子弹命中；战斗 AI/波次/电力图/地形碰撞不模拟，真游戏行为必须由玩家验收。
- 跨处理器按变量名 `read`/`write` 需要 `.msch` 里的链接表；裸 `.mlog` 用 `--links auto` 按名字推断。
- 知识库是快照：改完文档/工具后跑 `python tools/kb.py build`（`kb.py` 会先告诉你索引是不是已经旧了）。

## 许可

MIT。技能文档中的校准数字来自作者本地语料，仅作量级参考。
