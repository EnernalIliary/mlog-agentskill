---
name: mlog-agentskill
description: 审查 Mindustry mlog 逻辑时使用：一次跑完静态检查/成本/不可达代码/死存储/常量分支/可证 null/打包配置，按证据强弱给出先看哪里，并附每层的校准数字与"不能证明什么"。
whenToUse: 需要审查或解释一段 mlog（.mlog 源码或 .msch 蓝图里的逻辑块）、判断某条语句是否白算、某个分支是否恒真、某个变量是否可能为 null、或某个数字打包了几层字段时。
---

# MLOGAGENT — mlog 逻辑分析

一个入口把六种分析全部跑一遍，并告诉你**先看哪里**。自带完整副本（`tools/` 里 8 个模块 + 5 个数据文件 + `MANIFEST.sha256`），整个目录拷走就能用，不依赖仓库其他部分。

```bash
python tools/mlogagent.py report logic.mlog            # 全部
python tools/mlogagent.py report logic.mlog --brief    # 只要 VERDICT 两行
python tools/mlogagent.py report out.msch              # 蓝图里每个逻辑块各跑一遍
python tools/mlogagent.py info                         # 数据版本 / 模块清单
python tools/mlogagent.py info --verify                # 校验 MANIFEST.sha256
```

位置参数按**后缀**分派：`.msch` 走蓝图解析（一个逻辑块一节），其余按 UTF-8 文本读。

审计一条命令：`python tools/review.py run --pages 2`（抓图+分析+写清单，重写前自动读回上次判定）。

## 工具索引（一条命令一行）

`mlog.py` 是唯一入口，`python mlog.py <子命令> --help` 看全部参数。

| 子命令 | 一句话 | 什么时候用 |
|---|---|---|
| `parse <file.msch>` | 蓝图里有什么方块、每块处理器的源码和链接 | 拿到别人给的蓝图，先看结构 |
| `text <file.msch>` | 信息板（message 块）上写了什么 | 想知道作者说了什么、署名是谁 |
| `gen` | 按逻辑生成可粘贴的蓝图码 | 交付成品；**别手拼 base64** |
| `check [--msch]` | 静态检查：`0 error / 0 warn` 才算过 | 每次改完逻辑 |
| `check --cost` | 最坏一圈多少指令、折合多少 tick、`wait` 阻塞多久 | 判断能不能跟上周期 |
| `ir` | 死存储（四层）、不可达代码、指令直方图 | 找"写了没人读"和死代码 |
| `values` | 常量分支、可证 null（跨处理器要用 `--msch`） | 分支看着可疑时 |
| `pack` | 一个数打包了几层字段、低位够装几个 id | 看到 `*1e6`/`/1e6` 时 |
| `cross <file.msch>` | 跨处理器 `read` 到底读到什么 | 多处理器协作时 |
| `map <save.msav>` | 整个存档里所有处理器 + 逐块检查 | 看别人地图的逻辑 |
| `style <关键词>` | 语料里同类逻辑的命名/形状/成本 | **动手写之前**先看同行怎么写 |
| `explain <指令> [子命令]` | 一条指令的语法、读哪些位、文档勘误 | 拿不准参数顺序时 |
| `sensor [关键词]` | 75 个 `@属性` 能不能 `sensor`、能不能 `control` 写 | 查能读到什么 |
| `unit <名字>` | 单位的速度/血量/护甲/武器/技能 | 算拦截、算 DPS |
| `block <名字>` | 方块的建造配方/液体/输入/收不收物流 | 写产线和物流时 |
| `find <关键词>` | 在语料或蓝图里搜代码 | 找现成写法 |
| `item` / `id` | 物品 ID、方块 content ID 与尺寸 | 需要数字而不是名字时 |
| `cmd [关键词]` | 86 条指令格式速查 | `explain` 之前先扫一眼 |
| `selftest` | 蓝图编解码往返自检（430/430） | 怀疑解析器坏了 |

批量与并行：

```powershell
python tools\corpus\_sweep_saves.py        # 1,421 个存档：34 秒
python tools\corpus\_sweep_analyse.py      # 加六种分析：127 秒
python mindustry-blueprint\tools\parallel.py --items 1421   # 它会开几个 worker、为什么
```

## 语义从哪来：双实现确认

关键的语言事实除了读 `LExecutor.java`，还用 mindcode 的模拟器复核过（八条探针）。
`equal <未赋值> null` 恒真、`logn(0,2)`/`1/0` → null、`sensor @unit @dead` → 1、
`print <未声明>` → `null`、记忆格未写 → 0、`read`/`write` 只认对方已声明的变量 ——
这些是**两个独立实现都这么算**。细节见仓库里的 `mindustry-blueprint/EMULATOR-CROSSCHECK.md`。

## 先读这一节：五层各自能证明什么

| 层 | 回答的问题 | 证据强度 | 全语料命中 |
|---|---|---|---|
| `check` | 语法/参数位/`@dead` 反用这类**确定**错误，以及未定义变量的五层分级 | 最强，可直接改 | A 层误报 ~0 |
| `ir` → 死存储 | 某个变量**写了没人读** | 强，但分四层（见下） | 抽检 28 站全真 |
| `ir` → 不可达 | 某些语句**永远执行不到** | 最强 | 0 |
| `cost` | 一圈**最坏**要多少指令、`wait` 占多少秒 | 近似，可对拍 | — |
| `values` | 某个条件**恒真/恒假**、某个变量**必为 null** | 中，只报能证明的 | 4.1% 的块有信号 |
| `pack` | 一个数字**打包了几层字段**、低位够装几个 id | 强（低频） | 抽检 3 站全真 |
| `check` → build 闸门 | 这份逻辑**最早能跑在哪个 build**（蓝图不存版本号，从语句反推） | 强，只锚定 6 条有发布说明的语句 | 见 `BUILDS.md` |
| `cross` | 另一个处理器的 `read` 到底读到什么（null / 常量 / 无人赋过） | 强（低频 0.5%） | 我的库 3 份 / 彩末包 0 份 |
| `values --msch` | 把 `cross` 的结果喂给值域分析，跨处理器的 `read` 不再一律 ⊤（只迭代一次） | 强，但要求蓝图完整 | 某蓝图 9 条读 → 8 条新结论 |

`VERDICT` 那行是结论摘要；末尾的「先看这里」按上表强弱排序，只指一个地方。

**报告的基线是 build 146**（7.0 Build 146，2023-09-04，v7 首个正式版）：基线里就有的
语句（`effect`、`sync`、`ucontrol autoPathfind`、按名字 `read`/`write` 处理器或 message、
内容 ID 传感器）**永不报告**；只有**比基线新**的才报。判据是 `floor > 146`
（`mlogcheck.BASELINE_BUILD`），不是 `>= 147` —— 换句话说，闸门回答的是
「这份逻辑比 v7 基线新多少」，不是「是不是 v7」。

## 死存储必须分层读

`ir` 默认只报 `reported` 层，其余三层计数后隐藏（`--all` 才列出）：

| 层 | 含义 | 该不该改 |
|---|---|---|
| `reported` | 值被覆盖前没人读(`overwritten`),或从没人读却写了不止一次(`stale-write`) | **是 bug**，逐条看 |
| `slot` | 语法强制的输出槽（`ulocate` 的 `found`、`ucontrol` 的返回等）**且只写一次** | 多数不改，作者不需要那个值 |
| `declaration` | `set x <字面量>` 之后没读 | 作者的声明式初始化；**也可能是留给使用者改的配置**（`set count 0`、`set limit 40`）——先看文件头注释/命名（`cfg.*`）再决定删 |
| `annotation` | 变量名是纯标点（`//`、`--`） | 作者拿变量名当注释，不是 bug |

`stale-write` 专治「强制输出槽写两次」：写**一次**且没人读，可能只是语法逼你起个名字（`slot`，隐藏）；同一个槽**写两次**且从没人读，第一次写就可证被丢弃 —— 那是真 bug。实例：`某蓝图.msch` 的 micro-processor @(16,8)，`found` 在 `L6` 与 `L61` 各被 `ulocate` 写一次、全程序无读；改动前它被归进 `slot`、只算进 `(+3 hidden)`，改动后才作为 `reported` 报出来。

mlog **只有 `#` 起注释**（`LParser.java:98-99`），没有行尾注释 —— 所以 `set // 上个位置` 是**真语句**，游戏照执行。这类占语料 `reported` 的 222 条，已归入 `annotation`。

## 「未定义变量」要先分五层，再决定改不改

`check` 报 `` `X` is read here but is never assigned `` 时**先别改**：mlog 圈有一整套只用变量列表承载的写作习惯，靠语言规范测不出来，只能从用户嘴里知道。全包 926 份蓝图的实测分布（A 从 883 条降到 77 条，就是这五层分出来的）：

| 层 | 含义 | 条数 | 改不改 |
|---|---|---:|---|
| **A 真错** | 名字被读的地方，值真的改变行为 | 77 | **要改** |
| B 恒真守卫 | `jump` 两侧都是常量 ⇒ 分支固定 | 55 | 一般不用 |
| C 无效参数 | 名字落在指令**读不到**的参数位上 | 944 | 不用 |
| D 死引用 | 形如链接名，但这块处理器没有这个链接 | 788 | **要改**（静默失效） |
| E 署名 | 只为出现在编辑器变量列表里 | 5540 | 不用 |

各层的判据与实例：

- **E 署名**。编辑器变量列表会显示程序用到的所有变量，所以写个自己的名字当变量就是署名：`print by:NOSB(hghg`、`set Madeby mineqwwe`、`jump 21 equal colour ender`（整合者彩色末影的名字，两个都未赋值 ⇒ 0==0 恒真，既是署名又当 `always` 用）、`control config Carrot 0914 0 0 0`。检查器判 **INFO**：目标变量全程序无人读、名字只出现在 `print` 里、或纯标点名。
- **C 无效参数**。语句长度 > 指令真正读的位数时，多出来的 token 是**惰性**的（`LParser` 按 `arity` 填字段，多的丢掉）。`control` 只有三个有效位（类型 / 目标 / p1，p2–p4 被各方块类型忽略）；`ucontrol` 各子命令按 `semantic_uses` 算，`flag`/`payTake` 只有一个语义参数；一元 `op` 的第三位永远丢掉（`op rand g 255 b` 的 `b`）。署名和"占位开关"都塞在这里。
- **B 恒真守卫**。`jump T equal X Y` 两边都不是变量赋值时，分支是常量。要么是署名，要么作者想要 `always`。
- **D 死引用**。`scatter1` 这种名字**看着**是有效链接，但处理器的链接表里没有它 —— `LExecutor` 的 `validLink(b)` 直接挡掉，`control shootp scatter1` 一发不发，不报错、不崩溃。`.mlog` 单独文件没有链接表，只有 `.msch` 能查。

- **F 特权内置变量**。`@server` / `@client` / `@clientUnit` / `@clientName` … 在普通处理器里不是「未定义」，而是 `GlobalVars.get(name, false)` 直接返回的 **null 常量**：不报错、指令照跑、分支永远不走。`check` 报 **INFO**；只有 world processor（privileged）看得到真值。见到 `INFO ... privileged` 先确认这段逻辑跑在哪个方块上，别急着改代码。

真正要改的 A 层长这样：`op mod n n padNeedCount`（模数 0 ⇒ null）、`ubind u` 而 `u` 从未赋过、`control config unloader1 mmm 0 0 0`（`mmm` 当 0 用，但写成了名字）、`flase` 拼错落在 `ulocate` 的 enemy 位。

## 语言事实速查（每条都曾经让我误判）

| 事实 | 源码 | 后果 |
|---|---|---|
| `true`/`false` 是**注册常量**（1 / 0） | `GlobalVars.java:54-55` `putEntry("false", 0)`、`putEntry("true", 1)`，`LAssembler.var()` 先查 `logicVars` 才轮到 `putVar` | `jump T equal X true` 就是 `X == 1`，**不是**未赋值变量 |
| `lookup` 的结果在**第 2 参** | `LStatements.java:875-909`，第 0 位是 `ContentType` 关键字 | 把 `unit` 当目标 ⇒ 每个 `ubind u` 都变假错 |
| `ubind` 给类型和给单位的语义不同 | `LExecutor.UnitBindI`：类型走 `unitCache`，`exec.binds[id]` 取模后自增（轮转）；单位满足同队/特权且 `logicControllable` 才直接绑 | `ubind @flare` 每轮可能是不同单位；要盯一个就 `ubind unit.target`，否则 `sensor` 读到的是“另一个单位” |
| `ucontrol getBlock x y a b c` 有**三个输出** | `LExecutor.java:491-509`（p3/p4/p5） | 只认一个输出会把 `b` 当未赋值 |
| `ucontrol within x y r result` | `LExecutor.java:377` `p4.setnum(unit.within(...))` | `r` 是半径，`result` 是 1/0 |
| `equal X null` ⇔ `X.num() == 0` | `ConditionOp.java:31-40` | 对未赋值变量**恒真**；只有 `===` 区分 null 与 0 |
| NaN / ±Infinity 被静默转成 null | `LVar.setnum()` | 这是按位剥离循环的退出机制，也是"不能把 `rand` 建模成 NaN"的原因 |
| `noop` 是 `InvalidStatement` | `LStatements.java:48-59` 的类名就叫 `InvalidStatement`，`build()` 返回空跑的 `NoopI` | 游戏把**解析不了的语句**写成 `noop`。它是**丢失语句的墓碑**：高版本逻辑在低版本打开时丢一条语句，程序往往就此跑不动（丢的正是干活的那条）⇒ 判 **ERR** |
| `//` **不是**注释 | `LParser.java:98-99` 只认 `#` | `set // 上个位置` 是真语句 |
| `jump -1 always` 是 **nop** | `JumpI.run()` 有 `if(address != -1)` | 不是终止，继续往下走；当成终止会误报整片不可达 |
| `jump T always x false` 的 `x`/`false` 是补位 | `LParser` 多 token 惰性丢弃 | 派发表生成器的常见产物，不读 |
| `op add @counter @counter id` 是**派发表** | 下一句就是第 `id` 行 | 静态可达性从此失效，`ir` 会主动抑制不可达报告 |
| `0x`/`0b`/`%rrggbb` 是字面量 | `LAssembler.java:87-99` | 当成变量会误报硬错 |
| `control` 的 p2–p4 各方块忽略 | `LExecutor.ControlI.run()` | 实用有效位只有三个 |
| `ucontrol payTake`/`boost` 只吃布尔 | `LUnitControl.java:17,20` | 未赋值 ⇒ 恒 false，"只捡建筑" |
| `read`/`write` 的 `@this "名字"` 是**处理器变量** | `LogicBlock.java:607-620, 644-650`：字符串先 `optionalVar(name)`，没有再 `optionalLink(name)`；write 找不到变量直接 return | 名字是字符串不是变量；写未声明=静默空操作（`check` 报 INFO `self-write-noop`），读未声明=null（INFO `self-read-undefined`）；数字下标 `read v @this 0` 是链接 |

## 「我以为是作者写错」清单（其实都是检查器的 bug）

这一轮全包审查里，每一条误报都变成了规则，记下来免得下次重犯：

- 十六进制/二进制造型（`%ff0000`、`0b1010`）被当变量 → 硬错 1100 → 883。
- 一元 `op` 的第三位被当读取 → 182 条假警告清零。
- `jump T always x false` 的补位被当变量 → 276 个块凭空多出未定义 `x`。
- 派发表（写 `@counter`）⇒ 不可达 9384 → 495。
- `jump -1 always` 当终止 ⇒ `某蓝图.msch` 190 条里报 182 条不可达，实际全部可达。
- `lookup` 目标位算错 ⇒ `u` 族 23 条假错。
- **只看 `LAssembler.var()` 就断定 `true`/`false` 不是关键字** ⇒ 653 条假 WARN。真相在 `GlobalVars.init()`:它们是 `putEntry` 注册的常量 1 / 0。教训:**判一个名字是不是内建，要查"注册了什么"，不是查"解析函数怎么处理"** —— `var()` 第一步 `logicVars.get()` 就把它们接走了。
- `ucontrol getBlock` 只认一个输出 ⇒ `f` 假错。
- `struct` 层面的教训：**一个分析工具的第一次全量运行，主要产出是它自己的 bug 列表。**先抽样人工核对 20–30 站，再谈精度。

## 交付前先过一遍

`check` 0 error/0 warn → `ir` 无死存储 → `cost` 对上周期（含 `wait` 的 `⏸ blocking`）→ `values` 无意外恒真分支 → `cross` 无未声明槽 → 与 `style` 的命名风格一致 → 把"模拟器验证不了的部分"写清。阈值和失败策略**先问提问者**，不要自己定。

## 校准数字

**910 份真实蓝图 / 617 个文件（2409 个逻辑块）**

- `ir`：**80.9% 的处理器一条都不报**，p50 = 0、p90 = 1；均值 0.829/块是被约 20 个代码生成式蓝图（每个 60–78 条）拉高的。看**干净块占比**，别看均值。
- `values`：2396 块里 4.1% 有信号（常量分支 0.120/块、可证 null 0.060/块），39 ms/块，未收敛 0。
- `pack`：2420 块里只有 **3 块**（0.1%）用了打包，bit peel（`x & -x` + `log2`）**0 块**。

**蓝图包 926 份（481 份有逻辑、1698 块、359,131 条语句）**

- 五层分布见上面那张表：A 77 / B 55 / C 944 / D 788 / E 5540。
- 死存储 `reported` 2156 条 / 232 隐藏；常量分支 `values` 命中 98 块（4.1%）。
- 每块语句数：中位 **41**、p90 **902**、上限 **1000**（正好是 `maxInstructionsPerTick`，说明有人把预算写满）。
- 两批语料要分开算：`⭐不正经的东西⭐` + `🎯逻辑小游戏🎯` 只有 109 份文件却占 **87% 的语句量**（热舞 / 坏苹果 / 香蕉君这类动画演示，自旋是设计意图）。严肃子集 817 文件 / 902 块 / 45,722 语句里，硬错 16.6 条/千语句。

出现率差三个数量级 ⇒ **`ir` 是 linter，`pack` 是"点开就说话"的专用检查**，不能拿同一把尺子量。`pack` 也不是 linter：0.1% 的命中率意味着"报了就是有话说"，但"没报"不代表没打包。

## values 的语言事实（不记住会误判）

- `equal x null` ⇔ `x.num() == 0` —— **对从未赋值的变量恒真**（`LVar` 默认 `numval=0`、`isobj=false`）。只有 `===` 区分 null 与 0。（`ConditionOp.java:31-40`）
- NaN / ±Infinity 在 `LVar.setnum()` 里被**静默转成 null**。这就是 `op logn x 2` 在 `x=0` 时得 `-Infinity` → null、从而成为按位剥离循环退出条件的原因 —— **令牌流里没有任何字面信息说"退出"，只有值域说得清**。
- 所以 `op rand` / `op noise` 的值**不能建模成 NaN**（那会变成"必定是 null"）；本项目里它们一律是 ⊤。

## 真执行器模拟器（`mlogsim.py`）

这份副本只做静态分析；`mlogsim.py` 在本仓库根的 `tools/`，不在本目录里。它驱动真 `LExecutor`（默认 v160.7 + JRE21，`MLOGSIM_JAR`/`MLOGSIM_JAVA` 可换），不是重写的 VM。

```bash
python tools/mlogsim.py logic.mlog --steps 20                    # 指令级，不跑世界
python tools/mlogsim.py logic.mlog --ticks 120 --update all      # tick 级，工厂/单位也动
python tools/mlogsim.py logic.mlog --save scene.msav --units fortress:1 \
  --ticks 120 --trace out/t.csv --assert-last "chp < 3500"
```

- 世界：空白 64×64（默认）/ `--host` 随机真实图 / `--save` 载存档（自动在我方核心旁放处理器，`--base X,Y` 覆盖）。
- 单位：`--units name:count`、`--unit-pos X,Y`、`--unit-ai all`（场景原有单位按 AI 行动）。单位落在实体格会在第一次 `update()` 被 `kill()`，所以 tick 1 会跑 `PREFLIGHT:`（编译失败、单位没生成、落地即死都会直接报，不用等 1200 tick）。
- 库存：`--core-items silicon:400,copper:200` 给核心灌料（空白世界会自动放一个 `core-shard`）；`ulocate` 找核心、`itemTake`/`itemDrop` 取放料由此可断言（距离上限 `45 world + 方块半宽`，先 `approach` 到 2 格内）。
- 链接：裸 `.mlog` 没有链接表；`--links auto`（默认）会找出读而不赋值的链接名（`cell1`、`bank1`、`message1`、`dome1`）自动放同类方块并接线（同队、10 格内），`--links off` 才是 `null`。`.msch` 用自己的链接表。
- 世界更新：`--update all` 跑真 `Building.update()` 与 `LogicAI` 单位；`--power full|none` 钉电力；`--combat on`（`--ticks` 默认）按 `Logic.updateEntities()` 推进子弹物理/碰撞/伤害；`--weather rain` 强制开局天气。
- 观测：`--trace FILE` 每 tick 一行（`unit,tick,ux,uy,uhp,range,tx,ty,dist,cx,cy,chp,bullets,shots`，tile 坐标）；`--assert EXPR` 逐行、`--assert-last EXPR` 只查末行，失败退 3。
- 特权语句（`weathersense/weatherset/setrule/message/...`）只有 world processor 认，放微处理器里整行被静默删掉；`--processor auto` 自动选。
- 证明不了：野 AI、波次、电力图、真实地形碰撞、建筑被毁连锁；`draw` 执行但无画面。**真游戏行为必须玩家验收**，交付时把"跑过"和"读起来没错"分开写。
- 现成场景：`out/scenes/`（5 张现实存档）、`out/scenes/benches/run.py`（memory/processor/sensor/core 四张台子，62 项断言）、`_snapshot.py`（PNG 快照）。

## 边界：这些工具证明不了的事

- **不跨处理器(说明:`read`/`write` 可以按**名字**访问另一个处理器的变量(必須提前聲明、寫給未聲明的槽是靜默空操作)。老蓝图库里看不到这种写法,所以对老库「这个变量从未赋值」的判断是可靠的;新库里它是一条合法的"别处赋值"路径 —— 报 A 层之前先确认两份逻辑是不是同一代产物。)**。别的处理器 `read x cell1 "名字"` 看不见；实测 0 例，但 `ir` 报了死存储仍要自查有没有跨块约定。
- **只判"值有没有人用"，不判"值算得对不对"**。`op add dx dy dx` 想算距离却写成加法，`ir` 不报。
- **外部输入一律 ⊤**。`sensor` / `getlink` / `ulocate` 拿到的都是运行期状态 ⇒ 一半变量退化成未知，`values` 只能对纯计算链说话。
- `values` 3 轮后按变量放宽；`cost` 在 1000 条处截断并显式打 `>=`（那是下界，不是总量）。
- `pack` 只认**同一 `src` 上 ≥2 个不同指数**的 `op idiv`，不重建表达式；`MIN_EXP = 3`。
- **模拟器只到「逻辑层 + 单位运动层（B 档）+ 世界更新/天气 + 子弹命中」**。`tools/mlogsim.py` 跑真 `LExecutor`；`--update all` 下真 `Building.update()`（工厂/传送带/电力消费者，满电由 `--power` 钉）与真 `LogicAI` 单位 `update()`；tick 循环复刻 `Logic.updateWeather()` 的冷却/生成并 `Groups.weather.update()`；`--combat on`（`--ticks` 默认）按 `Logic.updateEntities()` 的顺序跑 `Groups.bullet.updatePhysics/update/collide`，所以 `ucontrol target` 的子弹会飞、会命中、会掉血。能证明 `move/approach/within/@x/@y`、生产进度、`weathersense/weatherset` 时序、目标 hp 变化。`--trace FILE` 每 tick 记逻辑单位一行（`unit,tick,ux,uy,uhp,range,tx,ty,dist,cx,cy,chp,bullets,shots`），`--assert` 逐行不变量、`--assert-last` 只看末行（失败退 3）。`weathersense`/`weatherset` 等特权语句只有 world processor 认，微处理器会把整行**静默删掉**（`--processor auto` 按语句自动选）。不模拟野 AI、波次、敌方 AI、电力图、真实地形碰撞，也不结算建筑被毁后的连锁后果。`shots` 增加不等于命中——必须看 `chp` 并开 `--combat off` 对照。**真游戏行为必须由玩家在游戏里验收**——模拟器通过不等于上手能跑；交付时要把「哪些部分是模拟器验证过的、哪些要你进游戏试」分开写。普通处理器读 `@client`/`@clientUnit` 等特权内置变量不会报错，而是静默得到 `null`（`GlobalVars.get(name,false)`）；要玩家/客户端数据只能用 world processor。AI 生成的逻辑必须先 `python tools/aigenerated.py sign` 签名（署名不可去除，交付前 `verify`）。

## 典型流程

1. `report --brief` 看 `VERDICT`，先确定有没有 `check` 报错。
2. 看「先看这里」指向哪层，只展开那一节（`--only ir` 之类）。
3. 展开前对照上面的**校准数字**，判断这一层的命中率是"正常噪声"还是"确实该看"。`ir` 报 1 条是常态，报 60 条要看生成方式。
4. 需要逐条证据时用 `--all` / `--trace VAR`，或退回单项工具拿更细的输出。

单项工具仍然可用（同一份 `tools/` 里）：`mlog.py check|ir|values|pack|explain|cmd|id|item|parse|gen`。`explain` 是查**某条指令哪个参数是输出**的唯一权威来源 —— 官方文档有 8 条指令的参数顺序是错的，`explain` 会直接打 `!! DOCS WRONG`。

## 环境（这份副本可以单独拿走）

- **Python 3.10+，只用标准库**，没有第三方依赖。
- `tools/` 里 16 个文件自带齐全，`SKILL.md` 与 `MANIFEST.sha256` 一起拷走即可；`python tools/mlogagent.py info --verify` 会核对每个文件的 SHA256。
- 要分析的蓝图可以是 `.msch` 二进制、base64 文本或整个目录；**不读游戏安装目录**，只读你给的文件。
- 控制台需要 UTF-8（`chcp 65001`），否则中文变量名显示为乱码（文件本身没问题）。

## 维护

这个技能的 `tools/` 是从 `mindustry-blueprint/tools/` **整份拷过来的副本**，不是链接 —— 目的就是让目录能被单独拷走。改了任何模块之后在仓库里跑：

```
python mindustry-blueprint/tools/sync_mlogagent.py          # 重新拷贝 + 重写 MANIFEST.sha256
python mindustry-blueprint/tools/sync_mlogagent.py --check  # 只比对，过期时 exit 1
```

本目录的 `SKILL.md` **不参与同步**（它只属于这个技能；蓝图技能有自己的一份）。两份工具不一致时 `mlogagent.py info --verify` 会报 `MISMATCH` 并指出是哪几个文件。

## 死循环

只有两种能静态证明,其余一律不报:

- `jump <head> strictEqual ctrl @this` + 环内 `ubind <类型>` ⇒ `ubind` 立刻把单位认领给本处理器,守卫从此恒真,**永不退出**(ERR)。
- `notEqual … @this` + 同一句 `ubind` ⇒ 守卫立刻恒假,循环一遍就结束 —— 这是标准写法,不报。
- 真实语料 900 块里该形状 0 处;等外部状态的自旋 0.33 条/块,不报。

`sensor` 的属性表（75 条，一条一句人话）来自 `LAccess.java`：`mlog.py sensor heat`。三条陷阱：`@heat` 在力墙上是被打掉的盾量、`@size` 对字符串返回 UTF-16 长度、`@dead` 在单位是 null 时也返回 1。

## 方块表里有什么、没有什么

`block_attrs.json` 由 `tools/blocks_from_source.py` 从 `Blocks.java` 抽，253 个方块有行为记录。

```bash
python mlog.py block cryofluid-mixer     # 一个方块的完整画像
python mlog.py block --accepts coal      # 谁吃煤（按 recipe / ammo / any / custom 分组）
```

一个方块能查到：

| 字段 | 例子 | 说明 |
|---|---|---|
| `build` | `lead:65 + silicon:40 + titanium:60  (crafting)` | 建造配方 + 分类；多次 `requirements()` 会合并成廉价层/升级层 |
| `liquids` | `water:12/s -> cryofluid:12/s` | 输入液体 → 输出液体，**已折成每秒** |
| `inputs` | `coal:1 + sand:2 -> silicon:1  craftTime 40` | 配方输入（每 craftTime 一次） |
| `booster` | `silicon:1  (optional; speeds the block up)` | 可选加速物，**不给也能跑** |
| `coolant` | `water` | 冷却液（不进配方，影响效率） |
| `accepts` | `any` / `only ...` / `ammo ...` / `nothing` | 物流能不能塞进去 |

三个读法坑：

1. **`build` 不是配方。** `build` 那行是「造这个方块要什么」，`inputs` 才是「它生产时吃什么」。写产线时两个都要看。
2. **液体量是每秒**（源码写的是每 tick，`_rate()` 折过）。折不了的带布尔重载原样显示源码算式。
3. **「烧整类物品」没有清单。** `rtg-generator` 显示 `burns radioactive items (no fixed item list)` —— 引擎按类别判，别去查它到底吃哪几种。


## 读整个存档里的逻辑：`mlog.py map`

```bash
python tools/mlog.py map "C:/Users/<you>/AppData/Roaming/Mindustry/saves/430.msav"
python tools/mlog.py map <save.msav> --verbose --show 0   # 连干净的一起列，只报汇总
python tools/mlog.py map <save.msav> --code 3            # 每块再打前 3 行源码
```

支持 build 146 之后的三种瓦片布局（存档版本 7–9 shortchunk、10–13 现代）；
版本 6 及更早的老存档不支持，会明确说 `legacy layout`。

- 每个处理器一行：坐标、方块类型、语句数、链接数，以及 `check` 的结论。
- 链接名来自存档里的链路表，所以「这个链接不存在」这类警告在整图上下文里同样可靠。
- 大存档会很慢（`235.msav` 613 个处理器、56 万条语句）：先 `--show 0` 看汇总。

### 全量体检（1421 个存档）

`mlog.py map` 一次读一个文件。要看**所有**存档，先按源码哈希去重再跑静态检查
（本地语料脚本（未随公开版发布））：1421 个存档、103,787 个处理器，去重后只有
**4,366 份不同的程序**（95.8% 是同一段代码的副本）——所以报告里所有比率的分母
都是「不同的程序」，不是「处理器」。

### 存档里的程序没有名字

`mlog` 没有名字字段（只有蓝图有 `name`/`description`）；存档里唯一的名字是地图名。判用途靠三个信号：
**链接名**（默认是方块名+序号）、**指令直方图**（`draw`=显示 / `ubind`=单位 / `control config`=物流 / `setrule`=世界规则）、
**代码里的字符串**（`print` 出去给人看的那一两段字）。按这三样分桶的现成结果在 `out/saves_programs.md`。

### 钍反保护:三条事实

| 事实 | 数字 | 出处 |
|---|---|---|
| 有冷却液时 `@heat` 恒为 0 | 一 tick 清零,稳态 1.2 液/秒 | `NuclearReactor.java:95-125` |
| `control enabled 0` 不是灭火 | 停了还要 1200 tick(20 s)才从 0.999 降到 0 | 同上,ambient 冷却 |
| 满料 100 tick 爆炸 | 发热 0.01/tick,`@heat >= 0.999` 即 `kill()` | 同上 |
| 链接名不能证明类型 | `reactor1` 可能是钍反或冲反,而 `@heat` 在两台上是相反的意思;要 `sensor x reactor1 @type` 证明类型才敢报 WARN,否则只报 INFO 提问 | 2026-10-18 用户实测纠正 |
| 冲反的 `@heat` 是 warmup | 出力 = `warmup^5`:卡在 0.5 只有 3.1%、0.9 有 59%、0.99 有 95%;满载要 ~6908 tick(115 s),**永远不会因为热而爆炸** | `ImpactReactor.java:117-120` |

保护逻辑的正确性不看阈值看**检查间隔**:满料 `(0.999 - 阈值)/0.01` tick 内必须再看一眼,
间隔 = 循环体语句数 ÷ 处理器 ipt。`mlog.py check` 会报 `reactor guard is too slow`。

### 批量跑语料

```powershell
python tools\corpus\_sweep_saves.py              # 1,421 个存档：34 秒
python tools\corpus\_sweep_analyse.py            # 加六种分析：127 秒
python mindustry-blueprint\tools\parallel.py --items 1421   # 先看它会开几个 worker、为什么
```

`parallel.py` 自己算 worker 数：核数、可用内存、**最大文件**三个上限取最小。重文件
（≥1 MB）单独一段、用更少的 worker —— 一个 4.5 MB 的存档里有 6,600 个处理器，按平均值
分 worker 会让几个这样的文件同时把内存吃干。想调就 `--workers N` 或 `--serial`。

### 病毒逻辑（自我复制）

```powershell
python mlog.py check someone.msch --msch      # 命中会打 [INFO] virus-logic
```

判据只有一行：`ucontrol build <x> <y> <块> <朝向> @this` —— 最后一个参数是新方块的 config，
传 `@this` 就是「造一个跑我这份程序的方块」，于是它复制自己、复制出的再复制。圈内叫
**病毒逻辑**。`@this` 经变量中转（`set cfg @this`）也算。

实测：1,421 个存档里 9,151 个处理器是病毒，但**只来自 2 份不同的程序**（`556.msav` 6,616 份
副本、`538.msav` 1,432 份）。看到一张图里几千个处理器，先怀疑这个，别急着叫它"逻辑计算机"。

### 规则与逐条审计（`rules/` + `review.py`）

python tools/review.py md --unjudged         # out/audit_review.md：源码 + `判定:` 空位，在编辑器里逐条判
python tools/review.py ingest                # 把 md 里填的 ok/bad/unsure/skip 读回 out/verdicts.csv
分析器说的每一句「这行有问题」，都该能追到一条**有证据、有反例**的规则；
而每条规则都该能被一个人判成「对 / 错 / 不知道」。

```bash
python tools/rule_capture.py list            # 25 条规则，带实测命中数
python tools/rule_capture.py lint -v         # schema + 反例必须不命中
python tools/rule_audit.py --dir out/maps    # 按规则统计噪声 → out/rule_audit_maps.md
python tools/review.py build --dir out/maps  # 压成可判的行 → out/audit_rows.json
python tools/review.py list --unjudged       # 还没判的
python tools/review.py show <id>             # 该行上下文（>>>> 标出）
python tools/review.py bad <id> --note "为什么"
python tools/review.py stats                 # 每条规则你判了几条、错了几条
python tools/review.py export                # out/audit.md，分组表格
```

- **kind**：`semantics`（游戏就是这样，禁止自动降级）/ `heuristic`（统计，可降级）/ `negative`（看着像错其实对，用来挡住想写的规则）。
- **单向棘轮**：降级（WARN→INFO）可以让机器提议，升级永远要人点头。
- 判词只有四个：`ok` / `bad` / `unsure` / `skip`。`bad` 攒够了就说明规则该删或该收窄。

