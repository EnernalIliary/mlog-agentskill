# tools/ 索引

日常只有两个入口：`mlog.py`（解析/检查/生成蓝图与逻辑）和 `mlogsim.py`（拿真执行器跑逻辑：默认官方 **v160.7** server jar `out/_server160.jar`；`MLOGSIM_JAR` 可切 `_server159.jar` / `_server146.jar`，见 `mlogsim.py:116-122`。注意数据表的 `source:` 仍写 v159.3 —— 那是数据表来源版本，不是模拟器版本）。
其余文件是它们的数据、分析层和一次性维护脚本。

## 常用命令

| 想做什么 | 命令 |
|---|---|
| 看蓝图里的逻辑 | `python tools/mlog.py parse 图.msch` |
| 静态检查 | `python tools/mlog.py check x.mlog`（`--cost` 加成本/最坏指令数，`--rid` 每行尾部显示规则 id） |
| 生成只含处理器的蓝图 | `python tools/mlog.py gen --name 名字 --code x.mlog` |
| 模拟运行 | `python tools/mlogsim.py x.mlog --ticks 120 --trace t.csv` |
| 超大场景（几千台）跑模拟 | `python tools/mlogsim.py 图.msch --ticks 110 --js-timeout 3600`（默认预算 180 s，几万台会把一条 js 命令跑到几分钟） |
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
| 自检工具链 | `python tools/mlog.py selftest`（`--jobs N` 分片）；`python tests/run_tests.py` |

`mlog.py --help` 是子命令总表；`tools/mlogsim.py --help` 是模拟器参数（世界、单位、战斗 tick、trace/assert）。

## 大场景 / 长跑：`--js-timeout` 与分批装载

- **一条 `js` 命令 = 一次墙钟预算**。场景模式把「摆方块 + 配置 + 整个 tick 循环 + 回收变量」全塞进一条命令，默认预算 180 s（`Server.js_timeout`，`Server.wait_for` 超时抛 `SimError("timeout waiting for ...")`）。台数一多必然超：d=64 的 3,758 台跑 120 tick 实测 **1,010 s**，不调预算就只会看到 `r*` 全 null。
- 调法：CLI `--js-timeout SEC`（float，默认 180），库方式 `srv.js_timeout = 3600`。**只影响等待上限，不影响语义**；测试仍 50/50。
- **第二条墙是单条命令的体积**。场景 JSON 里每条处理器都带全文代码，d=128（22,278 台 × ~850 行）拼成一条命令约 700 MB，GraalJS 会直接 `NullPointerException: ... FieldOrMethodRef.getType() because "m" is null`。解法是**分批装载**：先按批 `setBlock` 全部方块，再按批 `b.updateCode()` 并累积到全局 `procs`，最后单独发循环命令。参考实现（作者本地脚本，不随仓发布）（d=128 装载 50 s、2 tick 3 s）。
- 回收变量时注意：`srv.js()` 返回的是**已去掉 `[none/base.js]:` 前缀**的行，直接喂 `parse_results`；拿 `srv.all` 会因时间戳前缀匹配不到。

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

## 子进程生命周期（孤儿 JVM）

`mlogsim.Server` 起的 Java 子进程过去会活过它的 Python 父进程：父进程被强杀（gate 超时、Ctrl-C、探针崩溃）时 Windows 不连带杀子进程，JVM 继续占着内存。曾经堆到 61 个，把机器压到 `There is insufficient memory for the Java Runtime Environment to continue`，`probes` 26 条全红。现在三道闸：

1. **Windows job object**（`KILL_ON_JOB_CLOSE`）：`Server.__init__` 把子进程放进一个属于本进程的 job，本进程无论怎么结束（包括 `taskkill /F`）内核都会带走它；实测硬杀父进程后 3 秒内子进程消失。
2. **atexit 兜底**：正常退出路径上 `_close_live_servers()` 逐个 `close()`。
3. **`close()` 幂等**：置 `_closed`、发 `exit`、`wait(15)`，超时 `kill()`；finally 里关 `stdin`/`stdout` 并释放 job 句柄。

残留清理只清我们自己的 jar（按命令行里的 `_server160.jar` / `jre21` 识别，游戏本体也跑 java.exe），且只清父进程已死的：

```bash
python tools/mlogsim.py --sweep-orphans     # orphan sweep: N stale JVM(s) 1234 5678
```

`tests/probes/run_probes.py` 跑完一轮扫一次；`tests/mlogauxyou/run_ui_smoke.py` 退出前显式 `_close_live_servers()` —— 它以前从不 `srv.close()`，每跑一次泄漏一个 JVM。

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

1. **入口**：`mlog.py`（统一下发子命令）、`mlogagent.py`（`report` / `info` 一条命令跑完五层）、
   `jobqueue.py`（P4 作业队列：状态机 + 双写落盘 + 写入门禁，provider 可换，默认走模板档）、
   `rules_export.py`（把 instr_semantics.json + mlogcheck 的链接槽表导出成游戏内快检用的 JS）。
2. **分析层**：`mlogir.py`（解析/IR）、`mlogcheck.py`（静态检查）、`mlogval.py`（值域）、`mlogcross.py`（跨处理器）、`mlogpack.py`（打包配置）、`msch.py`/`mschgen.py`（蓝图容器）。
3. **模拟器**：`mlogsim.py`（真执行器驱动）、`mlog_needs.py`（扫程序需要的地图/方块/单位/全局量）。
5. **规则**：`review.py`、`rule_seed.py`、`rule_capture.py`、`rule_audit.py`；规则数据在 `rules/`。
6. **数据表维护**：`*_from_source.py`、`build_cmd_index.py`、`block_sizes.py`——需要 `Mindustry-Source`，输出 JSON 已在仓库里，平时不用跑。

   ```
                                                # 大仓库：codeload tar.gz + Python tarfile -> <dest>/<prefix>-flat/ + _index.json
                                                # 解码 + 去重 -> <dest>/_procs/<sha>.mlog + _meta.json
                                                 # 抽样冒烟：只跑 400 个，分析器抛异常就 exit 1（gate --full 用）
                                                 # 指令覆盖率：语料里每条 instruction/op/draw 子命令出现几次
                                                 # 覆盖率关：绝对值随样本漂，只钉「这批样本从不使用的指令集合」；
                                                 # 集合一变就 FAIL，要人重录基线（--write-baseline）
                                                 # 判读表：每条规则 6 条样本 + 机器旁证（名字出现次数 / 是否赋值 /
                                                 # 是否本蓝图链接名），判读栏留空交人填；--verdicts 回填 TP/FP/mixed
        --procs _procs --label anon --stride 8 --jobs 12   # 4 万程序抽样 5.5k，67 s
   python tools/mlog_needs.py <doc>/_procs --brief --no-detail --stride 10
                                                 # 世界符号清单（传感器/单位/方块/全局量）；大语料必须 --no-detail
   ```

   `mlogcheck.analyse(links=...)`，所以 `link-name-not-bound` 这类规则在外部语料上才有意义。
   `map_site.download()` 的 `dest` 必须是 `Path`（传 `str` 报 `AttributeError`）。
   上万文件 / 上百 MB 的仓库放在**工作区外**（如 `<corpus-dir>`），别塞进 同步盘目录；
   这类仓库的**文件名多为中文，Windows 自带 `tar.exe` 会按 CP936 解码 UTF-8 文件名**（`核心入冷` → `鏍稿績鍏ュ喎`），
   不同名字撞成同一文件、只落一半且互相覆盖——必须用 Python `tarfile` 解包；
   `git clone --depth 1` 对大包也不稳（`RPC failed; curl 28 Recv failure: Connection was reset`）。

   对 4 万程序按 `--stride 37` 抽 400 个跑 `check_corpus.py --fail-on-errors`
   （约 10 s），断言「分析器在真实代码上不崩」。紧接着的 `coverage` 步用同一批样本跑
   `instr_coverage.py --limit 400 --baseline tests/corpus-coverage-baseline.json`（0.5 s），
   断言零覆盖指令集合仍是签过字的那 18 条 —— 往 `instr_semantics.json` 加一行、或样本里
   丢一条指令，集合就变，必须有人重新录基线。两步都依赖语料目录；不在 git 里，机器上没有时 SKIP，
   与语料无关的还有一个 `shapes` 步（0.1 s）：`python tests/shapes/run_shapes.py`
   断言检查器自己的**语句形状不变量**——每条规则对坏样例追加 1/2/5 个惰性 token 与行尾注释后仍必须开火，
   防的是整行锚定正则 fail-open（`op select` 那类漏洞；`--module` 可指向旧版做负向自证）。
    和语料无关的还有一个 `docsig` 步（0.2 s）：`python tests/docsig/run_docsig.py` 把五份文档里每个
    「助记符 + `<占位符>`」签名与 `tools/instr_semantics.json` 机检——占位符个数、逐槽名字、`mlog` 代码块的
    示例参数数、表头含 param 的表格列序，以及**第五项**：枚举槽里的名字必须真实存在（`ucontrol`/`draw`/`ulocate`
    第 1 槽查 `instr_semantics.json` 的 `subcommands`、`status` 第 1 槽必须是 `true`/`false` 且第 2 槽查
    `tools/status_names.json`、`sensor` 第 3 槽查 `tools/sensor_attrs.json` 的 LAccess 或 `tools/content_names.json`；
    这几槽在语义表里是枚举 token，**不可能装变量**，所以「不在表里」一定是文档错——2026-10-29 一次抓出 6 处真错：
    `sensor ... @damage`（LAccess 无此项，读 null）、`status <apply|clear>`（第一槽是布尔，写 `apply` 反而静默不生效）、
    `ulocate locate ...`（第一槽是 LLocate，非法值整条编译成 `NoopI`）、`@velX`/`@velY`（真名 `@velocityX`/`@velocityY`）。
    `--self-test` 用合成文档自证五项检查会开火。**第六项**是引用存在性：`docs/速查卡.md` 里每个
    `L\d-\d\d` 必须在 `docs/断言表.md` 里存在，且每个 `## ` 小节至少引用一个 id —— 速查卡是给人查的入口，
    指错编号比没有更糟（负向自证：把 `L9-99` 写进卡片立刻 MISMATCH）。它抓的是「文档教错语法」：
    `getblock <result> <x> <y> <layer>` 这种**数目对、顺序错**的签名（真序 `layer,result,x,y`）在旧文档里
    活了整个版本，玩家照着写就是静默错位。原理写在脚本 docstring 里：mlog 文本 token 序 = Java **字段声明序**
    （`build(LAssembler)` 的传参序与之无关）；`radar` 那种「槽位数没错、语义错」属于已知盲区，只能靠 `probes` 钉住。
    `--full` 独有的四步（`selftest` / `probes` / `corpus` / `coverage`）互不依赖——各自起 JVM、
    两条长杆内部再各自并行：`probes` 每条探针一个 JVM（`run_probes.py --jobs`，默认 min(8, CPU)，41 s → 9.6 s）；
    `selftest` 用进程池把 420 个蓝图分片（`mlog.py selftest --jobs`，26 s → 5.3 s），
    并且**验证用的重建蓝图改用 deflate 级别 1**（`Blueprint(deflate_level=1)`）——级别只影响压缩耗时，
    解析回来的内容一模一样（level 9 = 0.200 s/MB，level 1 = 0.008 s/MB，这一项曾占自检 89% 的时间）；
    生成路径的默认级别仍是 9，蓝图字节与改前逐字节相同。现在 `--full` 约 **15 s**。
    `--serial` 回到串行，`--stream` 也强制串行。
    日常改完跑默认档即可（3.3 s，含 `shapes` 与 `lint`），`--full` 留给提交前/发版前。
   注意 `mlog_needs.py` 的 `programs_detail` 在大语料上是几百 MB，
   4 万程序全量跑要加 `--no-detail`，否则 JSON 慢到像挂死。

9. **一次性脚本**：`dev/`——探针、patch、调试脚本，默认被忽略，不保证能跑，不要依赖。
10. **数据 JSON**（顶层，和代码同目录）：`block_attrs`(253)、`sensor_attrs`(75)、`unit_attrs`、`instr_semantics`、`cmd_index`(86)、`wiki_block_ids`(422)、`block_sizes`(446)、`item_ids`、`status_names`、`label_rules`。

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
    python tests/run_tests.py                     # 门禁：41 条 golden（行为层；副本一致性由上面的 --check 负责）

`--mirror` 只有 skill（默认）/ bp / install / all，**all 不含 global**；写完会对每个目标自动跑一次它自己的 `mlogagent.py info --verify`（要关掉加 `--no-verify`）。

## 维护约定

- 提到顶层的门槛：`tests/run_tests.py` 有 golden 用例，或文档里有命令引用。
- 顶层不放大文件、不放大图；截图/日志/导出物放 `out/`。
