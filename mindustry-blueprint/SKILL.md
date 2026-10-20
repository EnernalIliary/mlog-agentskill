---
name: mindustry-blueprint
description: 生成/解析/校验 Mindustry 蓝图与 mlog 逻辑时使用：从蓝图提取逻辑源码、按逻辑生成可粘贴的蓝图码、静态检查 mlog、查方块 content ID 与指令格式。
whenToUse: 涉及 Mindustry 蓝图（.msch / 蓝图码）、mlog 逻辑编写或审查、需要方块尺寸或 content ID 时。
---

# Mindustry 蓝图与 mlog 工具链


## 目录

- 这个技能能做什么
- 标准流程
- 铁律(生成前逐条自查)
- 交付逻辑前的自检清单（一条都别跳）
- 写逻辑之前：先查这四样
- 单位表里有什么、没有什么
- 方块表里有什么、没有什么
- 写逻辑之前：先看语料里的同类是怎么写的
- 写逻辑:枚举、跳表还是内存格
- 指令预算:别猜,这是确定的
- ⚠️ 最容易搞错的一件事:方块坐标是「中心格」
- 生成蓝图时的作者标签
- 自动打标签
- 常用调用
- 成本分析(`--cost`)看什么
- `ir` 看什么、不看什么
- `values` 看什么、不看什么
- `values` 的跨处理器模式
- `cross` 只看跨处理器,不看记忆格
- `pack` 看什么、不看什么
- 「未定义变量」要先分五层,再决定改不改
- 死循环怎么查
- 病毒逻辑（自我复制）
- 读整个存档里的逻辑：`mlog.py map`
- 批量跑语料(并行)
- 钍反保护:三条事实
- 语义是谁说的：第二实现交叉验证
- 独立副本
- 改完分析器先跑測試
- 环境要求（分享给别人之前先看这段）
- 参考数据
- 关键事实速查


| `ucontrol move x y` 是 **4 个字段** | 语句对象有 6 个槽、`LExecutor` 无条件转换 `p1..p3`，但 `move` 只读 `x,y`（`approach` 才读第三个当半径）；`pathfind` 同理。别照编辑器补的 `0 0 0` 数参数 |
| 一元算子多写一个操作数不算错 | `op floor a b`、`op sin y angle 90` —— 多出来的 token 被 `LParser` 丢弃，运行时无影响，只算 INFO。但 `op sin` 吃弧度，写 `90` 往往说明作者以为是角度 |

## 这个技能能做什么

| 能力 | 命令 |
|---|---|
| **解析蓝图** —— 提取逻辑源码、方块、链接 | `mlog.py parse <file.msch> [--plain] [--no-text]` |
| **生成蓝图** —— 从 mlog 产出可粘贴蓝图码 | `mlog.py gen <logic.mlog> ...` |
| **静态检查 mlog** —— 抓 `@dead` 反用等真实 bug | `mlog.py check <logic.mlog>` |
| **成本分析** —— 死代码 + 最坏指令数 + 折合耗时 | `mlog.py check <logic.mlog> --cost` |
| **死存储 / 不可达代码** —— CFG + 活跃变量不动点 | `mlog.py ir <logic.mlog>` |
| **常量分支 / 可证 null** —— 抽象值不动点 | `mlog.py values <logic.mlog>` |
| **打包配置** —— 字段布局 + 低位能装几个 id | `mlog.py pack <logic.mlog>` |
| **查方块 ID / 尺寸** | `mlog.py id [名称]` |
| **查物品 ID / 解打包配置** | `mlog.py item [名称] [--unpack N]` |
| **查单位属性**（写逻辑第一步选单位） | `mlog.py unit [名称]`（速度/血量/护甲/武器/主动技能） |
| **查方块配方 / 容量 / 功耗** | `mlog.py block [名称]` |
| **找参考实现** | `mlog.py find "几个词"` |
| **查 sensor 能读什么** | `mlog.py sensor [关键词]` |
| **查指令格式** | `mlog.py cmd [关键字]` |
| **读信息板内容** —— 蓝图里 message 方块写的字 | mlog.py text <file.msch> [--plain] |
| **查一条指令的读写位** —— 哪个参数是输出 | `mlog.py explain <指令> [子命令]` |
| **查这条语句要哪个版本** `format` 147 / `select` 150 | `BUILDS.md`（GitHub 发布说明摘要），`mlog.py explain <指令>` 会直接打印 |
| **查这份逻辑要哪个 build** —— 蓝图不存版本号 | `mlog.py check` 的 `version gate` 行 / `mlogagent report` 的 `build >=N` |
| **跨处理器读写** —— 读到的到底是 null 还是常量 | `mlog.py cross <blueprint.msch>` |
| **回归自测** —— 429 个真实蓝图往返校验 | `mlog.py selftest` |

工具在 `tools/` 下,零第三方依赖(纯标准库)。`python tools/mlog.py --help`。

## 标准流程

```
写 mlog  →  mlog.py check --cost  →  mlog.py gen  →  游戏内实测  →  结论写回本文件
              ↑                                                        │
              └────────────────────────────────────────────────────────┘
```

**生成蓝图时必须遵守"确定性 + 自验证"**:

- 同一份源码 + 同一组参数 → **完全相同的字节**(不要引入时间戳/随机量)
- 生成前先跑 `check`
- 生成后**必须**重新解析验证(工具已内置,失败会拒绝输出)

## 铁律(生成前逐条自查)

1. **`@dead` 死亡返回 1** —— "死了就重绑"必须写 `equal`,不是 `notEqual`。**这条抓出过真实 bug。**
2. **控制单位前必须 `ubind`** —— 否则 `@unit` 为 `null`,所有 `ucontrol`/`uradar`/`ulocate` 静默失效。`ubind @flare` 是同类型**轮流绑**（内部计数器，每次 +1），`ubind someUnit` 才是绑那个具体单位；要盯住一个单位就别反复绑类型。
3. **`ulocate` 第 8 参必须接住** —— 写 `0` 就丢掉了建筑引用,后面无法 `itemTake`/`itemDrop`。
   (`core` 不是内置关键字,它只是接收这个输出的**变量名**。)
4. **取货点用 `move`,不要用 `approach`** —— `approach` 停在半径外可能够不到仓库,而 `itemTake` 够不到时**静默跳过**。
   `move` 不读第 3 个参数。(`move` 精确到 1 格;`approach` 停在 `radius - 7`)
5. **`ulocate` 要无条件执行,不能放进分支** —— 否则另一条路径上坐标从未赋值,单位会飞向 `(0,0)`。
6. **`end` 是"跳回开头"**,不能用来"结束一个分支后继续往下"。分支互斥请用 `jump`。
7. **`jump` 存的是绝对行号** —— 增删一行全盘偏移,生成前逐条数一遍。重点查:目标是否落在 `sensor`/`set` 这类有副作用的行上。
8. **单位只能带一种物品** —— `itemCapacity` 是**堆叠上限**,不是每种物品的上限。
9. **`op` 是固定元数** —— `abs`/`floor`/`sin`/`rand` 等一元运算只吃 2 个参数。
   (多写的 token 不参与执行,行为正常,但也不是你以为的运算。)
10. **不要自己发明阈值,不要做可行性推算** —— 游戏机制只要求某个下限,满足即满效率。
    实际战场有阻挡、有堵车;**"能跑"是实测出来的,不是算出来的**。
11. **不要为了讨好检查器去改正确的代码** —— 检查器是提示器,实测才是标准。
12. **`end` 之后不要再写语句** —— 它是"跳回程序开头",不是"结束"。写在它后面的都是死代码。
    用 `--cost` 一跑就能看到(会直接列出来)。

## 交付逻辑前的自检清单（一条都别跳）

写完之后按顺序过一遍，全部有答案才能交：

1. **先问过提问者**——数量、阈值、失败策略（超限怎么办：停机/降级/报警）、依赖哪些方块、要求的周期。没问就问，别自己定。阈值是最容易"我以为是"的地方：钍反防爆要的 0.5 我只知道是爆炸线，工作点 0.30 是我的判断，必须说明。
2. **`check`**：`0 error / 0 warn`。有 `no-target-jump`、`version drift`、`noop` 之类必须先解释。
3. **`ir`**：无 `reported` 死存储；不可达代码要能说出"为什么留着"。
4. **`cost`**：`worst-case path` 与每圈 tick 对上需求里的周期；把 `wait` 的 `⏸ blocking` 一起看（它一条 ipt 都不烧，但周期时间常常全在这里）。
5. **`values`**：没有意外的恒真/恒假分支和可证 null（尤其是 `equal X null`——未赋值变量是 0，只有 `===` 区分 null 与 0）。
6. **跨处理器**（用了 `read`/`write` 别的处理器时）：`cross` 报 `0 never-assigned`；槽名必须在对方先声明，且拼写一致。
7. **署名**：AI 生成的逻辑先 `python tools/aigenerated.py sign <file>`，交付前 `verify` 一遍。署名是最后一条语句末尾**超出参数个数的字符串**（`end "aigenerated:作者:id"`）：解析器填完字段后把多余 token 丢掉，所以行为、`print` 输出、语句数、最坏指令数都不变；改逻辑或删 token 都会验证失败（`strip` 被策略拒绝）。变量命名跟 `style` 里看到的语料风格一致。
8. **假设写清**：静态分析之外，时序、跨处理器读写、单位运动、生产/天气/子弹命中都要用 `tools/mlogsim.py` 跑真执行器（见下节）；模拟器覆盖不到的部分（画面、野 AI、波次、建筑被毁的连锁后果）才是推理不是验证。交付时明说哪些是"跑过"，哪些是"读起来没错"。
9. **蓝图用 `mlog.py gen` 产出**，不要手拼 base64；生成后 `ir`/`check` 再跑一遍确认逻辑没被截断。

## 模拟器：`tools/mlogsim.py`（真执行器）

静态分析回答"读起来对不对"，这个工具回答"跑起来是不是这样"。它直接驱动真 `LExecutor`，不是重写的 VM。

```bash
python tools/mlogsim.py my.mlog --steps 10                  # 指令级：只跑逻辑，不跑世界
python tools/mlogsim.py my.mlog --ticks 120 --update all    # tick 级：工厂/传送带/单位也动
python tools/mlogsim.py my.mlog --save scene.msav --ticks 120 \
  --units fortress:1 --trace out/t.csv --assert-last "chp < 3500"
```

- 默认 v160.7（`out/_server160.jar`）+ JRE21，可用 `MLOGSIM_JAR`/`MLOGSIM_JAVA` 换。空白世界默认 64×64；`--host` 用随机真实地图；`--save` 载存档（从我方核心旁自动找空地放入口处理器，`--base X,Y` 覆盖）。
- `--units name:count` 生成单位、`--unit-pos X,Y` 指定 tile 出生点；`--unit-ai all` 让场景里原有单位也按 AI 行动。单位落在实体格会在第一次 `update()` 被 `kill()`，所以有 `PREFLIGHT:` 预检——比"跑 1200 tick 发现单位没动"便宜得多；`--no-preflight` 只关单位存活检查。
- `--core-items ITEM:N,...` 给核心灌库存（空白世界会在处理器旁自动放一个 `core-shard`）；`ulocate`/`itemTake`/`itemDrop` 由此可断言。取放料要求同队、目标有 `items`、距离在 `45 world + 方块半宽`（约 6 格）内。
- `--links auto`（`.mlog` 默认）：裸 `.mlog` 没有链接表，模拟器会找出“读而不赋值”的链接名（`cell1`、`bank1`、`message1`、`dome1`），在处理器旁放同类方块并接上（同队、10 格内）；`.msch` 用自己的链接表；`--links off` 恢复原样（读 `null`）。
- `read`/`write` 的 `@this` 地址是**处理器变量**：`read v @this "slot"` 读、`write v @this "slot"` 写，名字是**字符串**；写一个程序里没声明过的名字是静默空操作（`check` 报 INFO `self-write-noop`），读未声明的名字得到 `null`（`self-read-undefined`）。数字下标 `read v @this 0` 取的是链接，不是变量。
- `--update all` 才跑 `Building.update()`（工厂、传送带、电力消费者）与 `LogicAI` 单位；`--power full|none` 把电力钉死；`--combat on`（`--ticks` 默认）按 `Logic.updateEntities()` 的顺序推进子弹物理/碰撞/伤害；`--weather rain` 可强制开局天气。
- `--trace FILE` 每 tick 一行逻辑单位轨迹（`unit,tick,ux,uy,uhp,range,tx,ty,dist,cx,cy,chp,bullets,shots`，tile 坐标）；`--assert EXPR` 对每行、`--assert-last EXPR` 只对末行求值，失败退 3。列名就是变量名。
- 特权语句（`weathersense/weatherset/setrule/message/cutscene/effect/fetch/sync/getblock/setblock/spawn/status`）只有 world processor 认；放进微处理器会被**静默删掉整行**。`--processor auto` 按语句自动选处理器。
- 特权**内置变量**（`@server`、`@client`、`@clientLocale`、`@clientUnit`、`@clientName`、`@clientTeam`、`@clientMobile`、`@clientMusicPlaying`）在普通处理器里不报错，而是被 `GlobalVars.get(name, false)` 换成 `null` 常量——分支永远不走。要在普通逻辑里判断玩家/客户端，换成 world processor 或游戏内可观测的数据。
- 能证明：`move/approach/within/@x/@y`、`ipt`、跨处理器读写、生产进度、天气时序、子弹命中掉血。不能证明：野 AI、波次、电力图、真实地形碰撞、建筑被毁的连锁；`draw` 会执行但没有画面。**真游戏行为必须由玩家验收**。

场景：`out/scenes/` 有 5 张现实存档（open / garded-line / maze / PVP / campaign）；`benches/run.py` 是 memory/processor/sensor/core 四张合成台（62 项断言）；`_snapshot.py` 出 PNG 快照。

注意：`mlogsim.py` 只在仓库根的 `tools/`（独立拷走的技能副本不含它，因为它要 Java + `out/_server160.jar`）；下面命令都假定当前目录是仓库根。

## 写逻辑之前：先查这四样

写逻辑缺的从来不是语法，是**目标**和**游戏事实**。这三条命令对应后者的三个大头：

```bash
python mlog.py find "wireless overdrive"     # 1. 别人怎么做的（先找参考，别自己发明）
python mlog.py unit flare                    # 2. 这个单位的速度/血量/能带多少货/会不会飞
python mlog.py block silicon-smelter         # 3. 这个方块吃什么、产什么、装多少、多少电
python mlog.py sensor heat                   # 4. 这个属性到底读的是什么（75 条，见下）
```

- `find` 扫描游戏存档目录里的全部蓝图（`MLOG_CORPUS` 可覆盖），按 `名字/描述/信息板/变量名/指令` 打分，打印 **分数拆解**——匹配得不对时能看出为什么不对。默认跳过 >5000 条语句的块与 >2MB 的文件（`BADAPPLE!!` 是 56 万条语句的动画，`Linux on mlogv32` 是 16MB），这些不是参考逻辑。首次 9 秒，之后读缓存 0.7 秒；`--rebuild` 强制重建。
- `unit` / `block` 的数据由 `tools/units_from_source.py` 与 `tools/blocks_from_source.py` 从源码抽出，`--check` 可校验是否与当前源码一致。**它们只列源码里写了的字段**，缺的字段是引擎默认值（`unit` 会标成 `(default X)`）——不要凭记忆补。

**“这个方块收不收 X”** 是最容易写错、错了还静默的一条——搬错了屏幕上什么都不会发生。规则来自源码
（`BuildingComp.acceptItem` = `block.consumesItem(item) && 容量`，而 `consumesItem` 是消费者填出来的布尔数组），所以：

| `accepts` | 含义 | 例子 |
|---|---|---|
| `any` | 只看容量，什么都收 | `core-shard`、`container` |
| `recipe` | **只收配方里的物品** | `silicon-smelter` 只收煤和沙 |
| `custom` | 收，但收不收/往哪走取决于配置 | `sorter`、`unloader`、`conveyor` |
| `none` | 一律不收 | `landing-pad`、`PayloadUnloader` |

反查：`mlog.py block --accepts coal` 列出所有收煤的方块（配方输入 + `any` + `custom`）。

### `sensor` 的 75 个属性

`sensor <结果> <目标> <属性>` 的第三个参数是**运行时对象**，也可以是变量。属性本身只有 75 个，
全部来自 `LAccess.java`，`mlog.py sensor` 一行一条、带一句人话说明：

```
python mlog.py sensor                # 全部 75 条
python mlog.py sensor heat           # 按名字或说明搜
python mlog.py sensor --settable     # 只有 control 也能写的（只有 3 条）
python mlog.py sensor --on unit      # 只有能从单位读的（37 条）
```

三条最容易踩的：

| 属性 | 陷阱 |
|---|---|
| `@heat` | 反应堆上是 0..1 的热量；**力墙投影上是"已损失的盾量"**，不是热 |
| `@size` | 方块是边长；**目标是字符串时返回 UTF-16 长度** |
| `@dead` | 单位死了返回 1，**单位是 null 时也返回 1** —— 不能当存在性判断 |

### 版本闸门：基线是 build 146

`instr_semantics.json` 里 46 条指令带 `min_build`：有明确出处的是 `format` 147、`select` 150、
`emod`/`ushr` 150、`bullet` 157、`getblock` 157、`effect`/`sync` 146；其余按 **v7 基线 146** 标，
理由写在 `BUILDS.md`。闸门判据是 `floor > 146`：**等于基线不报**（那个版本大家停了一年）。
七条（`printchar`/`unpackcolor`/`localeprint`/`query`/`makemarker`/`setmarker`/`clientdata`）
查不到确切入场版本，**留空而不猜** —— 没有出处就不写数字，是这个文件唯一的规矩。
注意 `custom` 只回答“可能收”，**“现在收不收”要看运行时状态**（sorter 的配置、router 是否空、焚化炉是否通电）。

## 单位表里有什么、没有什么

`mlog.py unit <名字>` 名称精确匹配优先（`unit oct` 不会再被 `spiroct` 挤掉），单条命中时多打三行：

| 字段 | 从哪来 | 写逻辑时怎么用 |
|---|---|---|
| `speed` / `health` / `armor` / `hitSize` | `UnitTypes.java` 里显式赋的值 | 算拦截时间、算能不能扛一轮 |
| `weapons[].damage/speed/lifetime/pierce/shots` | `new Weapon(...)` 块里的 `bullet = new XBulletType(...)` 及其 `{{ }}` | 估 DPS；`lifetime × speed` 决定射程上限 |
| `abilities[]` | `abilities.add(new XxxAbility(args))` | 这个单位会不会自己修、自己开盾、刷小怪 |
| `immune_to` | `immunities(StatusEffects...)` | **原版 39 个单位一条都没声明** —— 表里没写就是没声明，别猜 |

**三个读法上的坑**：
- `abilities.args` 是**源码原文**，会有 `60f * 8` 这种算式。别当数字读，它表达的是「8 秒」。
- 表里**没有**的字段 = 源码没写 = 引擎默认值（见 JSON 的 `defaults`），不是「零」。
- `itemCapacity (default -1)` 表示这个单位不能拿东西，不是容量为 1。

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

## 写逻辑之前：先看语料里的同类是怎么写的

`find` 回答"谁做过这件事",`style` 回答"他们写成了什么样子"。写逻辑前先跑一次,照着命名和形状写,生成的东西才不像外星人。

```
python mlog.py style 着陆 调度        # 多词不用引号
python mlog.py style 钍反 防爆 --limit 2
python mlog.py style 某逻辑 --code 20  # 连源码前 20 行一起看
```

每个命中会打印六项:

| 项 | 读它做什么 |
|---|---|
| `naming` | 作者的私有词汇表(已剔除 op 名/跳转条件/链接名/字面量) —— 新变量名照着这个风格起 |
| `flavour` | `dotted`(`i.item.min`)/ `underscored` / `Chinese` / `plain` 各几个 —— 选一种,别混 |
| `shape` | 能一眼认出的习惯:派发表、`select`、`wait` 节拍、命名跨处理器槽、内存格、`ubind`+`ucontrol`、消息板、`sensor @unit/@this` |
| `cost` | `--cost` 的结论行(最坏路径 / 微处理器每圈 tick) |
| `links` | 这类逻辑实际接了哪些方块 —— 顺手知道自己要接什么 |
| `opens` / `closes` | 开头两句和结尾两句(署名、`jump N always 0 false` 补位这类收尾习惯) |

同一个文件里多个处理器写同一份程序时只显示一次,并标 `(+N more block(s) in this file)`。
检索文本里包含**文件名**,因为语料文件名本身就是中文描述(`11-12双液体大超着陆合金气旋`)。

## 写逻辑:枚举、跳表还是内存格

mlog 里没有"按下标取内容物"的原语 —— `@copper` 是常量对象,不能写 `@[i]`。所以"遍历一个物品表"必须自己造表,而**造表的价格差不多就是摊开写**:

| 写法 | 每项成本 | 什么时候选它 |
|---|---|---|
| 枚举(摊开) | 2 行(`sensor` + 比较) | 列表固定、每项只比一个值、结果要一眼可复查 |
| 跳转表 `op add @counter @counter i` | 也是 2 行(`set it @x` + `jump`)+ 循环状态 | 列表长(>20),或每项还要顺带做好几件事 |
| 内存格存对象 | 1 块 + N 次 init `write` + 每圈 1 次 `read` | 列表要运行时可改 —— **但对象入格子只有 build 160+** |

三条必须先知道的事实:

- **`sensor` 的第三个参数是运行时对象,不是字面量**:`LExecutor.java:668-719` `Object sense = type.obj(); if(sense instanceof Content co){ to.setnum(se.sense(co)); }` ⇒ `sensor n core it`(it 里装 `@copper`)合法。**枚举不是语法逼出来的**,只是更少状态、更便宜。
- **平局要有确定的解**:枚举用严格比较保序(`jump s greaterThanEq n best_val`);循环版也得把这条规则显式写出来,省不掉。
- **列表交给生成器持有**:物品数组写在 `tools/gen_*.py` 里的一个 Python list,加一项 = 改一行 + `mlog.py gen` 重新生成。手改 mlog 里的清单一定会漂。

反面条件(这时别枚举):物品超过 20 种、列表要让别人在游戏里自己配、每项还要顺带做别的事。

## 指令预算:别猜,这是确定的

**一条语句 = 一条指令,`jump` 也是 1 条,和 `op` / `print` 没有区别。**

`runOnce()` 里 **`counter` 先自增再执行,不看指令类型**(`LExecutor.java:111-121`):

```java
instructions[(int)(counter.numval++)].run(this);   // ← 无条件 +1
```

⇒ **钱花在"循环圈数 × 循环体语句数"上,不花在 `jump` 这个字上。**
⇒ 用 `jump` 跳过一段确实省下被跳过那些行,但**跳转自己仍然收 1 条**。

**每 tick 的额度**(`LogicBlock.java:564-578`,`ipt = instructionsPerTick`):

| 处理器 | ipt | 每秒 |
|---|---|---|
| 微型 micro-processor | **2** | 120 |
| 逻辑 logic-processor | **8** | 480 |
| 超级 hyper-processor | **25** | 1500 |
| 世界 world-processor | **8**(`maxInstructionsPerTick = 1000`) | 480 |

**两条容易漏的**:

- **只有 `wait` / `stop` / `printflush @wait` 会 `yield`**,提前结束这一 tick 的额度;**`jump 0 always` 没有这个机制**,会在一个 tick 内把额度烧光
- 但 `wait` 期间处理器是**静止**的,不干别的活;要边等边算(看单位、轮询目标、多任务)就用 `op add cfg.timer @time 500` + `jump ... greaterThan @time cfg.timer`,别用 `wait` 空转。
- `setrate` 是唯一能改 ipt 的指令,上限是 `maxInstructionsPerTick`(逻辑卡 **40**,比默认 8 大 5 倍);`@ipt` 立即变新值,但**本 tick 的循环边界已经固定**,下个 tick 才生效

**所以改循环之前先跑 `check --cost`。** 算完的秒数就是单位从"看到"到"反应"的延迟。

## ⚠️ 最容易搞错的一件事:方块坐标是「中心格」

schematic 里 Stile 存的是方块的**中心格**,不是左上角。**已双重验证**:

- 源码:`Tile.setBlock()` 用 `int offset = -(block.size - 1) / 2` 铺开多格方块 → `(x,y)` 是中间那格
- 实证:624 个真实蓝图里,按"角"解释会产生 **11 处方块重叠**,按"中心"解释 **0 处**

所以一个 3×3 方块,要让它的成品占据 `(3,1)–(5,3)`,**中心要写 `(4,2)`**。

链接的 `name@dx,dy` 也要对到**方块覆盖范围内的任意格**(工具会按 footprint 校验并提示)。

## 生成蓝图时的作者标签

本仓库用 `mschgen` 生成的蓝图,`labels` 一律写 `["[blue]DeepSeek"]`
(用户标签体系里的"作品来源"类),描述末尾带 `逻辑 by [#8abcd1]DeepSeek[]`。

## 自动打标签

蓝图标签(颜色=维度、私有区图标=值身份)是手打的,但**其中 24 个值可以从内容推出来**,
留出集精确率 ≥70%:

```bash
```

`数量` / `品质` / `系列` / `无线` / `火控` 这类量不出精确率的值不会出现在建议里 ——
它们要么是主观判断,要么同一份蓝图三种都沾。写回只重写 tags 段,其余字节原样搬运。

## 常用调用

> 全部子命令的一行说明见 `.dsh/skills/mlog-agentskill/SKILL.md` 的「工具索引」。

```bash
### 解析:看逻辑源码和结构
python tools/mlog.py parse "schematics/某逻辑.msch"

### 检查:生成前必做
python tools/mlog.py check logic.mlog
python tools/mlog.py check logic.mlog --cost
python tools/mlog.py check --msch out.msch

`check` 的 INFO 不是错误：`@server` / `@client*` 是特权内置量，micro/logic/hyper 里读到的是 `null` 常量，只有 world processor 有真值；这条 INFO 是在问“这段逻辑到底跑在哪个方块上”。

### 成本分析:死代码 + 最坏多少条指令 + 折合几秒
python tools/mlog.py check --msch out.msch --cost

### 死存储:赋值了但整个程序(含跨周期)从未读取
python tools/mlog.py ir logic.mlog
python tools/mlog.py ir --msch out.msch
python tools/mlog.py ir --all logic.mlog    # 连语法强制的输出槽一起列

### 值域分析:常量分支 + 可证 null
python tools/mlog.py values logic.mlog
python tools/mlog.py values --msch blueprints/*.msch
python tools/mlog.py values logic.mlog --trace r   # 逐次打印 r 的抽象值

### 打包配置:字段布局 + 低位字段能装几个 id(能直接指认容量 bug)
python tools/mlog.py pack logic.mlog
python tools/mlog.py pack --msch out.msch

### 生成:只放处理器(链接目标需自己摆)
python tools/mlog.py gen logic.mlog --name "我的逻辑" --link dome1@3,1

### 生成:连目标方块一起放(--with-block 坐标是【中心格】)
python tools/mlog.py gen logic.mlog --name "某逻辑" \
    --link dome1@3,1 --with-block overdrive-dome@4,2=248 \
    --out paste.txt --binary out.msch

### 查方块 ID 和尺寸
python tools/mlog.py id overdrive

### 查指令格式
python tools/mlog.py cmd ulocate

### 查一条指令到底哪个参数是输出(哪个是枚举、哪个会被读)
python tools/mlog.py explain ulocate
python tools/mlog.py explain ulocate ore     # 只看 ore 分支
python tools/mlog.py explain select
python tools/mlog.py explain op add
```

**蓝图码永远由 `mlog.py gen` 产出,不要自己拼 base64。** 手拼过一次,前缀写成 `"bXNjaAF4n" + b64[8:]`(9 字符前缀却只砍 8 个),长度变成 `4k+1`,游戏直接报 `Length of Base64 encoded input string is not a multiple of 4.` —— 文件是好的,坏的是拼字符串那一步。

两条容易误会的细节:

- 前缀**不固定**:游戏自己写 `78 9c`(默认 zlib),`mschgen` 用 `78 da`(最高压缩)⇒ 第 11 个字符会不同(`bXNjaAF4**2**mPg` vs `bXNjaAF4**n**mPg`)。**两种都合法**,只认解码后的 `msch` 魔数。
- `--with-block` / `--link` 的坐标都是**相对处理器的中心格**,和方块的绝对坐标不是一回事。

## 成本分析(`--cost`)看什么

```
statements      : 159                     ← 语句数,>1000 会被静默截断
reachability    : all statements reachable ← 或列出永远跑不到的语句
opcodes         : op×62, jump×40, ...      ← 指令构成
loop heads      : L28(×80), L52(×80)       ← 循环起始行 + 推定圈数
worst-case path : ~2001 instructions       ← 一次完整决策最坏多少条
    ⚠ over LExecutor.maxInstructions (1000/tick): one cycle needs 2.0 ticks
    micro-processor  @ipt=2    1000 ticks (  16.7 s) per cycle
  ⏸ blocking      : 2 wait statement(s), ~240 ticks (4.0 s) blocked per cycle
      L3: wait -> ~120 ticks
```

**怎么用这三个数**:

| 看什么 | 说明什么 |
|---|---|
| **UNREACHABLE 非空** | 有死代码。多半是 `end` 之后写了东西,或跳转目标写错 |
| **worst-case > 1000** | 一个决策周期跑不完一 tick,单位响应会有对应延迟 |
| **@ipt 换算的秒数** | 直接回答"这套逻辑跟得上战况吗" |
| **⏸ blocking 那行** | `wait` 一条 ipt 都不烧,但周期时间几乎全在这里 |

**注意**:

- 循环圈数靠**守卫里的常量**推定(`jump 37 greaterThanEq index 80`)。看不到常量的循环按一圈算并给出警告
- 结果是**上界**(互斥分支不剪枝),意思是"最坏能到多少",不是"平时多少"
- 回到第 0 行的回边 = 主循环,只算**一圈**(mlog 本来就每 tick 重跑一遍)
- **`wait` 单独算**:参数是**秒**(60 tick = 1 秒),`wait 0` 不阻塞、只是"每 tick 跑一遍";
  `blocked` 已乘上包含它的循环圈数并加进三种处理器的 tick 数里。参数不是字面量时报 `UNBOUNDED`,不编数字
- 看到 `>=1001` 这种写法,意思是**循环体自己就把 1000 的预算填满了**,真实总量更大、算不出来;
  平静的 `~N` 才是量出来的

## `ir` 看什么、不看什么

四层分级,默认只打第一层:

| 层 | 含义 | 该不该管 |
|---|---|---|
| `reported` | 值被覆盖前没人读(`overwritten`)/ 从没人读但写了不止一次(`stale-write`) | **是 bug,去看** |
| `slot` | `ulocate`/`ucontrol`/`radar`/`sensor` 的多输出槽没读,且**只写一次** | 语法强制,不是错 |
| `declaration` | `set x 字面量` 且没人读 | 声明式初始化；**也可能是给使用者留的配置**（`set count 0`、`set limit 40`）——有 `cfg.` 命名或文件头注释就别删 |
| `annotation` | 变量名是纯标点(`//`) | mlog 没有行尾注释(只有 `#`),作者拿它当注释 |

`stale-write` 是为「强制输出槽写两次」加的一层:写**一次**且没人读,可能只是语法逼你起个名字(`slot`,降级隐藏);但同一个槽**写两次**且从没人读,第一次写可证被丢弃 —— 那是真 bug。实例:`某蓝图.msch` 的 micro-processor @(16,8) 里 `found` 在 `L6` 与 `L61` 各被 `ulocate` 写一次、全程序无读,改动前它被 `slot` 层藏住(`dead-store 0(+3 hidden)`),改动后才报出来。

**校准(全语料 617 文件 / 2409 块,已排除模拟器蓝图)**:80.9% 的处理器**一条都不报**,p50=0、p90=1;均值 0.829/块是被约 20 个代码生成式蓝图拉高的。抽样 28 个站点人工核对,**全部为真**。

**它不能证明你的逻辑是对的**:
- 不跨处理器(说明:`read`/`write` 可以按**名字**访问另一个处理器的变量(必須提前聲明、寫給未聲明的槽是靜默空操作)。老蓝图库里看不到这种写法,所以对老库「这个变量从未赋值」的判断是可靠的;新库里它是一条合法的"别处赋值"路径 —— 报 A 层之前先确认两份逻辑是不是同一代产物。) —— 别的处理器用 `read x cell1 "名字"` 读它,这里看不见(实测全语料 0 例,但报了 `never-read` 仍要自己确认)
- 只判"值有没有人用",不判"值算得对不对"(`op add dx dy dx` 想算距离却写加法,`ir` 不报)

## `values` 看什么、不看什么

`mlog.py values` 跑的是**抽象值不动点**:给每个变量在每个位置算一个区间/常量,然后回答两个 token 流回答不了的问题。

```
resolved branches: 1
  L3   always taken  jump 5 strictEqual r null    (cond = 1)
provably null: L3 r is null
```

| 输出 | 含义 | 该怎么用 |
|---|---|---|
| `always taken` / `never taken` | 条件两边都是常量,分支恒定 | 要么写错了,要么是刻意的死分支 —— 去看 |
| `... is null` | 这条语句执行时该变量必定是 null | `===` 能区分,`==` 不能(见下) |
| `?` | 不知道(外部输入、`rand`/`noise`) | 正常,别当 bug |

**必须先知道的两条语言事实**:

- **未赋值的变量是数字 `0`,不是 null**(`new LVar` 的 `numval = 0`)。所以 **`equal x null` ⇔ `x.num() == 0`**,对没赋过值的 `x` 恒真;**只有 `strictEqual`(`===`)区分 null 和 0**(`ConditionOp.java:31-40`:两边都是对象才比对象,否则比数字)。看到 `jump ... equal var null`,先怀疑它想写的是 `===`。
- **NaN / ±Infinity 会被静默转成 null**(`LVar.setnum` 的 `invalid()` 检查)。这正是按位剥离循环能退出的原因:`op logn x 2` 在 `x=0` 时得 `-Infinity` → null → `=== null` 成立。

**校准(全语料 2396 块,排除模拟器,39 ms/块)**:4.1% 的块有信号,平均 0.120 条分支 / 0.060 条可证 null;未收敛 0。抽样人工核对,结论都为真。

**它不能证明什么**:
- 外部输入一律 `⊤` —— `sensor`/`getlink`/`ulocate` 拿到的值都算"不知道",所以**只对纯计算链有效**
- 同一变量连改 3 轮就丢精度到 `⊤`(widen),深循环里会变回 `?`
- 不跨处理器,也不判"值算得对不对"(那是人的事)

## `values` 的跨处理器模式

只有 `--msch` 会给它跨处理器的知识：先跑一遍 `cross` 拿到每个槽的值，再带着这张表重跑（**只迭代一次**，不做不动点）。单个 `.mlog` 没有同伴，`read` 仍是 ⊤。蓝图不完整时（对方处理器没一起存）报 null 可能只是没存下来。

| **语料里的写法** —— 命名/形状/周期成本 | `mlog.py style <关键词...>` |

## `cross` 只看跨处理器,不看记忆格

`read`/`write` 有两种完全不同的用法,别混:

- `read x cell1 "slot"` —— **记忆格**,引号里是**地址变量名**。极常见(我的库 82 份里有它)。
- `read x processor1 "name"` —— **另一个处理器的变量**,引号里是那个处理器里的**变量名**。
  少见:我的库 625 份只有 **9 份**真的指向处理器,彩末包 926 份只有 13 份。

可读的那个槽就是**目标自己的变量**(所以 `set` 就够,`write` 不是必须的),这也是
「必须先在那边声明」的原因。`cross` 把 join(目标自己的所有赋值, 所有外部 `write`)
算出来,分四类报:`never assigned` / `always null` / `constant` / `written, never read`。

自链接(`processor1` 偏移 0,0)是合法写法,读的是自己的变量。

**版本**:按名字读写另一个处理器 / message 方块是 **v7(build 146)** 才有的;v6 的 `read`
只能拿数字下标访问记忆格 ⇒ 一份用它读写处理器的蓝图跑不到 v6 上(`cross` 会带一行
`note : ... v7 (build 146) feature` 提示)。

**报告基线是 build 146**（v7.0 首个正式版）：基线里就有的语句不报，只有更新的才报。判据是 `floor > 146`，不是 `>= 147`。

## `pack` 看什么、不看什么

`mlog.py pack` 认的是**把多个字段塞进一个数字**的惯用法(`data = status*1e8 + outputID*1e6 + inputMask`),然后算**低位字段能装多少个 id**。

```
    `data`  (first seen L2)
      1e8  ->  status   (= data / 1e8)   at L2
      1e6  ->  outputID (= data / 1e6)   at L3
      1e6  ->  mask     (= data % 1e6)   at L4
      low field `1e6` holds 0..999999  =>  20 usable bit positions (ids 0..19)
      !! 22 items exist but only 20 fit: ids 20..21 overflow into the next field
         (raise the separator, e.g. 1e6 -> 1e7)
      note: `outputID` also contains 100x `status`; a correct decode must first
            assert `status == 0`
```

| 输出 | 含义 |
|---|---|
| `1e8 -> status` | 这一层剥出来的是 `status` |
| `N usable bit positions` | 低位字段能表示 `0..10^N-1`,`(10**N-1).bit_length()` 就是能装几个 id |
| `!! ... only 20 fit` | **真 bug**:原版有 22 个物品,`fissile-matter`(20)与 `dormant-cyst`(21)放不下 |
| `note: ... must first assert X == 0` | `op idiv` 不掩高位,`idiv` 出来的值里还含着更高位 ⇒ 必须先断言高位为 0 |
| `ok: ... subtract-mask` | 先 `op mul hi 1eN` 再 `op sub` 减掉高位 —— **解码正确,不报警** |

**它是全套工具里唯一能直接给出"这段代码有 bug"结论的地方**,代价是出现率极低:**全语料 2420 块里只有 3 块(0.1%)** 用这个惯用法。所以它**不是 linter**:拿它扫整个语料几乎什么都看不到,但一旦命中,给出的是具体容量数字,不是"这里可能有问题"。

**边界**:只认 `op idiv|mod <dst> <src> 10**exp`,且同一个 `src` 上要**至少两个不同指数**才算一个 pack site;不重建表达式;`10^3` 以下不算分隔;掩码检测是全程序文本匹配(不做数据流),别处同形的 `mul`+`sub` 可能让真漏判静默通过。

## 「未定义变量」要先分五层,再决定改不改

静态检查报「`X` is read here but is never assigned anywhere」时,**先别改**。mlog 圈有一整套只用变量列表承载的写法,靠规范测不出来。926 份蓝图包的实测分布(分层把 A 从 883 条降到 77 条):

| 层 | 含义 | 条数 | 改不改 |
|---|---|---:|---|
| **A 真错** | 名字被读的地方,值真的改变行为 | 77 | **要改** |
| B 恒真守卫 | `jump` 两侧都是常量 ⇒ 分支固定 | 55 | 一般不用 |
| C 无效参数 | 名字落在指令**读不到**的参数位上 | 944 | 不用 |
| D 死引用 | 形如链接名,但这块处理器没有这个链接 | 788 | **要改**(静默失效) |
| E 署名 | 只为出现在编辑器变量列表里 | 5540 | 不用 |

- **E 署名**:编辑器变量列表会显示程序用到的所有变量,写个自己的名字当变量就是署名 —— `print by:NOSB(hghg`、`set Madeby mineqwwe`、`jump 21 equal colour ender`、`control config Carrot 0914 0 0 0`。判 **INFO**。
- **C 无效参数**:语句长度 > 指令真正读的位数时,多出来的 token 是惰性的。`control` 只有三个有效位(类型/目标/p1,p2–p4 被各方块忽略);`ucontrol` 按 `semantic_uses` 算,`flag`/`payTake` 只有一个语义参数;一元 `op` 的第三位永远丢掉(`op rand g 255 b` 的 `b`)。
- **D 死引用**:`scatter1` 看着是有效链接,但处理器的链接表里没有它 —— `LExecutor` 的 `validLink(b)` 直接挡掉,`control shootp scatter1` 一发不发,**不报错也不崩溃**。只有 `.msch` 能查(`.mlog` 没有链接表)。
- **`true`/`false` 是常量,不是普通变量**:`GlobalVars.java:54-55` 用 `putEntry` 注册成 1 / 0,`LAssembler.var()` 先查 `logicVars` 才轮到 `putVar` ⇒ `jump T equal X true` 就是 `X == 1`。**我曾只看 `var()` 就断定它俩是未赋值变量,凭空造出 653 条假警告** —— 判内建要查"注册了什么",不是查"解析函数怎么处理"。

`set // 装载电池组`(变量名纯标点)也在这套习惯里:mlog 只有 `#` 起注释(`LParser.java:98-99`),想让注释在变量列表可见就这么写 —— 归 `annotation` 层或整行跳过。

`noop` 单列一条:**判 ERR**。它是 `LStatements.InvalidStatement`(`LStatements.java:48-59`),`build()` 返回空跑的 `NoopI` —— 游戏把**解析不了的语句**替换成它。所以看到 `noop` 等于「这里原本有一条语句,没了」:最常见的原因是**高版本写的逻辑在低版本打开**,旧解析器不认识的语句被丢掉。这种程序**基本就死了** —— 丢的正是干活的那条,后面的 `jump` 还会照旧指向错位置。(极少数只是空行占位,那是特例;按错误报,让人去看一眼。)

真正要改的 A 层:`op mod n n padNeedCount`(模数 0 ⇒ null)、`ubind u` 而 `u` 从未赋值、`control config unloader1 mmm 0 0 0`、`flase` 拼错落在 `ulocate` 的 enemy 位。

**注意惰性位与内部位的区别**:参数槽**之外**的 token 不读(`op rand g 255 b` 的 `b`、`jump T always x false` 的 `x`);但署名写进参数槽**内部**(`control enabled reactor enable 0 by bicker` 的 `by`/`bicker`)游戏确实会读它们 —— 只是因为 `control` 的 p2–p4 对方块无意义，所以仍然判 C。

## 死循环怎么查

`check` 只报能证明的那种:回边永远成立、而且环内没有任何语句能让它变假。

- **`@this` 守卫**:`@this` 只能被 `ubind` 认领(`LExecutor.java:325`/`:329`,全树仅此两处写 `controller`)。于是
  `jump loop strictEqual ctrl @this` + 体内 `ubind @flare` ⇒ 第一遍就恒真 ⇒ **ERR,其后全是死代码**;
  `jump loop notEqual ctrl @this` + 同一句 `ubind` ⇒ 第一遍就恒假 ⇒ 循环一遍就结束,这是标准写法,**不报**。
- **等外部状态的自旋**(`jump loop equal on 0`,`on` 来自 `read cell1`)不报:真实语料每块 0.33 条,报了只会淹没结论。
- 模拟也替代不了:复现上一条要先构造"单位已被本处理器认领"的场面,喂不到场景时模拟器会说一切正常。

## 病毒逻辑（自我复制）

```powershell
python mlog.py check someone.msch --msch      # 命中会打 [INFO] virus-logic
```

判据只有一行：`ucontrol build <x> <y> <块> <朝向> @this` —— 最后一个参数是新方块的 config，
传 `@this` 就是「造一个跑我这份程序的方块」，于是它复制自己、复制出的再复制。圈内叫
**病毒逻辑**。`@this` 经变量中转（`set cfg @this`）也算。

实测：1,421 个存档里 9,151 个处理器是病毒，但**只来自 2 份不同的程序**（`556.msav` 6,616 份
副本、`538.msav` 1,432 份）。看到一张图里几千个处理器，先怀疑这个，别急着叫它"逻辑计算机"。

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
（个人语料扫描（未随公开版发布））：1421 个存档、103,787 个处理器，去重后只有
**4,366 份不同的程序**（95.8% 是同一段代码的副本）——所以报告里所有比率的分母
都是「不同的程序」，不是「处理器」。

### 存档里的程序没有名字

`mlog` 没有名字字段（只有蓝图有 `name`/`description`）；存档里唯一的名字是地图名。判用途靠三个信号：
**链接名**（默认是方块名+序号）、**指令直方图**（`draw`=显示 / `ubind`=单位 / `control config`=物流 / `setrule`=世界规则）、
**代码里的字符串**（`print` 出去给人看的那一两段字）。按这三样分桶的现成结果在 `out/saves_programs.md`。

## 批量跑语料(并行)

```powershell
python mindustry-blueprint\tools\parallel.py --items 1421   # 先看它会开几个 worker、为什么
```

`parallel.py` 自己算 worker 数：核数、可用内存、**最大文件**三个上限取最小。重文件
（≥1 MB）单独一段、用更少的 worker —— 一个 4.5 MB 的存档里有 6,600 个处理器，按平均值
分 worker 会让几个这样的文件同时把内存吃干。想调就 `--workers N` 或 `--serial`。

## 钍反保护:三条事实

| 事实 | 数字 | 出处 |
|---|---|---|
| 有冷却液时 `@heat` 恒为 0 | 一 tick 清零,稳态 1.2 液/秒 | `NuclearReactor.java:95-125` |
| `control enabled 0` 不是灭火 | 停了还要 1200 tick(20 s)才从 0.999 降到 0 | 同上,ambient 冷却 |
| 满料 100 tick 爆炸 | 发热 0.01/tick,`@heat >= 0.999` 即 `kill()` | 同上 |
| 链接名不能证明类型 | `reactor1` 可能是钍反或冲反,而 `@heat` 在两台上是相反的意思;要 `sensor x reactor1 @type` 证明类型才敢报 WARN,否则只报 INFO 提问 | 2026-10-18 用户实测纠正 |
| 冲反的 `@heat` 是 warmup | 出力 = `warmup^5`:卡在 0.5 只有 3.1%、0.9 有 59%、0.99 有 95%;满载要 ~6908 tick(115 s),**永远不会因为热而爆炸** | `ImpactReactor.java:117-120` |

保护逻辑的正确性不看阈值看**检查间隔**:满料 `(0.999 - 阈值)/0.01` tick 内必须再看一眼,
间隔 = 循环体语句数 ÷ 处理器 ipt。`mlog.py check` 会报 `reactor guard is too slow`。

## 语义是谁说的：第二实现交叉验证

本仓库的每条"语言事实"都来自读 `LExecutor.java`。读源码会读错，所以关键几条
另外用 [`cardillan/mindcode`](https://github.com/cardillan/mindcode) 的处理器模拟器
复核过一遍（八条探针，六条一致、一条不支持、一条蓝图级新增）。

| 结论 | 状态 |
|---|---|
| `equal <未赋值> null` 恒真 · `logn(0,2)`→null · `1/0`→null · `sensor @unit @dead`→1 · `print <未声明>`→`null` · 记忆格未写→0 | **双实现确认** |
| `read`/`write` 只认对方**已声明**的变量，`write` 到未声明名字不建槽 | **双实现确认**（蓝图级探针 `A=7 B=null C=null`） |
| `ubind` 后 `@controller == @this` | 真执行器实测（v159.3 / v160.7，`mlogsim`；mindcode 模拟器不支持 `ubind`） |

复跑方法与探针文件见 `EMULATOR-CROSSCHECK.md`（需要 JDK 22 与 `mindcode.jar`）。平时不需要 mindcode：`tools/mlogsim.py` 本身就是真执行器，`out/probes/p1..p8` 已在 v159.3 与 v160.7 上复跑通过；`tests/run_tests.py` 是 24 条 golden，不依赖 Java。

## 独立副本

同一套工具已经打包成独立的 mlog-agentskill 技能（.dsh/skills/mlog-agentskill/），目录自带全部模块与数据，可整体拷走。一审一整套分析用 mlogagent.py report <file>；改完模块后用 python tools/sync_mlogagent.py 刷新那份副本（--check 只比对）。

## 改完分析器先跑測試

```bash
python tests/run_tests.py          # 12 條 golden digest，任何結論變化都會失敗
python tests/run_tests.py -v       # 逐條列出
python tests/run_tests.py --write  # 改了就有意識地改期望值——然後讀 diff
```

digest 是**去措辭的結論**（`(severity, line)` 對、語句數、分支判定、容量位數…），
所以文案可以隨便改，結論一變就紅。`mlog.py selftest` 只證明解析器不丟東西
（429/429 round-trip），這五個分析器的正確性靠這套兜住。

## 环境要求（分享给别人之前先看这段）

**只需要 Python 3.10+ 和标准库。** 开发机是 3.12.14；全部脚本只用 `argparse base64 collections dataclasses glob hashlib json math os pathlib re shutil struct sys textwrap urllib zlib` —— 没有 numpy、没有 pandas、没有任何要 `pip install` 的东西。

两个可以独立拿走的东西：

| 拿什么 | 大小 | 能不能单独用 |
|---|---|---|
| `.dsh/skills/mlog-agentskill/` | 自带 16 个文件 + `MANIFEST.sha256` | **能**。拷到任何地方 `python tools/mlogagent.py report x.msch`，`info --verify` 自校验 |
| `mindustry-blueprint/` | 工具 + 数据 + 文档 | 能，但下面两条路径要按自己机器改 |

### 两条路径

- **游戏蓝图目录**：默认 `%APPDATA%\Mindustry\schematics`（即 `~/AppData/Roaming/Mindustry/schematics`）。换地方就设环境变量 `MLOG_CORPUS`，或对 `find` 传 `--corpus`。
  用到它的只有 `selftest` / `find` / `corpus` 类脚本；`parse` `check` `ir` `values` `pack` `cross` `explain` `unit` `block` `item` `gen` **都不需要游戏目录**。
- **Mindustry 源码目录**：`./Mindustry-Source`（git 忽略，约 8 MB）。只有"从源码重新生成数据表"的脚本要它：`block_ids_from_source.py`、`block_sizes.py`、`items_from_source.py`、`units_from_source.py`、`blocks_from_source.py`、`check_ops.py`。
  **日常使用完全不需要** —— 八张表都已随包提供（`block_ids.json` / `block_sizes.json` / `cmd_index.json` / `item_ids.json` / `instr_semantics.json` / `unit_attrs.json` / `block_attrs.json` / `label_rules.json`）。

### 版本与平台

- 数据表取自 **Mindustry v159.3（git `5811844`）**。游戏更新后要刷新表，就重新 clone 源码再跑上面那几个生成脚本（每个脚本头注释写了它读哪个文件）。
- **路径默认值是按 Windows 写的**。Linux/macOS 上把 `MLOG_CORPUS` 指到 `~/.local/share/Mindustry/schematics` 或 `~/Library/Application Support/Mindustry/schematics` 即可。
- **控制台要 UTF-8**：`chcp 65001`（或设 `PYTHONIOENCODING=utf-8`）。否则中文变量名和图标字形会显示成乱码 —— 那是终端在按 GBK 解码，**文件本身没问题**。
- **不需要**：Java、Mindustry 本体、网络。唯一联网的脚本是 `fetch_wiki_ids.py`（一次性抓 wiki 的方块 ID 表，结果已在仓库里）。

### 让技能在「所有项目」里生效

DSH 没有"单个技能的作用范围"开关,作用域**就是它所在的目录**:

| 位置 | 谁看得见 |
|---|---|
| `<仓库>/.dsh/skills/mlog-agentskill/` | 只有这个仓库(本仓库既是源码,也是这种用法) |
| `$DSH_HOME/skills/mlog-agentskill/` | **所有项目**。本机 `C:/Users/<you>/.dsh/skills` 是指向 `.dsh-pack/skills/default` 的 junction,所以写进去等于装成内置技能 |

一条命令装到用户级,装完逐文件校验:

```bash
python tools/sync_mlogagent.py --global          # 装 / 刷新
python tools/sync_mlogagent.py --check --global  # 只核对,不同步就 exit 1
```

它写的是仓库外目录,需要文件系统权限;全局副本与仓库副本的一致性由这个脚本负责,别手工复制。

### 规则与逐条审计（`rules/` + `review.py`）

一条命令跑完整个审计：

```bash
python tools/review.py run --pages 2      # 抓 30 张图 -> 分析 -> 写 out/audit_review.md
# 在编辑器里给每条的 `判定:` 后面填 ok / bad / unsure / skip，可加 `备注:`
python tools/review.py ingest && python tools/review.py stats
```

- `run` = `fetch` + `build` + `md`；`--pages 0` 只分析本地已有图，`--serial` 给慢机器。
- **重写清单前会先把上一份 md 里填过的判定读回来**，所以可以反复 `run`/`md`，判定不会丢。
- 只有 `build`（重新扫描）会换行 id；这时候先 `ingest` 再 `build`，否则旧判定对不上新 id。


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
python tools/review.py md --unjudged         # out/audit_review.md：源码 + `判定:` 空位，在编辑器里逐条判
python tools/review.py ingest                # 把 md 里填的 ok/bad/unsure/skip 读回 out/verdicts.csv

**判的载体是 markdown，不是游戏里。** `md` 把每条发现摊成：出处、处理器自己的链接名、
带语句序号的源码（`>>>>` 标出被指那一条）、以及一行空的 `判定:`。要判「链接名指错了」
不需要打开地图 —— 链接名就列在那一条里；要判「这行是不是白算」也不需要，源码就在下面。
填完 `ingest` 读回来，`stats` 按规则算准确率。`--window N` 控制每条上下各给几行。
```

- **kind**：`semantics`（游戏就是这样，禁止自动降级）/ `heuristic`（统计，可降级）/ `negative`（看着像错其实对，用来挡住想写的规则）。
- **单向棘轮**：降级（WARN→INFO）可以让机器提议，升级永远要人点头。
- 判词只有四个：`ok` / `bad` / `unsure` / `skip`。`bad` 攒够了就说明规则该删或该收窄。


## 参考数据

| 文件 | 内容 |
|---|---|
| `tools/wiki_block_ids.json` | 422 个原版方块 → content ID |
| `tools/block_sizes.json` | 446 个方块尺寸(从源码推导) |
| `tools/cmd_index.json` | 86 条 mlog 指令的格式/参数/注意事项 |
| [REFERENCE.md](REFERENCE.md) | 完整知识库:编号体系、机制、坑、被推翻的旧结论 |
| [PATTERNS.md](PATTERNS.md) | 逻辑模式库 + 蓝图工程分析 |

## 关键事实速查

- **蓝图里存的是 mlog 明文源码**,不需要反编译
- **content ID 是"构造顺序号"**,原版方块先构造、mod 后追加 ⇒ **mod 不会让原版方块 ID 偏移**
- **蓝图不存 content ID**,游戏加载时**按方块名解析** ⇒ 放原版方块只要名字对
- **`@dead` 对 `null` 目标也返回 1** ⇒ 兼作"单位不存在"判断
- **`sensor` 的 null 会传染** ⇒ 目标为 null 时所有属性都返回 null
- **`sensor` 的第三参可以是变量**(装 content 对象即可) ⇒ `sensor n core it` 合法,但 mlog **没有按序号取内容物的原语**
- **对象存进内存格只有 build 160+ 支持** ⇒ 老版本上 `write @copper cell1 0` 实际写的是 1
- **链接名 = 内部名按 `-` 切分取最后一段 + 序号** ⇒ `overdrive-dome` → `dome1`
- **每 tick 有效预算 = `@ipt × @timescale`** ⇒ 只看 `@ipt` 会把调速后的产能算低一倍(`sensor $ @this @timescale` 取倍率)
- **写 `@counter` 生效的是"下一次"位置** ⇒ `op add @counter @counter n` 之后的入口在 **n+1 行**
- **`@counter` 越界是未定义行为**(N<0 / N≥行数 / 非整数) ⇒ 派发表必须自己钳制,别指望游戏兜底
- **解析失败的语句整行变 `noop`**(编辑器显示 Invalid),不是"忽略某个参数" ⇒ 是整行失效,不是局部失效
- **`jump` 到不存在的标签 = 跳转 -1 = 什么也不做**(`LParser` 的 `get(location, -1)` + `JumpI` 的 `if(address != -1)`) ⇒ `check` 报 `no-target-jump`,别把它当"死代码"
- **逻辑上限 1000 行;`1e4` 合法、`1.2e3` 不合法;变量名除空白与 `"` `#` `;` 外几乎任意** ⇒ 生成器按 C 标识符规则写会切错名字、写出游戏解析不了的数字
- **`idiv` 是向下取整、`mod` 是截断取余、`emod` 是 floor-mod** ⇒ 三者不能互换;恒等式 `a == (a idiv b) * b + (a emod b)` 只在 emod 下成立(`LogicOp.java:12-14`)
- **`emod` 与 `ushr` 是 v150 新增** ⇒ 版本闸门必须看**算子名**,`op emod` 报 `>=150` 而不是基线 146
- **任何 `ucontrol` 命令(除 `unbind`/`within`)都会把单位认领给本处理器** ⇒ `sensor c @unit @controller` 之后紧跟 `ucontrol move …`,`c` 立刻等于 `@this`;想只测距不认领,用 `op len` 手算
- **编辑器显示名与文本名错位**:`not` 显示成 `flip`、`notEqual` 显示成 `not`(`LogicOp.java:32`)⇒ 照编辑器念出来的名字写进 mlog 会变成另一个算子
- **`@counter` 的语义是「当前行之后将要执行的行号」** ⇒ 函数返回地址用 `op add ret @counter 1`,而派发表写 `op add @counter @counter n` 之后入口在 n+1 行
- **控制命令间隔超过 10 秒就丢控制状态** ⇒ 长循环里每 10 秒至少发一条 `ucontrol`
- **`ucontrol move x y` 是 4 个字段** —— 语句对象有 6 个槽、`LExecutor` 无条件转换 `p1..p3`，但 `move` 只读 `x,y`（`approach` 才读第三个当半径），`pathfind` 同理；别照编辑器补的 `0 0 0` 数参数
- **一元算子多写一个操作数不算错** —— `op floor a b`、`op sin y angle 90` 多出的 token 被 `LParser` 丢弃，运行时无影响，只算 INFO；但 `op sin` 吃弧度，写 `90` 往往说明作者以为是角度
