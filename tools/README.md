# tools/ 索引

日常只有两个入口：`mlog.py`（解析/检查/生成蓝图与逻辑）和 `mlogsim.py`（拿真执行器跑逻辑：默认官方 **v160.7** server jar `out/_server160.jar`；`MLOGSIM_JAR` 可切 `_server159.jar` / `_server146.jar`，见 `mlogsim.py:116-122`。注意数据表的 `source:` 仍写 v159.3 —— 那是数据表来源版本，不是模拟器版本）。
其余文件是它们的数据、分析层和一次性维护脚本。

## 常用命令

| 想做什么 | 命令 |
|---|---|
| 看蓝图里的逻辑 | `python tools/mlog.py parse 图.msch` |
| 静态检查 | `python tools/mlog.py check x.mlog`（`--cost` 加成本/最坏指令数） |
| 生成只含处理器的蓝图 | `python tools/mlog.py gen --name 名字 --code x.mlog` |
| 模拟运行 | `python tools/mlogsim.py x.mlog --ticks 120 --trace t.csv` |
| 一次启动跑多个文件 | `python tools/mlogsim.py a.mlog b.mlog c.mlog --ticks 60` |
| 预热模拟器（预处理时先起） | `python tools/mlogsim.py --daemon` → `python tools/mlogsim.py --remote x.mlog --ticks 60` |
| 值域 / 跳转表 | `python tools/mlog.py ranges x.mlog --var n`；`python tools/mlog.py jumps x.mlog --var n` |
| 指令级执行流 | `python tools/mlogsim.py x.mlog --ticks 120 --itrace t.tsv --itrace-var n` |
| 把数字跳转换成标签，方便编辑 | `python tools/mlog.py labelize x.mlog`（输出 `x.labels.mlog`；签名文件会先把注释还原到正文） |
| 交付前把标签转回行号并签名 | `python tools/mlog.py post x.labels.mlog -o x.mlog`（`#` 注释打包进签名 token） |
| 看/取回签名里的注释 | `python tools/aigenerated.py extract x.mlog` / `restore x.mlog`（按原始行号与语句锚点） |
| 这个程序需要哪些世界符号 | `python tools/mlog_needs.py 图.msch` |
| 整批存档里的逻辑 | `python tools/mlog.py map <存档目录>` |
| 规则逐条审计 | `python tools/review.py md` |
| 本地知识库（向量+可选重排） | `python tools/kb.py search "read @this 怎么写" -k 6` |
| MCP 服务（模型直接调用工具） | `python tools/mlog_mcp.py`（stdio，见下节） |
| 自检工具链 | `python tools/mlog.py selftest`；`python tests/run_tests.py` |

`mlog.py --help` 是子命令总表；`tools/mlogsim.py --help` 是模拟器参数（世界、单位、战斗 tick、trace/assert）。

## 模拟器 JS 控制台 API（`mlogsim.Server`）

库方式驱动模拟器时，`srv.js(src)` 里的代码跑在游戏进程内（GraalJS），返回它 `print` 出来的行。手工摆方块/刷单位有三件套必须补，否则容易得到「单位没死 / ubind 绑不到」的假结论：

1. `Vars.state.rules.unitCap = 1000;` —— 空白世界没有核心，`Units.getCap()` 是 0，**每个单位在 `add()` 里就被移除**（这是历史「落地即死」的来源，跟 spawn 落点无关）。
2. `Vars.state.rules.logicUnitControl = true;` —— 处理器 `ubind` / `ucontrol` 控制单位的前提。
3. 刷完单位后 `Vars.state.teams.updateTeamStats();` —— 暂停的世界不会自己跑 team 统计，不调这一步 `ubind` 看到的是空。

读取式（GraalJS 里字段和方法不通用，写错会抛 `EcmaError: ... is not a function`）：

| 写法 | 说明 |
|---|---|
| `Groups.unit.size()` | 方法，不是属性 |
| `U.dead` / `U.health` / `U.x` / `U.y` / `U.valid` | 属性，不要加 `()` |
| `U.isValid()` | 方法 |
| `T.block()` / `T.floor()` | 方法 |
| `T.build` | 属性，可能为 null |

最小可复现示例（存成 `out/_assert_runs/tmp_probe.py`，能打印 SPAWN 行就说明环境通了）：

```python
import os, sys
sys.path.insert(0, "tools")
import mlogsim

srv = mlogsim.Server(os.path.abspath("out/jre21/jdk-21.0.5+11-jre/bin/java.exe"),
                     os.path.abspath("out/_server160.jar"), 64)
try:
    print(srv.js('''
        Vars.state.rules.unitCap = 1000;
        Vars.state.rules.logicUnitControl = true;
        var UT=null;
        for(var i=0;i<Vars.content.units().size;i++){var u=Vars.content.units().get(i); if(u.name=="dagger") UT=u;}
        var U=UT.spawn(Packages.mindustry.game.Team.sharded, 30*8+4, 30*8+4);
        Vars.state.teams.updateTeamStats();
        print("SPAWN\\t"+U.id+"\\tvalid="+U.isValid()+"\\tdead="+U.dead+"\\thp="+U.health);
    '''))
finally:
    srv.close()
```

输出 `['SPAWN\t210\tvalid=true\tdead=false\thp=150']`（`capacity` 调大后 spawn 才成立；不调 `unitCap` 时这一行会抛 `CountUnitException` 或单位数恒 0）。

- `srv.js(script)` 用 "undefined" 当结束哨兵（`tools/mlogsim.py:300-311`）：**脚本最后一条必须是语句**，不要以赋值/对象字面量这类「有返回值的表达式」结尾，否则控制台打印的是返回值（例如 `true`），`js()` 会一直等到超时。要调试输出就在末尾 `print(...)`，或写成 `var x = ...;`。
- `Server(java, jar, ...)` 的 java/jar 建议传绝对路径：Java 子进程的 cwd 是 `out/_sim/run-*`，相对路径会按**调用方** cwd 解析（本版本已内置 `_abs_path`，见 `tools/mlogsim.py`）。
- 坑：`sensor dead @unit @dead` 在 `@unit` 为 null 时读到 **1**（见 `docs/验证记录.md` L2-02），拿 `dead=1` 判「单位死了」不可靠，先判 `@unit` 非 null。
- 自写 JS 驱动推进逻辑必须照 `mlogsim.py:854-869`（`itr_exec`）的写法：先 `obj.accumulator += obj.block.instructionsPerTick`，再 `while(obj.accumulator >= 1){ obj.executor.runOnce(); obj.accumulator -= 1; }`。**只调 `b.updateTile()` 不会推进指令流**（它只重建方块、把 team 拷进去），ipt 也不进累加器 —— 症状是「逻辑一条都没跑」的中断器计数始终为 0。
- `LINK_ALIASES`（`mlogsim.py:980-995`）只有 cell / bank / message / switch / sorter / unloader / dome / projector / mender / router / junction / spectre / furnace / pad，**没有 `vault` / 容器别名**：要读容器库存（`sensor n vault1 @copper`）只能自己写 JS 摆方块再 `config`，别指望 `--links auto` 猜出 vault1。

## MCP 服务（`mlog_mcp.py`）

把检查器和模拟器直接暴露成工具，模型不用记路径、不用拼 PowerShell：

```bash
python tools/mlog_mcp.py          # stdio JSON-RPC，供 DSH / Claude Desktop 连接
```

工具：`mlog_doctor`、`mlog_check{path,cost}`、`mlog_ir{path}`、`mlog_values{path}`、
`mlog_gen{source|logic,name,links,blocks,out}`、`mlog_sim{path|logic,ticks,units,save,...}`。
模拟器在服务进程内保温，首次约 3.7 s，之后约 0.6 s。DSH 侧配置片段：

```yaml
- insert:
    - id: mcp-mlog
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: mlog
        transport: stdio
        command: '<python.exe>'
        args: ['<repo>/tools/mlog_mcp.py']
```

## 本地知识库（`kb.py`）

把仓库里的公开文档与工具源码切成块，存进 SQLite，检索走“向量召回 + FTS 召回 → RRF 融合”，加 `--rerank` 再走 cross-encoder。模型与索引都在本机，不进仓库。

```bash
# 首次：下载模型并建索引（约 1 分钟）
python tools/kb.py build
# 查询：默认向量+FTS+RRF（重排需显式 --rerank）
python tools/kb.py search "模拟器战斗 tick 怎么开" -k 6
python tools/kb.py search "ulocate" -k 4 --kind code --rerank
# MCP stdio 服务（给 DSH / Claude Desktop 之类用）
python tools/kb.py serve
```

- 依赖与模型：`fastembed` 装在 `out/_kblibs`，模型缓存在 `out/_kbmodels`（`BAAI/bge-small-zh-v1.5` + `BAAI/bge-reranker-base`）。首次运行前设置 `HF_ENDPOINT=https://hf-mirror.com`（国内镜像）。
- 索引：`out/_kb/kb.sqlite3`；`build` 可重复跑，重建整表。
- MCP 配置（以 DSH 的 mcp 配置为例）：

```json
{"mcpServers": {"mlog-kb": {
  "command": "python",
  "args": ["<repo>/tools/kb.py", "serve"],
  "env": {"HF_ENDPOINT": "https://hf-mirror.com"}
}}}
```

- 工具名 `kb_search(query, k=6, kind="")`；`kind` 取 `doc` 或 `code`。


## 文件分层

1. **入口**：`mlog.py`（统一下发子命令）、`mlogagent.py`（`report` / `info` 一条命令跑完五层）。
2. **分析层**：`mlogir.py`（解析/IR）、`mlogcheck.py`（静态检查）、`mlogval.py`（值域）、`mlogcross.py`（跨处理器）、`mlogpack.py`（打包配置）、`msch.py`/`mschgen.py`（蓝图容器）。
3. **模拟器**：`mlogsim.py`（真执行器驱动）、`mlog_needs.py`（扫程序需要的地图/方块/单位/全局量）。
4. **语料与存档**：`map_logic.py`（读存档）+ `parallel.py`（并行 worker）；语料挖掘、分桶、标注在 `corpus/`。
5. **规则**：`review.py`、`rule_seed.py`、`rule_capture.py`、`rule_audit.py`；规则数据在 `rules/`。
6. **数据表维护**：`*_from_source.py`、`build_cmd_index.py`、`block_sizes.py`——需要 `Mindustry-Source`，输出 JSON 已在仓库里，平时不用跑。
7. **语料流水线**（`corpus/`，低频，文档里有引用）：`analyze_logic.py`、`rank_logic.py`、`mine_idioms.py`、`check_ops.py`、`scan_all.py`、`extract_logic.py`、`label_*.py`、`sweep_*.py`、`pack_scan.py`、`typo_*.py`、`_sweep_saves.py`、`_sweep_analyse.py`、`_label_programs.py`、`_err_table.py` 等。脚本已按新位置改过路径，能直接跑。
8. **一次性脚本**：`dev/`——探针、patch、调试脚本，默认被忽略，不保证能跑，不要依赖。
9. **数据 JSON**（顶层，和代码同目录）：`block_attrs`(253)、`sensor_attrs`(75)、`unit_attrs`、`instr_semantics`、`cmd_index`(86)、`wiki_block_ids`(422)、`block_sizes`(446)、`item_ids`、`status_names`、`label_rules`。

## 不要手改的副本

一共四处，`tools/` 是唯一母本，其余全部由脚本从母本生成：

- `mindustry-blueprint/tools/`：超集（payload 20 个 + 本副本独有的 check_ops.py / map_site.py 等）。
- `.dsh/skills/mlog-agentskill/tools/`：可整目录拷走的独立技能包。
- `.dsh/skills/mindustry-blueprint/tools/`：**DSH 实际加载的安装副本**（改开发副本对 bot 不生效）。
- `$DSH_HOME/skills/mlog-agentskill/tools/`（通常 `~/.dsh/skills`）：用户级、跨项目可见，opt-in。

改顶层后：

    python tools/sync_mlogagent.py --mirror all   # 三处仓库内副本 + 各自 MANIFEST.sha256
    python tools/sync_mlogagent.py --mirror all --check   # 只比不写
    python tools/sync_mlogagent.py --global      # 第四处（仓库外），需全权限
    python tests/run_tests.py                     # 门禁：36 条 golden（行为层；副本一致性由上面的 --check 负责）

`--mirror` 只有 skill（默认）/ bp / install / all，**all 不含 global**；写完会对每个目标自动跑一次它自己的 `mlogagent.py info --verify`（要关掉加 `--no-verify`）。

## 维护约定

- 新写的一次性脚本先放 `tools/dev/`；成体系的语料分析放 `tools/corpus/`；稳定并有人引用后再提到顶层。
- 提到顶层的门槛：`tests/run_tests.py` 有 golden 用例，或文档里有命令引用。
- 顶层不放大文件、不放大图；截图/日志/导出物放 `out/`。