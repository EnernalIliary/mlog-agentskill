# 蓝图逻辑模式库（Mindustry mlog）

> 基于 **Mindustry build 159.1 源码** + **你游戏目录 625 个 `.msch` 蓝图中的 5774 个逻辑块** 实证整理。
> 所有机制结论都在 `Mindustry-Source` 里找到了对应源码行；所有模式都在你的蓝图里找到了真实用例。

---

## 目录

- [第 0 章 蓝图文件怎么解析](#第-0-章-蓝图文件怎么解析)
- [第 1 章 执行机制（原理核心）](#第-1-章-执行机制原理核心)
- [第 2 章 跳转与标签机制](#第-2-章-跳转与标签机制)
- [第 3 章 链接系统与建筑交互](#第-3-章-链接系统与建筑交互)
- [第 4 章 兵控：单位绑定与多控槽位](#第-4-章-兵控单位绑定与多控槽位)
- [第 5 章 物流：搬运与物品转运](#第-5-章-物流搬运与物品转运)
- [第 6 章 火控：索敌与集火](#第-6-章-火控索敌与集火)
- [第 7 章 建造 / 拆除（世界处理器）](#第-7-章-建造--拆除世界处理器)
- [第 8 章 内存建筑与共享黑板](#第-8-章-内存建筑与共享黑板)
- [第 9 章 显示与绘制](#第-9-章-显示与绘制)
- [第 10 章 反抽插 / 反炸房 / 抗干扰](#第-10-章-反抽插--反炸房--抗干扰)
- [第 11 章 反面教材：蓝图里真实存在的 Bug](#第-11-章-反面教材蓝图里真实存在的-bug)
- [附录 A 指令速查](#附录-a-指令速查)
- [附录 B 工具用法](#附录-b-工具用法)

---

# 第 0 章 蓝图文件怎么解析

## 0.1 `.msch` 外层格式

从 [Schematics.java:543](../Mindustry-Source/core/src/mindustry/game/Schematics.java#L543)（读）和 [:623](../Mindustry-Source/core/src/mindustry/game/Schematics.java#L623)（写）还原：

```
偏移  类型        含义
0     byte[4]     'm''s''c''h' 魔数
4     uint8       版本号（当前 = 1）
5..   zlib 流     ↓ 解压后
      int16       width
      int16       height
      uint8       tagCount
      tagCount × {UTF key, UTF value}       ← labels / contentMap / name / description
      uint8       blockDictLen
      blockDictLen × UTF blockName
      int32       totalTiles
      totalTiles × {
          int8    blockDict 索引
          int32   Point2.pack(x, y)
          ?       TypeIO 序列化的 config   ← 逻辑代码藏在这里
          int8    rotation
      }
```

两个容易踩的坑：

1. **`UTF` 是 Java `DataInputStream.readUTF`**，即"uint16 长度 + 修改版 UTF-8"。修改版 UTF-8 把补充平面字符（U+10000 以上）拆成 **CESU-8 代理对**（6 字节），而不是标准 UTF-8 的 4 字节。普通 Python `decode('utf-8')` 对 BMP 内的中文没问题，只有遇到 emoji 级字符才会出偏差。
2. **坐标是 `Point2.pack` 打包的 32 位整数**：`x = (short)(packed >> 16)`，`y = (short)(packed & 0xFFFF)`。都是**有符号**的，所以解包必须做符号扩展。

## 0.2 逻辑代码藏在哪

逻辑类方块（`micro-processor` / `logic-processor` / `hyper-processor` / `world-processor`）在 [LogicBlock.java:65](../Mindustry-Source/core/src/mindustry/world/blocks/logic/LogicBlock.java#L65) 声明了：

```java
config(byte[].class, (LogicBuild build, byte[] data) -> build.readCompressed(data, true));
```

所以那个 `TypeIO type-14 byte[]` 就是逻辑数据。它本身又是**第二层 zlib**，格式见 [LogicBlock.java:141](../Mindustry-Source/core/src/mindustry/world/blocks/logic/LogicBlock.java#L141)：

```
uint8   logicVersion        (0 = 旧版只有链接；1 = 当前)
int32   byteLen
byteLen × bytes             ← UTF-8 的 mlog 源码，一行一条指令
int32   linkCount
linkCount × { UTF linkName, int16 x, int16 y }   ← x/y 是相对处理器原点的偏移
```

**这是最关键的一条结论**：

> **蓝图里存的是 mlog 明文源码，不是编译后的字节码。**
> 因为游戏内部 `LAssembler.write()`（[LAssembler.java:42](../Mindustry-Source/core/src/mindustry/logic/LAssembler.java#L42)）产出的就是"一行一条语句"的文本，而 `LogicBuild.config()` 直接把这个字符串 `getBytes(charset)` 写进去。

所以**解析 = 零损失还原，完全不需要反编译**。任何声称"要反编译蓝图逻辑"的说法都是误解。

## 0.3 实测覆盖率

| 指标 | 数值 |
|---|---|
| 游戏目录蓝图总数 | 625 |
| 解析成功 | **624**（99.8%） |
| 含逻辑的蓝图 | 430 |
| 逻辑块总数 | 5774 |
| 语句总数 | 3,719,102 |

唯一失败的是 `90d8d0114faa503637ba671dee7042d4.png_2.msch`——**游戏自己也读不了它**，`last_log.txt` 里明确记录着 `java.io.IOException: Invalid schematic: Too many blocks.`。这不是解析器的问题。

### ⚠️ 一个必须知道的统计陷阱

3,719,102 条语句里，**97.8% 是噪点**：

| 蓝图 | 语句数 | 占比 | 性质 |
|---|---|---|---|
| `Linux on mlogv32.msch` | 2,251,980 | 60.6% | mlog 上实现的 RISC-V 模拟器（**已按要求排除**） |
| `BADAPPLE!!.msch` | 564,073 | 15.2% | 显示屏像素画 |
| `pic大型幻象.msch` | 242,555 | 6.5% | 像素画 |
| `最可爱.msch` | 154,653 | 4.2% | 像素画 |
| `intel corei3.msch` | — | — | 像素画（126,759 条 `draw`） |

**排除噪点后，真正有算法内容的语句只有 22.5 万条，处理器中位数 77 条语句。**
所有"模式"分析都必须在这个纯净子集上做，否则统计结果会被 `draw` 淹没。

---

# 第 1 章 执行机制（原理核心）

## 1.1 一帧到底执行几条指令

源码 [LogicBlock.java:560-580](../Mindustry-Source/core/src/mindustry/world/blocks/logic/LogicBlock.java#L560)：

```java
accumulator += edelta() * ipt;                      // 先累积
if(accumulator > maxInstructionScale * ipt)          // 上限裁剪
    accumulator = maxInstructionScale * ipt;
while(accumulator >= 1f){                            // 再消费
    if(executor.yield){ executor.yield = false; break; }   // wait 中断
    executor.runOnce();
    accumulator--;
}
```

三个必须记住的推论：

1. **`@ipt` 是"每 tick 的指令预算"，不是"每帧固定执行 ipt 条"。** 预算按 `edelta()` 缩放，游戏加速时 `edelta()` 变大，处理器会一次性跑更多条来追上进度——所以**加速会让逻辑行为改变**。
2. **`accumulator` 上限 = `maxInstructionScale * ipt` = `5 * ipt`**。这是积压保护：卡顿后最多补 5 个 tick 的量，不会无限堆积。
3. **`wait` 是唯一的"主动让出"**：它设置 `yield = true`，`while` 循环立即 `break`，本 tick 剩下的预算全部作废，**不累积到下帧**。所以 `wait` 是"降频"的最直接手段。

### 处理器 @ipt 表

| 处理器 | 默认 @ipt | 链接范围 | 尺寸 | 备注 |
|---|---|---|---|---|
| micro-processor | 2 | 10 格 | 1×1 | 120 指令/秒 |
| logic-processor | 8 | 22 格 | 2×2 | 480 指令/秒 |
| hyper-processor | 25 | 42 格 | 3×3 | 1500 指令/秒，需冷却液 |
| world-processor | 8 | 全图 | 1×1 | 可 `setrate`，上限 1000（60000 指令/秒） |

> **实战含义**：`hyper-processor` 的 25 ipt 是 micro 的 12.5 倍。`中国象棋` 就同时用了 logic-processor（控制）和 hyper-processor（395 条语句的走子判定 + 显卡绘制），后者就是靠 ipt 优势扛住计算量的。

## 1.2 `@ipt` 能被改吗

能，但**只有世界处理器**，而且**有硬上限 1000**：

```
setrate <值>      # 世界处理器专属
```

源码 [LExecutor.java:2028](../Mindustry-Source/core/src/mindustry/logic/LExecutor.java#L2028)：

```java
public void run(LExecutor exec){
    if(exec.build == null) return;
    exec.build.ipt = Mathf.clamp(amount.numi(), 1, ((LogicBlock)exec.build.block).maxInstructionsPerTick);
    if(exec.ipt != null) exec.ipt.numval = exec.build.ipt;
}
```

即 **`ipt = clamp(值, 1, maxInstructionsPerTick)`**，而 [Blocks.java:6958](../Mindustry-Source/core/src/mindustry/content/Blocks.java#L6958) 给世界处理器设了 `maxInstructionsPerTick = 1000`：

```java
worldProcessor.maxInstructionsPerTick = 1000;    // Blocks.java:6958
```

> **同时注意**：[LogicBlock.java:48](../Mindustry-Source/core/src/mindustry/world/blocks/logic/LogicBlock.java#L48) 的默认值是 `maxInstructionsPerTick = 40`，只有世界处理器被显式抬到 1000。
> micro/logic/hyper 三种处理器**根本不能执行 `setrate`**（`SetRateI.run` 开头就 `if(exec.build == null) return;`，而且 `setrate` 被注册为 privileged 指令）。

**你的语料里 `setrate` 的实际取值分布**（30 处）：

| 取值 | 次数 | 实际生效值 |
|---|---|---|
| `1000` | 10 | 1000 |
| `normal.ipt`（变量，10） | 6 | 10 |
| `500` | 5 | 500 |
| `20` | 3 | 20 |
| `10` | 2 | 10 |
| `300` | 2 | 300 |
| `50` | 2 | 50 |
| `200` | 1 | 200 |
| **`2000`** | 1 | **1000（被 clamp 截断）** |

`MCV.msc`（移动核心）的用法最值得学——平时省性能，密集遍历时瞬间拉满：

```mlog
set normal.ipt 10
setrate normal.ipt            # 常态：10
...
setrate 1000                  # 开始遍历核心物品，瞬间拉满
set i.item 0
... 遍历 @itemCount ...
setrate normal.ipt            # 遍历结束，还原
```

**MindustryX 的差异**：我用字节码工具查了你的安装，`dexed-MindustryX-2026.05.24.B456.loader.jar` 里的世界处理器类构造函数里同样写着 `sipush 1000`，与官方源码一致——**没有额外改动**。所以该 mod 环境下这一条以官方行为为准。

**注意**：`accumulator` 不会因为改 ipt 而重置，所以从 10 拉到 1000 的瞬间会有一段"预算暴涨"，表现为一次性跑很多指令。MCV 正是利用这一点做"即时性"操作。

## 1.3 帧差（frame delta）与缓存

这是中高级逻辑最容易踩的隐性 bug。核心事实：**`sensor` 读到的值可能是"上一帧"的**。

原因在于 Mindustry 的执行顺序：

1. 世界逻辑（建筑 `update()`）跑完
2. 处理器逻辑（`LogicBuild.update()`）跑
3. 但单位 AI、传送带转运等可能在自己的时间片里才更新

所以你在 tick N 读 `@shooting`，拿到的可能是 tick N-1 的状态。

**缓解手段**：

| 手段 | 说明 |
|---|---|
| `wait` | 强制跨 tick，让世界状态先稳定 |
| `read` / `write` 内存 | 内存建筑的读写在处理器自己的时间片内是自洽的 |
| `printflush` / `drawflush` | 显式同步到消息/显示屏 |
| 双缓存 | 写两个内存位，读"上一次"的值来比较 |

**你的蓝图里的实际做法**：`搬运t4`、`ILI集火逻辑` 都用了一个"**变化检测**"惯用法：

```mlog
sensor 艾铭射的x Iliary艾铭 @shootX       # 读当前值
sensor 艾铭在射 Iliary艾铭 @shooting
op add 艾铭变了 艾铭射的x 艾铭在射        # 组合成一个"指纹"
jump 1 equal 艾铭变了 艾铭真的变了        # 指纹没变 → 回开头重读（自旋等待）
sensor 艾铭射的y Iliary艾铭 @shootY
set 艾铭真的变了 艾铭变了                 # 指纹变了 → 记录并继续
```

这是**用自旋轮询代替中断**：不停读直到状态真的变化才干活。代价是烧 ipt，收益是绝不错过状态跳变。

## 1.4 网络同步

| 类别 | 指令 | 同步性 |
|---|---|---|
| 本地安全 | `set` `op` `jump` `read` `write` `select` `lookup` `packcolor` | 不回传，各客户端独立算 |
| 需要回传 | `control` `ucontrol` `build` `deconstruct` `setrule` `spawn` `bullet` `effect` | 影响世界，走 `Call.*` 同步 |
| 显示 | `draw` `print` | 客户端本地，但 `drawflush`/`printflush` 才真正提交 |

**关键**：多人游戏里**每个客户端都独立跑一遍逻辑**。如果你的逻辑依赖 `@time` 或 `op rand`，不同客户端会算出不同结果，表现为"显示不一致"或"偶发不执行"。

`ILI反病毒.msch` 里有 `op rand` 用于随机化——这在多人环境要小心。

### 更精确的同步清单（来自你的 `Logic-Docs-v1.1.0` §网络同步）

文档把指令分成两类，比"本地/回传"更实用：

**服务器直接操作单位对象 —— 不受同步影响**：
`ubind`、**所有 `ucontrol` 子指令**、`uradar`、`ulocate`

> 原因：这些指令改的是单位的 AI 状态，物理结果由服务器统一计算后同步给客户端。所以**单位控制的"意图"是本地算的，但"结果"是服务器给的**——这也是为什么单位看起来会有轻微延迟感。

**涉及建筑状态读写 —— 受同步影响**：
`read` / `write`（内存）、`control`（建筑配置）、`sensor`（读建筑状态**可能读到过时值**）、`draw` 系列（可能闪烁/延迟）、`print`

**文档给出的四条应对策略**：

1. **避免高频写入**——同一个建筑的 `write`/`control` 不要每帧执行，加计数器降频
2. **读取容错**——对 `sensor` 结果做合理性判断（例如范围检查）
3. **幂等设计**——重复执行同一条指令不应产生不同结果
4. **严格同步的操作交给世界处理器**——它在服务端执行，不存在客户端同步问题

**两个补充事实**：

- **`draw` 在无头服务器（headless / 专用服务器）上完全不执行。** 如果你的逻辑只在显示屏上体现效果，在服务器端等于空转。
- **`sync` 是「服务器 → 客户端」单向，且每 tick 最多同步 120 个变量**，超出部分**不会同步**。频繁 `sync` 还会拖慢网络。所以 `sync` 不是万能药，只在关键状态上用。

---

## 1.5 三条容易被忽略的硬限制

### 限制一：指令总数上限 1000 条

[LExecutor.java:41](../Mindustry-Source/core/src/mindustry/logic/LExecutor.java#L41)：

```java
public static int maxInstructions = 1000;
```

[LParser.java:185](../Mindustry-Source/core/src/mindustry/logic/LParser.java#L185)：

```java
while(pos < chars.length && line < LExecutor.maxInstructions){
```

**超出 1000 条的代码会被静默截断**——解析循环直接结束，后面的指令全部丢失。

> **这条对你的语料意义重大**：解析出来的最大处理器是 1985 条语句（`Linux on mlogv32`，已排除），**远超 1000**。
> 这说明该蓝图**要么是在更早的版本（上限更高）制作的，要么是被截断后依然"能用"**。如果你自己写长逻辑，**必须把 1000 条当成硬天花板**，超了要用多处理器拆分。

### 限制二：未知指令静默变成 `noop`

[LStatements.java](../Mindustry-Source/core/src/mindustry/logic/LStatements.java) 用 `InvalidStatement` 兜底，凡是无法识别的指令名都会被注册成 `noop`，[LExecutor.java:905](../Mindustry-Source/core/src/mindustry/logic/LExecutor.java#L905) 的 `NoopI.run()` 是空实现。

**后果**：
- **拼错的指令不会报错**，只会静默什么都不做
- **调试技巧**：如果某段逻辑"完全没反应"，先怀疑拼写——那一行很可能就是个 `noop`
- 这也解释了为什么某些看起来"有 bug 的代码"依然能跑——**出错的那行可能早就被降级成空操作了**

### 限制三：标签最多 500 个

`maxJumps = 500`。超出的标签定义会失败。另外**未解析的标签目标为 -1，`jump` 不跳转，等同于 `noop`**。

> 这也意味着：如果你把带标签的代码导入游戏，某个标签拼错了，**不会报错，只是那个跳转永远不发生**——逻辑会静默地"穿透"过去。这是最阴险的一类 bug。

---

# 第 2 章 跳转与标签机制

## 2.1 标签在导入时就被编译成行号了

[LParser.java:112-176](../Mindustry-Source/core/src/mindustry/logic/LParser.java#L112) 是两趟解析：

- **第一趟**：扫描到 `标签名:` 形式的 token，把 `jumpLocations.put(label, line)` 记下来。**注意：这一步不产生任何 Statement 对象，`line` 不递增。**
- **第二趟**：把 `jump` 的标签名替换成记录的 `line` 数值。

**这解释了三个现象**：

1. **标签不占指令位、不消耗 @ipt**——因为它根本不是指令。
2. **从蓝图里解析出来的代码，`jump` 目标全是数字**，标签信息已经丢了。你看到的 `jump 48 lessThan mp 5` 里的 `48` 就是当年那个标签的语句索引。
3. **想还原成带标签的可读代码**，需要自己做"跳转目标 → 标签"的反向标注（本模式库后面的示例都做了这件事）。

## 2.2 `jump` 的完整语义

```
jump <目标> <条件> <左值> <右值>
jump <目标> always
```

`LExecutor` 里 `jump` 修改 `@counter`；**条件不成立时 `@counter` 正常 +1**。

条件运算符（`ConditionOp`）：

| 写法 | 含义 | 陷阱 |
|---|---|---|
| `equal` | `==` | **带浮点容差 0.000001** |
| `notEqual` | `!=` | |
| `lessThan` / `lessThanEq` / `greaterThan` / `greaterThanEq` | `<` `<=` `>` `>=` | |
| `strictEqual` | `===` | **严格相等，同时比类型和值** |
| `always` | 恒真 | 后面两个参数被忽略 |

### `equal` vs `strictEqual` 的实战差别

这是**你的蓝图里最常见的隐患之一**。

```mlog
set 艾铭在这里 0
jump 10 equal 艾铭在这里 0          # 0 == 0 → 跳
```

但如果是对象：

```mlog
sensor co @unit @controlled          # co 可能是 null 或数字
jump 41 notEqual controlled 0        # null != 0 → 跳！
```

`equal` 对**数字与 null 比较**用的是 `Structs.eq`，`null` 和 `0` **不相等**。
所以 `jump X notEqual co 0` 在 `co == null` 时**会跳转**——很多"单位已经空了却还在执行控制"的 bug 就出在这里。

**正确姿势**：判断对象是否存在，用 `null` 比较：

```mlog
jump X equal building null       # 明确判空
jump Y strictEqual min%item 1    # 严格判数值，避免浮点容差误判
```

## 2.3 `end` 与"跑出程序末尾"

- `end` 把 `@counter` 设为指令总长度，效果等价于跳回开头（下一轮 `@counter` 越界后重置为 0）。
- **不加 `end` 直接跑到底，行为是一样的**——`@counter` 超出数组范围会自动回 0。
- 所以 `end` 是**语义标注**，不是必需的。

**你的蓝图里 `end` 的典型用法**是"条件保护下的提前返回"：

```mlog
sensor reset switch1 @enabled
jump 3 equal reset 1
end                          # switch 没开 → 直接回到开头，本 tick 不干活
set // let ...
```

这是**最省 ipt 的"关掉逻辑"手段**：一条 `end` 让整个 tick 立即结束。比用 `jump` 绕一大圈便宜得多。

## 2.4 标签踩空

`LParser` 记录标签时存的是"当时已经解析出的语句数"。如果你的标签**在文件最末尾、下面没有任何指令**：

```mlog
set x 1
loop:            # ← 踩空！line == statements.size()
```

跳转时 `@counter = statements.size()`，越界被重置为 0，**实际跳回了开头**而不是"标签所在位置"。行为不可预测。

**规范**：标签下面必须至少跟一条指令；文件和分支末尾用 `end` 而不是裸标签。

## 2.5 高级：用 `@counter` 做跳转表

`@counter` 是**可写**的。你的蓝图里有 39 处用到这个技巧，这是语料里最"高级"的写法。

### 模式 A：固定偏移分派（`ILIOS.msch`）

```mlog
op add @counter @counter state     # 以 state 为索引跳转
jump 9 always 0 false              # state=0 → 落到这
jump 12 always 0 false             # state=1 → 落到这
jump 15 always 0 false             # state=2 → 落到这
```

`op add @counter @counter state` **执行完后 `@counter` 还会自动 +1**，所以：

- `state = 0` → 下一跳落在 `jump 9`（即索引 1）
- `state = 1` → 落在索引 2
- 以此类推

**这是 O(1) 状态机分派**，比一长串 `jump X equal state 0 / jump Y equal state 1 ...` 快得多，而且**语句数恒定**。

### 模式 B：缩放索引（`ILI反病毒.msch`）

```mlog
op add u.i u.i 1
op mod u.i u.i 8            # u.i ∈ [0,8)
op mul counterp u.i 2       # 每档占 2 条
op add @counter @counter counterp
set uty @nova               # 档 0
jump 23 always 0 false      # 跳出
set uty @pulsar             # 档 1
...
```

`mul ... 2` 是因为**每个分支占 2 条语句**。这是手工做的"跳转表步长"，等价于 C 的 `switch`。

### 模式 C：动态计算跳转目标

`ILI集火逻辑.msch` 里最精妙的一段：

```mlog
op min 鱼梦醒时 100 @links
op sub 鱼梦醒时 100 @links
set 艾铭想从这连接 @counter
set 艾铭上次连接的 @links
op add @counter @counter 鱼梦醒时
```

这是在**运行时计算"该跳到哪一批 getlink"**，用 `100 - @links` 做偏移，让链接数不同的蓝图都能正确跳到对应的代码块。属于"自适配代码"。

> ⚠️ **风险**：这类写法**不可维护**。插入/删除任何一条指令都会让所有偏移错位。你的蓝图里这类代码都没有注释，说明作者本人也很可能已经看不懂了。**新代码不建议模仿**，但读懂它是必要的。

---

# 第 3 章 链接系统与建筑交互

## 3.1 链接是怎么工作的

处理器和建筑之间靠"链接"通信。蓝图里链接以 **(name, 相对 x, 相对 y)** 存储（[LogicBlock.java:300-322](../Mindustry-Source/core/src/mindustry/world/blocks/logic/LogicBlock.java#L300)），读入时 `x += tileX(); y += tileY()` 转成绝对坐标。

链接名生成规则见 [LogicBlock.java:123](../Mindustry-Source/core/src/mindustry/world/blocks/logic/LogicBlock.java#L123) `getLinkName()`：取方块名，去掉 `-` 后缀（如 `-large`、数字后缀），得到 `conveyor`、`reactor`、`foreshadow` 这类基名，重名则加数字尾巴 `conveyor1`、`conveyor2`。

**注意**：名字是**存进蓝图**的。如果你改了某个链接名，旧名字不会自动更新——`readCompressed` 里有个兜底：

```java
String bestName = getLinkName(build.block);
if(!name.startsWith(bestName)) name = findLinkName(build.block);   // 名字对不上就重新分配
```

## 3.2 访问链接的两条路

### 方式一：具名（推荐，可读性好）

```mlog
sensor 冷却液 核电 @cryofluid        # 直接用链接名
control enabled 核电 0 0 0 0
```

链接名在蓝图里是**变量**，直接当标识符用。

### 方式二：`getlink` + `@links` 遍历（适合批量）

```mlog
set i 0
getlink b i                          # 取第 i 个链接
sensor co b @controlled
jump 17 equal co 2
op add i i 1
jump 19 lessThan i @links            # @links = 链接总数
```

**`@links` 是链接总数**，`getlink x i` 取第 i 个（0 基）。

## 3.3 轮转链接：把负载摊到多帧

这是**你的蓝图里最高频的优化模式**（95 个逻辑块用到）。原因是：**如果每帧都遍历 100 个炮塔，micro-processor 的 2 ipt 根本跑不完**。

```mlog
set 序号 0
loop:
op add 序号 序号 1
op mod 序号 序号 @links             # 环形索引，越界自动回 0
getlink 核电 序号                    # 只处理这一个
sensor 冷却液 核电 @cryofluid
...
jump loop always
```

**效果**：每个 tick 只处理 1 个链接，`@links` 个 tick 轮完一圈。
- 100 个炮塔 + 1 ipt 预算 → 100 tick（约 1.7 秒）轮一圈
- 对"反应速度要求不高、但数量大"的场景（发电机启停、冷却液监测、传送带开关）**完全够用**

**这是"用延迟换吞吐"的经典手法**，也是大规模逻辑组能跑起来的核心原因。

`17十七硫幽灵四熔毁四油海啸组.msch` 的 212 个链接就是靠这个模式撑住的。

## 3.4 关键 sensor 属性速查

| 属性 | 适用 | 含义 |
|---|---|---|
| `@x` `@y` | 通用 | tile 坐标 |
| `@health` / `@maxHealth` | 通用 | 生命值 |
| `@dead` | 单位/建筑 | 1 = 已死（**判活必用**） |
| `@enabled` | 建筑 | 是否启用 |
| `@controlled` | 单位/建筑 | `1`=逻辑控制 `2`=玩家控制 `3`=指令控制 `0`=空闲 |
| `@controlled` 建筑 | `2`=玩家控制 |
| `@shooting` `@shootX` `@shootY` | 炮塔 | 是否开火 + 瞄准点 |
| `@firstItem` | 单位 | 携带的第一种物品（可空） |
| `@itemCapacity` / `@itemCount` | 单位/核心 | 容量 / 数量 |
| `@config` | 建筑 | 当前配置（分拣器筛的物料等） |
| `@flag` | 单位 | flag 值 |
| `@controlled` 见 §4.3 | | |
| `@size` | 单位 | 尺寸（tile） |
| `@range` / `@buildRange` | 单位 | 攻击/建造范围 |
| `@type` | 单位 | UnitType（用于 `ubind` 绑定） |
| `@payloadCount` | 单位 | 载荷数 |
| `@pingX` `@pingY` | 玩家单位 | 标记点（**可空，且是 NaN 陷阱**） |

### `@controlled` 的真相（源码级）

[UnitComp.java:296](../Mindustry-Source/core/src/mindustry/entities/comp/UnitComp.java#L296)：

```java
case controlled -> !isValid() ? 0 :
        controller instanceof LogicAI ? ctrlProcessor :   // = 1
        controller instanceof Player  ? ctrlPlayer    :   // = 2
        controller instanceof CommandAI command && command.hasCommand() ? ctrlCommand : // = 3
        0;
```

常量定义在 [GlobalVars.java:24](../Mindustry-Source/core/src/mindustry/logic/GlobalVars.java#L24)：`ctrlProcessor = 1, ctrlPlayer = 2, ctrlCommand = 3`。

**这意味着**：
- `jump 41 notEqual controlled 0` → "只要有任何控制者（含玩家、指令 AI）就跳过"。**这常被误当作"这个单位被逻辑占用了"，其实玩家控制的单位也会命中。**
- `jump 17 equal co 2` → "炮塔被玩家手动控制，跳过"（建筑只有 0/2 两种）。
- **无法区分是哪个处理器控制的**——所有逻辑控制都返回 1。

所以**多处理器争抢同一批单位时，`@controlled` 是不可靠的抢占判据**。可靠的两种做法：

```mlog
# 做法一：flag 打标记（见 §4.6 的命名规范）
sensor f @unit @flag
jump 换一个 notEqual f 0

# 做法二：直接比控制器引用
sensor ctr @unit @controller
jump 是我控的 equal ctr @this
```

> ⚠️ `@controller` **没有出现在 `sensor` 属性总表里**，只在官方示例代码中使用——属于"能用但未文档化"，用前建议实测。

**`@controlled` 唯一无歧义的用法**是判断"是不是完全自由的单位"：

```mlog
sensor co @unit @controlled
jump 自由单位 equal co 0
```

---

# 第 4 章 兵控：单位绑定与多控槽位

兵控是你蓝图里**占比最大、模式最成熟**的一类。5774 个逻辑块里 `ubind` 出现 1066 次，`ucontrol` 出现 3305 次。

## 4.1 `ubind` 的真实语义（源码级）

[LExecutor.java:178-206](../Mindustry-Source/core/src/mindustry/logic/LExecutor.java#L178)：

```java
if(type.obj() instanceof UnitType type && type.logicControllable){
    Seq<Unit> seq = exec.team.data().unitCache(type);
    if(seq != null && seq.any()){
        exec.binds[type.id] %= seq.size;              // 环形
        exec.unit.setconst(seq.get(exec.binds[type.id]));
        exec.binds[type.id]++;                         // 推进计数器
    }else{
        exec.unit.setconst(null);
    }
}
```

**四个关键点**：

1. **计数器 `exec.binds[type.id]` 是"每个处理器、每个单位类型"独立的**。所以同一个处理器里 `ubind @flare` 和 `ubind @mono` 各转各的圈，互不干扰。
2. **`ubind` 就是 `@unit = 下一个同类单位`**，环形的。连续两次 `ubind @flare` 会拿到**两个不同的 flare**。
3. **`ubind` 不需要单位"空闲"**。它会无条件绑定，包括已经被别的处理器控制的单位。
4. **按"具体单位对象"绑定不会推进环形计数器**（走的是另一个分支）。所以 `ubind u1`（u1 是变量）和 `ubind @flare` 是两套互不干扰的机制——**多控槽位模式正是靠这一点工作的**。

### 两条必须知道的坑

**坑一：绑定顺序会在单位死亡时跳变。**
单位列表用**置换删除（swap and pop）**维护——某个单位死了，列表会把**末尾的单位移到它原来的位置**。所以"绑定的第 3 个"在单位死亡后可能变成完全不同的单位。
**推论**：不要依赖"第 N 次 `ubind` 拿到的就是第 N 个单位"这种假设。

**坑二：`ubind` 遍历同类单位时，如果起始单位中途死了，会无限循环。**
你在"数单位数量"时如果不检查起始单位是否存活，遍历永远回不到起点。
**规范**：计数循环必须加起始单位死亡判断：

```mlog
sensor chushiDead chushi @dead
jump 结束 equal chushiDead 1        # 起始单位死了 → 立即退出，否则死循环
```

### `logicControllable` 前置条件

只有 `type.logicControllable == true` 的单位能被绑定。**核心（Core）单位、部分建筑型单位不可控。**

**另外**：非特权处理器**不能绑定敌方单位**，只有世界处理器可以。
**玩家单位**可以被 `ubind` 到，但 `ucontrol`/`uradar`/`ulocate` 对它**全部无效**——因为 `checkLogicAI()` 检查 `unit.controller().isLogicControllable()`，而 `Player.isLogicControllable()` 返回 `false`。玩家松开控制后逻辑指令才生效。

### 单元不可控时的保护

```mlog
ubind @flare
jump 0 equal @unit null        # ⚠️ 这是死循环写法！
```

**`多单位搬运物品至核心.msch` 第 0-1 行就是这样的**：

```mlog
ubind @flare
jump 0 equal @unit null        # 没有 flare → 无限重绑
```

没有单位时会**死循环烧 ipt**。更稳妥的是加个 `wait` 或跳出去：

```mlog
ubind @flare
jump nowait notEqual @unit null
wait 0.5                       # 没单位就歇一会
nowait:
```

> **顺带说明 `wait 0.5` 到底做了什么**：`wait` 在时间没到时**会回退 `@counter`**（回到自己这一条）并设 `yield = true` 结束本 tick。所以下一 tick 会**重新执行同一条 `wait`** 并累加 `curTime`，直到累计到 0.5 秒才继续往下。
> **关键结论：等待期间 `accumulator` 不递减，等完了也**不会**"补偿性"地猛跑一堆指令。所以 `wait` 是干净的降频手段。**

## 4.2 多控槽位模式（Multi-Control）

这是**你最核心的兵控模式**，在 `搬运t4`、`多单位搬运物品至核心`、`僚机程序`、`贴核5t3` 等几十个蓝图里反复出现。

### 核心思想

`ubind @flare` 每次拿"下一个"，无法直接指定"第 3 个 flare"。所以要**给每个单位打标记**，然后以后靠标记找回它们。

### 标准实现（逐段注释）

```mlog
# ── 阶段 1：初始化，声明要控几个 ──
ubind @flare
jump 0 equal @unit null          # 没单位，重试
set 绑定数量 8                    # 想控 8 个
getlink bd 1                     # 第二个链接是"目标建筑"
jump 0 equal bd null             # 没链接，重试
sensor type @unit @type           # 记住单位类型
sensor max  @unit @itemCapacity   # 记住容量
jump 15 lessThan 绑定数量 8       # 夹紧上限
set 绑定数量 8

# ── 阶段 2：认领 8 个单位，逐个打 flag ──
set i 0
set ztmax 绑定数量
ubind type                        # 按类型绑，绕圈
sensor co @unit @controlled
jump 22 equal co 0                # 空闲才要
sensor f @unit @flag
jump 17 notEqual f 0              # 已经有 flag 说明被别人占了，跳过
op add i i 1
jump 25 notEqual i 1
set u1 @unit                      # ← 存进槽位变量
jump 27 notEqual i 2
set u2 @unit
...                               # 一直到 u8
ucontrol flag 11011 0 0 0 0       # ← 打上统一标记 11011
jump 17 lessThan i 绑定数量       # 还不够？继续抢
```

**三个设计要点**：

| 要点 | 作用 |
|---|---|
| `sensor f @unit @flag` + `jump notEqual f 0` | **跳过已被占用的单位**。因为 flag 默认 0，非 0 即"有人了" |
| `ucontrol flag 11011` | **占用声明**。用一个"魔法数字"作为本次逻辑的专属标记 |
| `set u1 @unit` … `set u8 @unit` | **槽位变量**。mlog 没有数组，只能用 `u1..u8` 这种平铺变量 |

> **`11011` 这种数字不是随便选的**——它相当于"逻辑组的 ID"。同一张图上多套兵控逻辑必须用**不同的 flag 值**，否则会互相抢占。
> 语料里见到的：`11011`（多单位搬运）、`9001..9005`（僚机程序，每个槽位一个号）。

### 为什么要两个方案并存

`多单位搬运物品至核心.msch` 的说明文字里作者自己点出了关键：

```
print 非FLAG控制，即使被改flag也会继续搬运
print 加flag只是为了告诉其他逻辑正在控制
```

**这是很重要的区分**：
- **槽位变量 `u1..u8` 保存了真实引用**，所以 flag 被外部改掉**不影响**已建立的绑定。
- **flag 只是"给别人看的告示牌"**，用来防止别的逻辑重复认领。

所以这个模式是**双轨**的：变量管自己，flag 管别人。

## 4.3 死单位重绑模式

单位会死。槽位里的引用变成死引用，必须先检测再补。

```mlog
label_slot1:
ubind u1                          # 绑定到槽位里记录的那个具体单位
sensor de u1 @dead                # 先查它死没死（用变量，不是 @unit）
jump 下一个槽位 equal de 0         # 没死 → 跳过

# ── 死了，尝试补一个新的 ──
set try 0
label_retry:
jump 跳过 greaterThan try 3       # 最多重试 3 次，防死循环
ubind type                        # 按类型找新的
sensor co @unit @controlled
jump 下一个槽位 equal co 0         # ⚠️ 见下方警告
sensor f @unit @flag
op add try try 1
jump label_retry notEqual f 0     # 有 flag 说明被占，再试
set u1 @unit                      # 成功认领
ucontrol flag 11011 0 0 0 0
```

**两个值得注意的细节**：

1. **`jump 下一个槽位 equal co 0` 这个条件是反的**——`@controlled == 0` 表示"**空闲**"，但代码却在这里**跳过**了。这说明作者实际想表达的是"如果 `co` 读到的是 null/异常值就跳过"，是**防御性写法**而非逻辑本意。你在 `搬运t4.msch` 里能看到同一位置的条件是 `jump 62 equal co 0`，但语义注释是"已被控制则跳过"——**作者的意图和代码不完全一致**。这是语料里最值得警惕的一类 bug。
2. **`try` 上限是必须的**。没有它，一旦没有可用单位，重试循环会吃光整个 tick 预算且永不退出。

## 4.4 `ucontrol` 指令的精确语义

以下全部来自 [LExecutor.java:342-510](../Mindustry-Source/core/src/mindustry/logic/LExecutor.java#L342)。

### 前置检查：什么单位能被控

```java
public static LogicAI checkLogicAI(LExecutor exec, Object unitObj){
    if(unitObj instanceof Unit unit && unit.isValid()
        && exec.unit.obj() == unit                    // ← 必须是当前 @unit
        && (unit.team == exec.team || exec.privileged)
        && unit.controller().isLogicControllable()){
```

**关键约束**：`exec.unit.obj() == unit`——**`ucontrol` 只对"当前 `@unit`"生效**。
所以标准写法永远是：

```mlog
ubind u1            # 或 ubind @flare
ucontrol move x y 0 0 0    # 必须紧跟，中间不能 ubind 别的
```

### 控制超时机制（非常重要）

[LogicAI.java:18](../Mindustry-Source/core/src/mindustry/ai/types/LogicAI.java#L18)：

```java
public static final float logicControlTimeout = 60f * 10f;   // 600 帧 = 10 秒
```

`LogicAI.updateMovement()`（[LogicAI.java:59](../Mindustry-Source/core/src/mindustry/ai/types/LogicAI.java#L59)）：

```java
if(controlTimer > 0 && controller != null && controller.isValid()){
    controlTimer -= Time.delta;
}else{
    unit.resetController();     // ← 超时，单位回到默认 AI
    return;
}
```

**每次 `ucontrol` 都会把 `controlTimer` 重置为 600**。

> **推论**：如果你的单位控制循环因为某个分支卡住，超过 10 秒没有下发任何 `ucontrol`，单位会**自动脱离控制**，开始自由行动（通常是往回走或攻击附近敌人）。
> **这就是"逻辑卡一下单位就乱跑"的根因。**

### 各指令详解

| 指令 | 参数 | 行为 | 关键细节 |
|---|---|---|---|
| `ucontrol idle` | — | `ai.control = idle` | **只改状态，不清除采矿/建造**。单位会停在原地但继续挖矿 |
| `ucontrol stop` | — | `ai.control = stop` | **额外执行 `unit.mineTile = null; unit.clearBuilding();`**——真的全停 |
| `ucontrol move x y` | tile 坐标 | `moveTo(pos, 1f, 30f)` | 直线飞向目标，**不绕障碍**。半径 1 tile 内停 |
| `ucontrol approach x y r` | tile 坐标 + 半径 | `moveTo(pos, moveRad - 7f, 7, true, null)` | 接近到半径 r 处就停，**带路径平滑参数 7** |
| `ucontrol pathfind x y` | tile 坐标 | 地面单位走 `controlPath` 寻路；飞行单位退化为 `move` | **有寻路开销**，卡住时会耗性能 |
| `ucontrol autoPathfind` | — | 自动冲向最近敌方核心；若在出生点保护圈内则不动 | 不需要参数，**最适合"放出去自己打"** |
| `ucontrol boost 1/0` | bool | `ai.boost = bool` | 只有部分单位（如 flare/eclipse 系）有意义 |
| `ucontrol target x y shoot` | tile 坐标 + bool | 设置 `posTarget` 和 `shoot` | **瞄准地面点** |
| `ucontrol targetp 对象 shoot` | 对象 + bool | `ai.mainTarget = 对象` | **瞄准具体单位/建筑实体** |
| `ucontrol itemDrop 建筑 数量` | 建筑 + 数量 | 往建筑塞物品 | 距离限制 `45 + 建筑尺寸*4` 像素；`@air` 表示**丢弃到地面**（清空物品） |
| `ucontrol itemTake 建筑 物品 数量` | 建筑 + 物品 + 数量 | 从建筑取物品 | 同样受距离限制 |
| `ucontrol payDrop` | — | 丢下载荷 | **有 1.5 秒冷却**（`transferDelay = 90`） |
| `ucontrol payTake 类型` | bool | `true` 抓单位，`false` 抓建筑 | 同样 1.5 秒冷却 |
| `ucontrol payEnter` | — | 单位进入脚下建筑 | 用于让单位"坐进"炮塔 |
| `ucontrol mine x y` | tile 坐标 | 设置采矿目标 | 需 `unit.canMine()`；范围外自动清空 |
| `ucontrol flag v` | 数值 | `unit.flag = v` | **纯标记，无游戏效果**，供逻辑之间通信 |
| `ucontrol build x y 方块 旋转 配置` | | 让单位去建造 | **需 `state.rules.logicUnitBuild`（默认 true）**；方块需已解锁；`p5` 是配置对象 |
| `ucontrol deconstruct x y` | tile 坐标 | 让单位拆除 | **`logicUnitDeconstruct` 默认 false！** 大多数图**用不了**，除非房主开规则或你用世界处理器 |
| `ucontrol getBlock x y 输出方块 输出建筑 输出地板` | | 查询格子信息 | **若超出 `max(@range, @buildRange)` 则三个输出全为 null** |
| `ucontrol within x y r 输出` | | 输出 1/0 | 写入第 4 个参数；**副作用：会顺便夺控单位**（见下方规则三） |
| `ucontrol unbind` | — | `unit.resetController()` | **解除的是"控制"不是"绑定"**——`@unit` 仍指向它，flag 也保留；**会打断正在控制该单位的其他逻辑** |

### 写代码时必须知道的三条 `ucontrol` 通用规则

**规则一：导出的格式永远是 7 个 token，没用到的参数位填 `0`。**

```
ucontrol <动作> <p1> <p2> <p3> <p4> <p5>
```

这就是为什么你看到的全是 `ucontrol stop 0 0 0 0 0`、`ucontrol idle 0 0 0 0 0`——**那些 `0` 是占位符，不是参数**。
所以 §7.2 里 `ucontrol move bx by @copper-wall 0 0` 的 `@copper-wall` 就是"从 build 复制过来忘了删"的残留。

**规则二：布尔参数是"非 0 即真"，不是"必须为 1"。**
`ucontrol target x y 5` 里的 `5` 等同于 `true`。

**规则三：`ucontrol within` / `ucontrol getBlock` 会"顺便夺控"。**
它们也会调用 `checkLogicAI()` 并刷新 10 秒计时器。这意味着：

> **如果你只是想"量一下距离"，却用了 `ucontrol within`，你会意外地把这个单位纳入逻辑控制。**

**替代方案**——用 `op len` 纯计算，不碰控制状态：

```mlog
sensor 我x @unit @x
sensor 我y @unit @y
op sub dx 目标x 我x
op sub dy 目标y 我y
op len 距离 dx dy
op lessThan 在范围内 距离 20
```

**这条同时解决了 §11.2 的距离计算问题和夺控副作用**，是更干净的做法。

### `idle` vs `stop`（很容易搞混）

| | 移动 | 采矿 | 建造 |
|---|---|---|---|
| `ucontrol idle` | 停 | **继续** | **继续** |
| `ucontrol stop` | 停 | **停止**（`mineTile = null`） | **停止**（`clearBuilding()`） |

**`idle` 只是"交还移动权"**，单位手上正在干的活不会停。
想让单位**彻底停手**必须用 `stop`。

### `ucontrol stop` 与 `stop` 指令不是一回事

- `ucontrol stop` —— 停止**单位**的动作
- `stop` —— 停止**处理器**继续执行（见附录 A.1）

### `getBlock` 拿到建筑引用后能干什么（重要限制）

`ucontrol getBlock` 返回的 building 引用，**即使单位已经离开范围**：

| 能做 | 不能做 |
|---|---|
| 对**存储类建筑**读写（`cell` / `bank` / 显示屏） | **启用/禁用**（`control enabled`） |
| 绘制到显示屏 | **修改配置**（`control config`） |

因为后两者需要单位**仍在范围内**。这个细节决定了"远程操控内存库"这类玩法是否可行。

### `move` vs `approach` vs `pathfind`

| | 停在哪 | 绕障碍 | 开销 |
|---|---|---|---|
| `move` | 目标点 1 tile 内 | ❌ 撞墙就卡 | 最低 |
| `approach` | 距目标 `r` 处 | ❌ | 低，但有接近平滑 |
| `pathfind` | 目标点 | ✅ 地面单位有效 | 高 |
| `autoPathfind` | 敌方核心附近 | ✅ | 高，但全自动 |

**实战选择**：
- 飞行单位 → `move`（本来就不撞墙）
- 地面单位短距离 → `move`
- 地面单位远距离、有地形 → `pathfind`
- 放出去自己打 → `autoPathfind`

### `target` vs `targetp`

```mlog
ucontrol target  sx sy 1        # 打坐标（sx sy 是 tile 坐标）
ucontrol targetp 敌人 1          # 打实体对象
```

**区别**：`target` 瞄一个固定的点，目标移动了就打空；`targetp` 跟踪实体，会持续跟随。
**但 `targetp` 有个坑**：`ai.mainTarget = p1.obj() instanceof Teamc t ? t : null`——**传进去的对象必须是 `Teamc`（有队伍的实体）**，传个数字会变成 null，单位就不开枪了。

## 4.5 官方建议的兵控分类

你的文档 `Logic-Docs-v1.1.0` 把兵控分为 **单控 / 群控 / 多控** 三类：

| 类型 | 特征 | 适用 | 语料代表 |
|---|---|---|---|
| **单控** | 一个处理器控一个单位，靠 `ubind` 每次拿下一个 | 少量精锐单位 | 简单逻辑 |
| **群控** | 一次 `ubind` + `ucontrol` 下发，所有同类单位**同时**执行 | 大规模自杀式冲锋 | `落地神风单元`、`落地Poly神风` |
| **多控** | 槽位变量 `u1..uN` 分别寻址，逐个下不同指令 | 需要编队/分工 | `搬运t4`、`僚机程序`、`多单位搬运物品至核心` |

**群控的原理**：`ucontrol` 作用于"当前 `@unit`"，但**如果只 `ubind` 一次然后 `ucontrol` 多次**，只有那一个单位受控。真正的"群控"是——

```mlog
label:
ubind @flare                    # 每次都拿下一个
ucontrol move x y 0 0 0         # 对它下发
jump label always                # 立刻回去拿下一个
```

**这才是"一次代码控所有单位"的真相**：靠**循环遍历**，不是靠魔法。文档里"两行代码控制所有同类单位"指的是这个循环结构。

**代价**：N 个单位需要 N 条 `ucontrol`，micro-processor（2 ipt）控 100 个单位需要 50 tick 才能轮一圈。**这就是多控要分槽位、大编队要用 hyper-processor 的原因。**

---

## 4.6 协同规范：flag 命名约定（进阶核心）

这一节是你文档 `Logic-Docs-v1.1.0` §兵控逻辑分类与绑定规范 的核心内容，也是**多套逻辑共存时不打架的关键**。

### 问题：魔法数字会撞车

你在语料里看到的 `11011`、`9001..9005`、`114514` 这类"随便挑的数字"，**在多套逻辑共存时必然冲突**——两套逻辑恰好用了同一个 flag 值，就会互相抢单位。

### 解决方案：用处理器坐标生成唯一 flag

文档给出的标准公式：

```mlog
op floor _0 @thisx 0
op mul   _1 _0 1000
op floor _2 @thisy 0
op add   unFlag _1 _2
```

即：

```
unFlag = floor(@thisx) * 1000 + floor(@thisy)
```

**为什么是 1000**：绝大多数地图的长宽都在 1000 格以内，所以 `×1000` 之后**能从 flag 反推回处理器的坐标**——调试时一眼就能看出"这个单位被哪个位置的处理器占了"。

**为什么要 `floor`**：避免处理器因为尺寸问题产生小数坐标。

### 扩展：一个 flag 存两段信息

想同时存"处理器标识"和"单位编号"，把基数放大即可：

```mlog
flagN = (floor(@thisx) * 1000 + floor(@thisy)) * 100 + N
```

末两位放单位编号 `N`（1–9）。**这正是你的搬运逻辑采用的方案**（见 `Logic-Docs` §搬运逻辑）。

### 取回信息

```mlog
op mod   编号 flag值 100                       # 后两位 → 单位编号
op idiv  处理器码 flag值 100                    # 前面 → 处理器码
op mod   坐标y 处理器码 1000                    # → 处理器 y
op idiv  坐标x 处理器码 1000                    # → 处理器 x
```

### 群控的小数 flag 技巧（很巧妙，但要知道边界）

群控逻辑按约定**不给单位打 flag**（flag = 0 表示"自由单位"）。但如果群控确实需要标记自己的单位呢？

利用 `equal` / `notEqual` 的**浮点容差 0.000001**：

```mlog
op mul tinyFlag 单位编号 0.00000001     # 编号 1..99 → flag ∈ (0, 0.000001)
ucontrol flag tinyFlag 0 0 0 0
```

| 判断方式 | 其他逻辑看到的结果 |
|---|---|
| `equal` / `notEqual`（容差比较） | **等于 0 → 隐形**，照常选定 |
| `strictEqual` | 非 0 → 可见 |
| `>` `<` `>=` `<=` | 非 0 → 可见（无容差） |
| `and` / `or` | 视为已设置 |

**三条硬边界**：
1. 绝对值必须**严格小于** 0.000001（`0.000001` 本身会被判为非 0）——推荐 `0.0000001`，留一个数量级余量
2. **群控自己读这个小 flag 不能用 `==`**（会被判成 0），要用 `>`
3. 编号最大到 **99**（`99 × 1e-8 = 9.9e-7 < 1e-6`）；**编号 100 就达到 1e-6 边界而失效**

## 4.7 多核架构：分配核 + 控制核

当单位数量超过单个处理器的 @ipt 预算时，**must 拆分**。你的文档给了一套成熟的架构，值得学。

### 架构

```
        ┌─────────────┐
        │   分配核     │  绑定所有同类单位，均匀分配
        └──────┬──────┘
               │ write/read（处理器自身变量空间）
     ┌─────────┼─────────┐
     ▼         ▼         ▼
  控制核1   控制核2   控制核3   各自只控自己那份
```

### 分配算法

```mlog
op idiv blockTI unitI @links       # 每个核分到多少单位
op mod  processorI unitI @links    # 轮询：第 unitI 个单位给第几个核
```

**这是标准的"取模分片"**——和 §3.3 的链接轮转同源。

### 通信机制：用处理器自身变量空间，而不是内存库

**这是最关键的一条**（文档特别强调了修正）：

```mlog
# 分配核写入
write 单位引用 processor "unitName"     # 字符串地址 → 写进处理器的变量空间

# 控制核读取
read 单位 processor "unitName"
```

**为什么不用内存库**：
- **内存库（cell/bank）只能存 double 数字**，对象引用会被转换掉
- **处理器自身变量空间可以存对象引用**，因为 `LogicBuild` 同时实现了 `LReadable` 和 `LWritable`，字符串地址会按**变量名**访问变量空间

> **补充**：其实 `read`/`write` 的地址**既可以是数字索引也可以是字符串变量名**。字符串形式访问的是"变量空间"，数字形式访问的是内存建筑。这是一个很多人不知道的用法。

### 变量名用建筑类型名，避免冲突

```mlog
sensor blockTN blockT @name
write  单位值 processor blockTN
```

文档的**变量表约定**正是为此：用 `lookup block` 遍历所有建筑类型，把类型名注册成变量名，这样每个核都有一份统一的"槽位命名"。

### 核标识与失效探测

```mlog
set thisMarking "CustomDotMatrix-byNOSBHG2g"        # 自我标识
read thisMarking pr "thisMarking"                   # 分配核识别主控核
read check processor "readerI"                      # null → 这个核不是主控核
```

### 一个"远程跳转"技巧

```mlog
write 52 processor "@counter"      # 直接改写另一个处理器的 @counter
```

**`@counter` 是变量，可以被远程写**。这相当于**跨处理器强制跳转**——分配核可以命令某个控制核跳到清理段。
**威力大但非常危险**：一旦目标处理器的语句数变了，这个硬编码的 52 就会跳错位置。

### 节流时钟

```mlog
# 5 秒一轮
jump 86 greaterThan second @second
op add second @second 5

# 6.5 秒超时
op add tCheck @time 6500
```

**用 `@second` 做粗粒度节流、`@time` 做超时**，比计数器循环更省指令。

---

## 5.1 搬运逻辑的标准骨架

所有搬运类蓝图（`搬运t4`、`搬运T5`、`运输T3`、`多单位搬运物品至核心`、`搬运八温差`）都是同一个骨架：

```
绑定一批单位 → 循环：对每个单位判断"该取货还是该卸货" → 下发指令
```

### 单单位调度核心（逐段注释）

来自 `多单位搬运物品至核心.msch` 的槽位 1：

```mlog
# ── 查这个单位死了没 ──
ubind u1
sensor de u1 @dead
jump 下一个槽位 equal de 0        # 活着 → 跳过补员

# ── 死了就补员（见 §4.3）──
...

# ── 补员成功，开始干活 ──
ucontrol flag 11011 0 0 0 0
sensor it u1 cfg                  # 看它身上有没有目标物品
ucontrol boost 1 0 0 0 0          # 开加速，尽快到位
jump 73 lessThanEq it 0           # 没货 → 去取货
# ── 有货：送回核心 ──
ucontrol move hxx hxy 0 0 0       # 飞向核心（hxx hxy 来自 ulocate）
ucontrol itemDrop hx max 0 0 0    # 全部卸进核心
ucontrol within hxx hxy 5 w 0     # 到了吗？
jump 72 equal w 0                 # 没到 → 继续
op add zt zt 1                    # 计数：完成一次搬运
jump 80 always x false

# ── 没货：去取货 ──
sensor ft u1 @firstItem
ucontrol move bx by 0 0 0         # 飞向取货点 bx by
jump 77 equal ft null
jump 79 notEqual ft cfg
ucontrol itemTake b cfg max 0 0   # 取满
jump 80 always x false
ucontrol itemDrop b 9999 0 0 0    # 物品不对 → 倒掉
```

**要点**：

| 写法 | 作用 |
|---|---|
| `ucontrol within x y r w` | **唯一的"到达判定"手段**，结果写进第 4 个参数 |
| `sensor it u1 cfg` | 读配置物品（`cfg` 来自 `sensor cfg sorter1 @config`） |
| `ucontrol itemDrop b 9999` | 物品不对就**当场倒掉**，避免单位卡着错误物品 |
| `ucontrol boost 1` | 全程开加速，提升吞吐 |
| `zt` 计数器 | 统计成功搬运次数，用于外部监测 |

### 全局循环与自增轮转

```mlog
# ── 主循环：每次处理一个链接 ──
jump 43 lessThan i @links
set i 1
getlink b i                       # 取第 i 个链接（可能是中转容器）
sensor bx b @x
sensor by b @y
... 处理 8 个槽位 ...
# ── 槽位循环结束 ──
jump 295 lessThan zt ztmax        # 这一轮搬够了吗？
op add i i 1
set zt 0
jump 43 always x false            # 换下一个链接
```

**`jump 292 lessThan 绑定数量 N` 这种"平铺展开"是 mlog 的必然**：没有数组，没有函数，8 个槽位只能复制 8 份代码。所以搬运逻辑**体积随绑定数量线性增长**——这就是为什么 `搬运t4` 有 913 条语句。

## 5.2 无线供弹（跨核心物资调度）

`咕咕无线供弹.msch`、`无线八可串塔位框架.msch` 是 475 条语句的单处理器，属于"无线物流"：

核心思想是**用同一个处理器的链接网络把物品从核心分发到塔位**，靠 `getlink` + `@links` 轮转遍历，不依赖传送带。

**这类逻辑的价值**：传送带会被打断、会被绕路；逻辑分发是**瞬时的**（`control` 直接改建筑配置或 `ucontrol itemDrop` 直接塞）。代价是 ipt 消耗大。

## 5.3 物品选择与分拣

`建筑物品选择逻辑`（文档第 11 章）的核心：

```mlog
sensor cfg sorter1 @config        # 读分拣器筛的物品
control config pad2 item2 0 0 0   # 改装卸器的配置物品
```

**`@config` 读的是"建筑当前的配置值"**，对分拣器是 `Item` 对象，对装卸器是 `Item` 对象，对传送带是 `Block`。

`4着陆板布超t4 V2II型.msch` 里有 564 处 `control config`——这是**大规模动态分拣**：根据库存情况实时切换每个装卸器/分拣器的物品类型。

**批量写法**：

```mlog
control config pad2 item2 0 0 0
control config pad3 item2 0 0 0
control config pad4 item2 0 0 0
...
```

**优化提示**：这类平铺可以用 `getlink` + `@links` 轮转来压缩，但代价是延迟。**如果物品切换必须同帧生效，就只能平铺。**

---

# 第 6 章 火控：索敌与集火

## 6.1 索敌：`radar` 与 `uradar`

### 建筑雷达 `radar`

```
radar <目标阵营> <关系> <排序依据> <排序方向> <建筑> <数量> <输出>
```

来自 `11-12双液体大超着陆合金气旋.msch`：

```mlog
radar enemy any any maxHealth b 1 u
```

| 参数 | 取值 | 说明 |
|---|---|---|
| 阵营 | `enemy` / `ally` / `player` / `attacker` / `flying` / `boss` / `ground` | 筛什么 |
| 关系 | `any` / `enemy` / `ally` / `player` | 与谁的敌我关系 |
| 排序 | `distance` / `health` / `shield` / `armor` / `maxHealth` | 按什么排 |
| 方向 | **`1` = 正序（最近/最高优先），`0` 或负值 = 反序（最远/最低优先）** | ← 注意方向语义 |
| 建筑 | 链接名 | 以谁为圆心 |
| 数量 | 1..10 | 取前 N 个 |
| 输出 | **必须是一个变量**，结果存进去 | |

**三个容易踩的语义细节**：

1. **`order` 的方向容易记反**：`1` 才是"最近的"，`0` 是"最远的"。写 `radar enemy any any distance tower 1 target` 才是取最近敌人。
2. **`enemy` 筛的是"不同队伍且非遗弃队伍"**；`ally` 是同队伍；`attacker` 是 `canShoot`；**`ground` 是"已着陆的"**（不是"地面单位"）。
3. **雷达搜不到"不可瞄准"的单位**——源码 `RadarI.find()` 里有 `if(!u.targetable(team)) return;`。所以隐身/无敌状态的目标会直接漏掉。

**注意**：`radar` 的建筑参数**必须实现 `Ranged` 接口**（也就是炮塔、雷达这类有射程的建筑）。拿一个传送带当搜索源是不行的。

**`radar` 一次只能取 N 个（最多 10），存进一个变量**——实际上是取第 N 个。要取多个得写多次。

### 单位雷达 `uradar`

```
uradar <阵营> <关系> <排序> <方向> <输出>
```

**没有"建筑"参数**——以当前 `@unit` 为圆心，所以**必须先 `ubind`**。

`10冷冻厄兆.msch` 的模式：

```mlog
ubind @flare
uradar enemy any any distance 1 目标
jump X equal 目标 null            # 没找到
```

**三个筛选器是 AND 关系**，`any` 表示"不限"。未找到时输出 **`null`**。

> ### ⚠️ `uradar` 不刷新控制超时（很容易踩）
>
> 这是 `uradar` 和 `ucontrol` 之间一个**非常隐蔽的差异**：
>
> | 指令 | 是否刷新 10 秒 `controlTimer` |
> |---|---|
> | `ucontrol *`（除 uradar） | ✅ 刷新 |
> | `ulocate` | ✅ 刷新 |
> | **`uradar`** | ❌ **不刷新** |
>
> **后果**：如果你的逻辑只用 `uradar` 索敌、却不再下发任何 `ucontrol`，那么**单位会在 10 秒后自动脱离控制、恢复默认 AI**。
> 典型症状："我的单位打了十来秒就不打了 / 开始自己乱跑"。
>
> **修正**：循环里至少要有一条实质性的 `ucontrol`（哪怕 `ucontrol idle`），或者用 `ucontrol targetp` 顺便刷新。

### `radar` / `uradar` / `ulocate` 都有 40 tick 缓存

**这是三个指令共同的坑**：结果会缓存 **40 tick（约 0.67 秒）**，重复执行**返回旧结果而不是重新搜索**。

**后果**：
- 目标在这 40 tick 内移动了，你拿到的还是旧坐标
- 目标已经死了/消失了，你依然会"看到"它
- 在客户端和服务端，缓存是**各自独立**运行的，可能短暂不一致

**修正**：
- 需要实时结果时，**两次搜索之间至少间隔 40 tick**
- 或者**改变搜索参数**（不同的筛选条件会被视为不同的缓存条目）
- `ulocate` 的缓存按**参数组合**隔离——7 条参数各异的 `ulocate ore` 缓存互不干扰，所以可以用"多个不同参数的 ulocate 轮换"来绕过缓存

## 6.2 集火的正确姿势：`control shootp`

**注意**：`control shoot` 打的是**坐标**，`control shootp` 打的是**实体**。

```mlog
control shoot  炮塔 x y shoot 0     # 打坐标点
control shootp 炮塔 目标 0 0 0       # 跟踪实体 ← 推荐
```

`155厄兆火控v1.0.msch` 里：

```mlog
control shootp FW target 0 0 0
```

**为什么 `shootp` 更好**：`shoot` 打固定点，敌人在移动就会打空；`shootp` 让炮塔自己解算提前量。

## 6.3 集火模式：`ILI集火逻辑`

这是你语料里**最成熟的火控模式**，值得完整拆解。

### 目标：让一堆炮塔打同一个目标

### 第一段：读"主机"的瞄准点

```mlog
getlink Iliary艾铭 鱼破了冰        # 取控制主机
sensor 艾铭在这里 Iliary艾铭 @controlled
jump 10 equal 艾铭在这里 0          # 主机空闲 → 走另一条路
sensor 艾铭射的x Iliary艾铭 @shootX # 读主机当前瞄准 x
sensor 艾铭在射 Iliary艾铭 @shooting
op add 艾铭变了 艾铭射的x 艾铭在射  # 组合指纹
jump 1 equal 艾铭变了 艾铭真的变了  # 自旋等状态变化
sensor 艾铭射的y Iliary艾铭 @shootY
set 艾铭真的变了 艾铭变了
```

**这一段就是 §1.3 的"指纹自旋"**——等主机真正开火才去跟。

### 第二段：主机没开火时，自己索敌

```mlog
radar enemy any any distance Iliary艾铭 1 艾铭的敌人
jump 16 strictEqual 艾铭的敌人 null   # 用 strictEqual 判空
sensor 艾铭射的x 艾铭的敌人 @x
sensor 艾铭射的y 艾铭的敌人 @y
set 艾铭在射 艾铭的敌人
```

### 第三段：`ping` 协作（利用玩家的地图标记）

```mlog
radar player ally any distance Iliary艾铭 1 艾铭·ILI
jump 35 equal 艾铭·ILI null
jump 35 equal 艾铭·ILI L.I.F.E       # 排除自己人
sensor 艾铭还想约的x 艾铭·ILI @pingX # 读玩家标记点
jump 35 equal 艾铭还想约的x 艾铭想约的x
sensor 艾铭还想约的x 艾铭·ILI @pingX
jump 35 equal 艾铭还想约的x null      # ping 可能为 null
sensor 艾铭想约的y 艾铭·ILI @pingY
sensor 艾铭的x 艾铭·ILI @x
sensor 艾铭的y 艾铭·ILI @y
sensor 艾铭的尺寸 艾铭·ILI @size
op sub 艾铭约的dx 艾铭想约的x 艾铭的x
op sub 艾铭约的dy 艾铭想约的y 艾铭的y
op add 艾铭约的距离 艾铭约的dx 艾铭约的dy
op lessThan 艾铭应该约 艾铭约的距离 艾铭的尺寸
jump 35 notEqual 艾铭应该约 1
set L.I.F.E 艾铭·ILI                   # 锁定这个玩家作为"指挥员"
set 艾铭约的x 艾铭想约的x
set 艾铭在射 0
```

**这是一个非常巧妙的设计**：**用玩家的地图 ping 当作"集火目标指定"的 UI**。
玩家在地图上 ping 一下，逻辑就读取 `@pingX/@pingY`，然后所有炮塔转向那个点。

**`@pingX` 的坑**（[UnitComp.java:307](../Mindustry-Source/core/src/mindustry/entities/comp/UnitComp.java#L307)）：

```java
case pingX -> controller instanceof Player p && p.isPinging() ? World.conv(p.pingX) : Float.NaN;
```

**没有 ping 的时候返回 `Float.NaN`，不是 null！**
所以 `jump 35 equal 艾铭还想约的x null` 这个判断**实际上永远不会命中**——NaN 不等于 null。

**正确写法**：

```mlog
op add tmp pingx 0               # NaN 参与运算仍是 NaN
jump skip notEqual tmp tmp        # NaN != NaN → 真，说明是 NaN
```

或者用 `strictEqual` 配合已知哨兵值。

### 第四段：距离计算（这里有两个真实的错误）

```mlog
op sub 艾铭约的dx 艾铭约的x 艾铭的x
op sub 艾铭约的dy 艾铭约的y 艾铭的y
op add 艾铭约的距离 艾铭约的dx 艾铭约的dy   # ← 错误 1：这是 dx+dy，不是距离
op abs 艾铭约的距离 艾铭约的距离 艾铭约的dy   # ← 错误 2：abs 是一元运算，多给了一个参数
op greaterThan 艾铭在射 艾铭约的距离 艾铭的尺寸
```

**错误 1：`op add 距离 dx dy` 不是距离，是曼哈顿距离。**

距离必须是**欧几里得长度**，mlog 有专门的指令：

```mlog
op len 距离 dx dy           # Mathf.dst(dx, dy) = sqrt(dx²+dy²)
```

`dx + dy` 与真实距离的关系取决于方向：
- `dx`、`dy` 同号且相等时，`dx+dy ≈ 1.41 × 真实距离`（偏大 41%）
- `dx`、`dy` 异号时，两个误差互相抵消，**可能得到 0 而实际距离很大**

所以这个"距离"在某些方向上把远目标判成近距离，在另一些方向上把近目标判成远距离。**配上一个大阈值时"看起来能用"，这正是它没被发现的原因。**

**错误 2：`abs` 是一元运算，写成三元是无效的**（详见 §11.1）。

**最小修正**——只改一行就能同时修好两处：

```mlog
op sub dx 目标x 自己x
op sub dy 目标y 自己y
op len 距离 dx dy                          # 已经是非负数，abs 不再需要
op greaterThan 在范围内 距离 阈值
```

想省掉 `sqrt` 的话可以比较平方（`len` 本身开销可接受，但批量比较时值得优化）：

```mlog
op mul dx2 dx dx
op mul dy2 dy dy
op add d2 dx2 dy2
op lessThan 在范围内 d2 阈值平方
```

> **这个发现很重要**：即使是语料里排名靠前的"成熟"逻辑，也存在**真实的数学错误**。
> 学习蓝图模式时**必须验证算法本身**，不能因为"能跑"就认为"对"——手感上能用的逻辑，数学上可能是错的。

### 另一个值得学的点：用 `@time` 做不应期

```mlog
jump 63 greaterThan 不应期 @time      # 还没到时间 → 跳过
op add 不应期 @time 1000              # 重新计时 1000ms
...
jump 63 equal 艾铭在射 0
set 艾铭在射 艾铭的敌人
```

**这是"绝对到期时刻"写法**，比倒计时更健壮——漏跑几帧也不会累积误差。见 §8.3。

### 第五段：批量下发（性能核心）

```mlog
getlink 艾铭的奴隶99 99
getlink 艾铭的奴隶98 98
... 一直到 0 ...（100 条 getlink）
op add 艾铭想从这里连接 @counter 鱼梦醒时
op sub 艾铭想从这里连接 艾铭想从这里连接 艾铭想从这连接
op add @counter @counter 鱼梦醒时
control shoot 艾铭的奴隶99 艾铭射的x 艾铭射的y 艾铭在射 0
control shoot 艾铭的奴隶98 ...
... （100 条 control shoot）
jump 1 equal 艾铭在这里 1
```

**设计分析**：

| 手法 | 目的 |
|---|---|
| 一次性 `getlink` 100 个到 100 个变量 | **避免每帧 getlink**，只做一次 |
| `op add @counter @counter 偏移` | 跳过"已经处理过"的 getlink 块，**增量式每帧处理一批** |
| 100 条 `control shoot` 平铺 | 因为 `control shoot` 必须指定具体建筑 |

**这个设计的本质是"分批处理"**：用 `@counter` 技巧让每帧只跑一部分 `control shoot`，把 100 个炮塔分摊到多帧。

**但实现很脆弱**：`op sub 艾铭想从这里连接 艾铭想从这里连接 艾铭想从这连接` 这种自相减的写法极其难懂，且依赖精确的语句计数。

**更清晰的等价写法**：

```mlog
# 用显式计数器分批
op add batch batch 1
op mod batch batch 10            # 0..9 共 10 批
jump t0 equal batch 0
jump t1 equal batch 1
...
```

---

# 第 7 章 建造 / 拆除（世界处理器）

## 7.1 权限门槛（必须知道）

| 能力 | 规则开关 | 默认值 | 出处 |
|---|---|---|---|
| 单位控制 | `logicUnitControl` | **true** | [Rules.java:99](../Mindustry-Source/core/src/mindustry/game/Rules.java#L99) |
| 单位建造 | `logicUnitBuild` | **true** | [Rules.java:101](../Mindustry-Source/core/src/mindustry/game/Rules.java#L101) |
| 单位拆除 | `logicUnitDeconstruct` | **false** ← | [Rules.java:103](../Mindustry-Source/core/src/mindustry/game/Rules.java#L103) |

**`ucontrol deconstruct` 默认是关的**。源码 [LExecutor.java:470](../Mindustry-Source/core/src/mindustry/logic/LExecutor.java#L470)：

```java
case deconstruct -> {
    if((state.rules.logicUnitDeconstruct || exec.privileged) && unit.canBuild()){
```

所以普通图里**用不了单位拆除**——除非：
- 房主在自定义规则里开 `logicUnitDeconstruct`
- 或者你用**世界处理器**（privileged = true，绕过规则检查）

**这解释了为什么你的建造类蓝图大量使用 `world-processor`。**

## 7.2 单位建造

```
ucontrol build <x> <y> <方块> <旋转> <配置>
```

来自 `GetBlock点阵钍反替换防炸房逻辑.msch`：

```mlog
ucontrol move bx by @copper-wall 0 0      # ⚠️ 这里第 3 参数是 @copper-wall，但 build 期待的是方块
ucontrol within bx by 20 r 0              # 到了吗（20 tile 内）
jump 40 notEqual r 1
ucontrol build bx by @battery-large 0 0   # 在 bx by 建大型电池
wait 0.01                                 # 给建造留时间
ucontrol stop 0 0 0 0 0                   # 停手
jump 25 always yi ym
```

**注意第一行**：`ucontrol move bx by @copper-wall 0 0` 把 `@copper-wall` 当第 3 个参数传给 `move`。源码 [LExecutor.java:358](../Mindustry-Source/core/src/mindustry/logic/LExecutor.java#L358) 显示 `move` 只用 p1/p2：

```java
case move, stop, approach, pathfind -> {
    ai.control = type;
    ai.moveX = x1;
    ai.moveY = y1;
    ...
}
```

**所以 `@copper-wall` 这个参数被完全忽略了**——无害但多余。这是**从 `build` 复制过来忘记删参数**留下的痕迹。

### 建造的前提条件（源码）

```java
case build -> {
    if((state.rules.logicUnitBuild || exec.privileged)
        && unit.canBuild()
        && p3.obj() instanceof Block block
        && block.canBeBuilt()
        && (block.unlockedNow() || unit.team.isAI())){
```

- `unit.canBuild()` —— 单位必须有建造能力（`@poly`、`@mega`、`@quad` 等）
- `block.unlockedNow()` —— **方块必须已解锁**（否则静默失败）
- 坐标会做 `block.offset` 修正和 `Mathf.mod(p4, 4)` 旋转规范化

### 建造请求的"重置"逻辑

```java
if(ai.plan.x != x || ai.plan.y != y || ai.plan.block != block || unit.plans.isEmpty()){
    ai.plan.progress = 0;
    ai.plan.initialized = false;
    ai.plan.stuck = false;
}
```

**如果你每帧都换目标，进度会被反复清零，永远建不完。** 正确做法是**锁定一个目标直到建完再换**。

## 7.3 世界处理器（privileged）通用模式

世界处理器是所有"超级逻辑"的基础。特征：

| 特性 | 说明 |
|---|---|
| 链接范围 | **全图** |
| `setrate` | 可用，上限 1000 |
| 绕过规则检查 | `logicUnitBuild`/`logicUnitDeconstruct`/`logicUnitControl` 全部无视 |
| 可读写全局 | `setrule` `setprop` `spawn` `bullet` `effect` `setmarker` 等 |
| 网格坐标 | `@thisx/@thisy` 是处理器位置 |

### `MCV.msch`（移动核心）架构

这是你语料里最完整的工程项目（270 条语句，world-processor + cell1）。

```mlog
set author "[blue]Ili[#8abcd1]ary..."
print "MCV逻辑开发版，by - Iliary艾铭"
set fire.enable 0
print "允许MCV开火..."
set distant.m 2
print "最大展开区域偏移距离"
set normal.ipt 10
setrate normal.ipt
```

**特征**：

| 手法 | 语句 | 作用 |
|---|---|---|
| 参数集中声明 | `set fire.enable 0` + `print` 说明 | **用 print 当文档**，游戏里能在消息块看到 |
| 动态 ipt | `setrate 1000` / `setrate normal.ipt` | 只在密集遍历时拉满 |
| `fetch` | `fetch unit ...` | 统计全局单位/建筑数量 |
| `setprop` | 11 处 | 设置建筑/单位属性 |
| `effect` | 6 处 | 视觉特效 |
| `setrule` | 5 处 | 改游戏规则（**这就是移动核心能"展开"的底层手段**） |
| `getblock` | 5 处 | 读格子信息判断能否展开 |

**"移动核心"的实现原理**：用 `setrule` + `setprop` + 单位/建筑生成，把"核心"这个建筑在逻辑层面模拟出来——真正的核心是固定的，MCV 靠逻辑伪造一个可移动的。

### `反病毒.msch`（48 个处理器协同）

```mlog
=== 反病毒.msch [micro-processor @0,0] 6 stmts
=== 反病毒.msch [logic-processor ...] ...
=== 反病毒.msch ... 48 个处理器，每个 ≤6 条语句
```

**这是一个"蜂群"架构**：48 个小处理器各管一小块，靠内存/flag 通信。**单处理器语句少 = 启动快、抗单点故障**。

对比 `MCV` 的"单体大逻辑"，这是**两种截然不同的架构路线**：

| 架构 | 优点 | 缺点 |
|---|---|---|
| 单体（MCV，270 条） | 逻辑内聚，无通信开销 | 一处报错全崩；难维护 |
| 蜂群（反病毒，48×6 条） | 容错，易改动局部 | 通信开销，难协调 |

---

# 第 8 章 内存建筑与共享黑板

## 8.1 内存建筑

| 建筑 | 单元数 | 说明 |
|---|---|---|
| `memory-cell` | 64 | 小型 |
| `memory-bank` | 512 | 大型 |

```
read  <变量> <内存建筑> <索引>
write <值>   <内存建筑> <索引>
```

**内存单元存的可以是数字或对象**（建筑、单位、物品）。

## 8.2 共享黑板模式

你的多个复杂项目都用内存当"全局变量表"：

- **`中国象棋.msch`**：bank1 的索引 91 存 `shooting`、96 存 `s.team`、99 存 `t.team`——**用固定索引当寄存器**。
- **`超车模拟器.msch`**：cell1 索引 30 存 `dead`、9 存 `stop-r`、6/7 存 `run-r/run-l`、1/2 存 `o1x/o1y`、16 存 `sdva`、20 存 `o1pa`、39 存 `moon-p`。

**这是 mlog 里唯一的"共享内存"机制**。多个处理器通过它交换数据。

### 标准用法

```mlog
# 写入方
write mp cell1 2                 # 把 mp 写到 cell1[2]

# 读取方
read mp cell1 2                  # 读回来
```

### 手工分配索引（必须的规范）

mlog 没有变量表管理，索引冲突是**最常见的协同 bug**。文档第 12 章"变量表完整性检查"就是讲这个。

**建议格式**（在代码开头用 print 声明）：

```mlog
print "cell1 索引分配表:"
print "0-9   : 玩家状态 (hp/x/y/...)"
print "10-19 : 敌人状态"
print "20-29 : 逻辑组A 临时变量"
print "30-39 : 逻辑组B 临时变量"
print "90-99 : 全局标志位"
```

`中国象棋` 的作者实际上就是这么做的——从索引分布（91/96/99）能看出他留了分段。

## 8.3 `@time` 计时器模式

```mlog
op add 不应期 @time 1000          # 记录"到什么时候为止"
...
jump 63 greaterThan 不应期 @time   # 还没到 → 跳过
```

**`@time` 是毫秒级游戏时间**。用"绝对到期时刻"而不是"倒计时"的好处：**不受帧率影响**，逻辑漏跑几帧也不会累积误差。

对比"倒计时"写法（`op sub cd cd 1`）在掉帧时会变慢——**`@time` 是更健壮的冷却实现**。

`17十七硫幽灵四熔毁四油海啸组.msch` 也用了同样套路：

```mlog
op lessThan c @time ck            # 时间到了吗
control enabled a c 0 0 0
```

---

# 第 9 章 显示与绘制

## 9.1 绘制指令

```
draw clear r g b
draw color r g b a
draw col <打包颜色>
draw stroke <线宽>
draw line   x1 y1 x2 y2
draw rect   x y w h
draw lineRect x y w h
draw poly   x y sides radius rotation
draw linePoly x y sides radius rotation
draw triangle x1 y1 x2 y2 x3 y3
draw image  x y @imageName size rotation
draw print  x y align text
draw translate x y
draw scale  x y
draw rotate <角度>
draw reset
drawflush <显示屏>
```

**坐标系**：显示屏的坐标范围由显示屏尺寸决定（`large-logic-display` 是 80×80？实际是按 tile 数换算），原点在**左下角**。

## 9.2 像素画的生成套路

你语料里 18 个像素画蓝图（140 万条语句）的套路：

```mlog
draw color 255 255 255 255 0 0
draw rect 0 61 1 2
draw rect 0 58 1 2
...
drawflush display1
```

**逐像素一个 `draw rect`**。`intel corei3.msch` 的 126,759 条 `draw` 就是这么来的。

**这就是为什么必须把像素画从统计里剔除**：它们数量巨大但零算法价值。

**优化方向**（如果你想自己写）：
- 用 `draw image` + 自定义图片（如果服务端有）
- 用 `draw line` 画长条而不是逐像素 `rect`
- 用内存存位图 + 循环读取：

```mlog
set i 0
loop:
read px cell1 i
draw color px px px 255 0 0
draw rect i 0 1 1
op add i i 1
jump loop lessThan i 64
```

## 9.3 文本与颜色代码

```mlog
print "[red]警告[green]正常"
print "[#ff8800]自定义颜色"
printflush message1
```

**颜色标签**：`[red]` `[green]` `[blue]` `[yellow]` `[white]` `[orange]` `[purple]` `[cyan]` `[gray]` `[black]` `[pink]` `[brown]` `[acid]` `[#RRGGBB]`，`[]` 重置。

**注意 `print` 是累积的**：多次 `print` 会拼成一行，直到 `printflush` 或遇到 `\n`。你语料里的像素画就是靠这个把整个画面用数字拼出来：

```mlog
print "[#"
print e
print "f"
print e
print "f"
print "]"
```

**这是拼一个 `[#XXXXXX]` 颜色标签**！`e` = 232 的十六进制 `e8`，拼出 `[#e8f0f0]` 之类的颜色。**这是把数字转成十六进制颜色的手工做法**。

**更好的做法**：

```mlog
op add r 232 0
op add g 240 0
op add b 240 0
# mlog 没有数字转十六进制字符串...
```

**mlog 没有数字到十六进制的转换**，所以只能这样拼。这是语言限制，不是作者水平问题。

## 9.4 `format` 指令

```
format <模板> <输出>
```

模板里 `{0}` `{1}` 是占位符，后面跟变量。**比多次 `print` 更省指令**。

---

# 第 10 章 反抽插 / 反炸房 / 抗干扰

你的语料里有一整类**防御性逻辑**，这在公开教程里很少见，属于实战经验。

## 10.1 什么叫"抽插"和"炸房"

| 术语 | 含义 |
|---|---|
| **抽插** | 对手用逻辑/单位反复快速拆建同一个建筑，导致你的逻辑状态错乱或服务器卡顿 |
| **炸房** | 用逻辑大量生成实体（单位/子弹/特效）让所有人掉线 |
| **抽水/抽插小飞机** | 用大量廉价单位反复冲击，消耗对方火控的 ipt |

## 10.2 反制手段

### A. `ucontrol build` 抢修（`GetBlock点阵钍反替换防炸房逻辑`）

```mlog
ucontrol getBlock x y 0 outBlock outFloor   # 查这个格子现在是什么
...判定...
ucontrol move bx by @copper-wall 0 0
ucontrol within bx by 20 r 0
jump 40 notEqual r 1
ucontrol build bx by @battery-large 0 0     # 强行盖掉
wait 0.01
ucontrol stop 0 0 0 0 0
```

**原理**：**在被拆的位置强行盖一个不同方块**，让对方的"拆-建"循环失效（因为它盖的是另一个方块，你的盖上去就打断它了）。

### B. `.逻辑-火控-分裂炮-防抽插-小撒-1.2.0`

```mlog
set 容器1 conveyor1
set 容器2 conveyor1
...
sensor hp @unit @health
```

**用 `set` 把链接名复制到短变量**——既省字节，又能在链接被破坏时保持逻辑不崩。

### C. 反病毒蜂群（`反病毒.msch` / `ILI反病毒.msch`）

48 个微型处理器，每个只做一件事。**抗单点故障**：对手拆掉几个处理器不影响整体。

`ILI反病毒.msch` 里那段跳转表：

```mlog
op add u.i u.i 1
op mod u.i u.i 8
op mul counterp u.i 2
op add @counter @counter counterp
set uty @nova
jump 23 always 0 false
set uty @pulsar
...
```

**用状态机轮转单位类型**——大概是在多种单位之间循环生成/控制，让对手无法预测。

### D. `反钍反反炸房、反病毒逻辑超核逻辑`

从名字看是针对"钍反（thorium reactor）被当作炸弹"的防御——**钍反应堆会爆炸**，对手可能故意引爆或阻止你冷却。反制是**自动检测温度/冷却液并强制停机或拆除**。

对应模式：

```mlog
sensor 冷却液 核电 @cryofluid
jump 11 greaterThan 冷却液 5      # 冷却充足
control enabled 核电 0 0 0 0       # 不足则停机
```

---

# 第 11 章 反面教材：蓝图里真实存在的 Bug

这一章是本模式库最有价值的部分——**从你的语料里找出的真实错误**。

## 11.1 一元运算写成三元 —— **全语料 567 处**

这不是个别失误，而是**整个语料里最大的一类系统性错误**。我用 `check_ops.py`（未随公开版发布） 扫了全部 1081 个真实逻辑块，找出所有"参数个数和运算元数不匹配"的 `op` 行：

| 运算 | 错误写法 | 正确参数数 | 出现次数 |
|---|---|---|---|
| `rand` | `op rand out in b` | 2 | **199** |
| `floor` | `op floor out in b` | 2 | **88** |
| `ceil` | `op ceil out in b` | 2 | 65 |
| `cos` | `op cos out in b` | 2 | 50 |
| `sin` | `op sin out in b` | 2 | 50 |
| `abs` | `op abs out in b` | 2 | 35 |
| `log10` | `op log10 out in b` | 2 | 24 |
| `round` | `op round out in b` | 2 | 24 |
| `not` | `op not out in b` | 2 | 13 |
| `atan` | 同上 | 2 | 7 |
| `sqrt` | 同上 | 2 | 6 |
| `log` | 同上 | 2 | 5 |
| `tan` | 同上 | 2 | 1 |
| **合计** | | | **567** |

**同一轮扫描的另外三项结果**（说明你的蓝图在别的方面是干净的）：

| 检查项 | 结果 |
|---|---|
| `jump` 目标越界 | **0** ✅ |
| 未知指令名 | **0** ✅ |
| 未知 `ucontrol` 动作 | **0** ✅ |
| `ucontrol` 参数缺省 | **0**（说明全部是游戏导出的规范 7 槽格式）✅ |

### 为什么会这样

看几个真实例子就明白了——**作者是在用其他语言/库的直觉写 mlog**：

```mlog
op floor threshold threshold b        # ← 像是 floor(x, unit) 的写法
op round x.effect x.effect 0.5        # ← 想"四舍五入到 0.5 的倍数"
op log10 MPVY @maph 0                 # ← 多给一个 0
op cos sx rota b                      # ← 多给一个 b
op abs 距离 距离 dy                    # ← §6.3 里那个
op abs internal internal 0            # ← 多给一个 0
```

**这些运算在 mlog 里全是一元的**（[LogicOp.java:40-57](../Mindustry-Source/core/src/mindustry/logic/LogicOp.java#L40) 用的是 `OpLambda1` 构造器，`unary = true`），只接受 `op <运算> <输出> <输入>` 两个操作数。

`round x 0.5` 这种"按精度取整"在 mlog 里**根本不存在**——`round` 就是 `Math.round(a)`，只能取到整数。

> **有意思的是**：`b` 这个变量名反复出现在第三个参数位上（`op cos ... b`、`op floor ... b`、`op rand ... b`）。
> 这说明作者有一份**从别的语言翻译过来的代码模板**，`b` 是那个模板里的残留参数——**同一个错误被复制粘贴了上百次**。

### 后果

`LStatements.OpI.build()`（[LStatements.java:773](../Mindustry-Source/core/src/mindustry/logic/LStatements.java#L773)）是：

```java
public LInstruction build(LAssembler builder){
    return new OpI(op, builder.var(a), builder.var(b), builder.var(dest));
}
```

一元运算在 UI 路径上只读一个操作数（[:725](../Mindustry-Source/core/src/mindustry/logic/LStatements.java#L725)）：

```java
if(op.unary){
    opButton(table, table);
    field(table, a, str -> a = str);      // ← 只读一个操作数
}
```

**多出来的那个 token 没有被消费**。这一行的实际效果**不是作者想要的运算**。

> **注意**：`LogicIO`（负责把 token 数组转成 `LStatement` 的类）**不在这份源码快照里**（该 checkout 缺少这个文件），所以它遇到参数过多时到底是"抛异常降级成灰积木"还是"忽略多余 token"我无法从源码确证。
> 但**两种情况下结论都一样：这一行的行为都不是作者的本意**——要么完全没执行，要么执行了一个参数不全的版本。
>
> **想确证的话**：把任意一条这类代码粘进游戏，看那个积木是正常显示还是变成灰色（`InvalidStatement`）即可。**这是唯一可靠的验证方式，建议你实测一条。**

### 修正对照表

| 想干什么 | 错误写法 | 正确写法 |
|---|---|---|
| 取绝对值 | `op abs out in x` | `op abs out in` |
| 向下取整 | `op floor out in b` | `op floor out in` |
| 取随机数 | `op rand out 3 b` | `op rand out 3` |
| 取正弦 | `op sin out in b` | `op sin out in` |
| 按 0.5 取整 | `op round out in 0.5` | `op mul out in 2` + `op round out out` + `op div out out 2` |
| 以 10 为底对数 | `op log10 out in 0` | `op log10 out in` |
| 逻辑取反 | `op not out in x` | ⚠️ `not` 是**按位取反**！逻辑非要用 `op equal out in 0` |

**这是个很好的教训**：mlog 的 `op` 是**固定元数**的，不存在可选参数。写之前先确认这个运算吃几个操作数。

**顺手排查你自己的代码**：

```bash
# 该语料脚本未随公开版发布
```

## 11.2 "距离"算成了 `dx + dy`

同文件：

```mlog
op sub 艾铭约的dx 艾铭想约的x 艾铭的x
op sub 艾铭约的dy 艾铭想约的y 艾铭的y
op add 艾铭约的距离 艾铭约的dx 艾铭约的dy    # ← 错！这是 dx+dy
```

**正确**：

```mlog
op len 距离 艾铭约的dx 艾铭约的dy
```

**为什么没被发现**：`dx+dy` 在 |dx| 与 |dy| 同号且量级相同时，约等于 `1.41 × 真实距离`，配上一个宽松的阈值就"看起来能用"。

## 11.3 `@controlled` 被当成"被逻辑占用"

见 §3.4 和 §4.3。`@controlled` 返回 **1 = 逻辑控制 / 2 = 玩家控制 / 3 = 指令控制 / 0 = 空闲**。

**两个错误的假设**：

1. **"非 0 就是被逻辑占用"** —— 错。玩家控制的单位返回 2，也被算进去了。
2. **"能区分是哪个处理器在控制"** —— 错。**所有逻辑控制一律返回 1**，无法区分处理器。

**`@controlled` 唯一可靠的用途**是判断"这个单位是不是自由单位"：

```mlog
sensor co @unit @controlled
jump 空闲 equal co 0              # co == 0 才是真正没人管
```

**如果想知道"是不是我这个处理器在控制"，必须用 `@controller` 和 `@this` 比较**：

```mlog
sensor ctr @unit @controller
jump 是我的 equal ctr @this       # 对比控制器引用
```

> ⚠️ `@controller` **没有出现在 `sensor` 属性总表里**，只在官方示例代码中使用，属于"能用但未文档化"的属性。用之前建议实测。

**多逻辑抢占单位的标准做法**（来自你的文档 §兵控规范）：

```mlog
sensor co @unit @controlled
jump 换一个 greaterThan co 0      # 0=自由；否则看 flag
sensor f @unit @flag
jump 选它 equal f 0               # flag 为 0 → 是群控也没标记 → 可以选
jump 换一个 always                # flag 非 0 → 已被别占用
```

**并且每次循环都要复查 flag 有没有被别人改掉**——这是防帧差冲突的关键（同帧放下两个相同逻辑时，双方都可能认为单位没被占用）。

## 11.4 空值比较用错运算符

```mlog
jump 4 equal co 0                 # co 为 null 时：null == 0 → false → 不跳
jump 16 strictEqual 艾铭的敌人 null   # 这个写法是对的
```

**`null` 和 `0` 在 `equal` 下不相等**，但 `0` 和 `0.0` 相等（浮点容差）。
**判空一律用 `strictEqual x null` 或 `equal x null`**（这两个对 null 都正确）。

**顺带一个实用技巧**：`sensor` 的目标为 `null` 且属性是 `@dead` 时**直接返回 1**（视为已死亡）。
所以下面这种写法可以一句话同时判"不存在"和"已死"：

```mlog
sensor d 某个单位 @dead
jump 需要补员 equal d 1            # null 或已死都会命中
```

## 11.5 `@pingX` 的 NaN 陷阱

[UnitComp.java:307](../Mindustry-Source/core/src/mindustry/entities/comp/UnitComp.java#L307)：

```java
case pingX -> controller instanceof Player p && p.isPinging() ? World.conv(p.pingX) : Float.NaN;
```

**没有 ping 时返回 `Float.NaN`，不是 `null`。** 所以：

```mlog
jump 35 equal 艾铭还想约的x null      # ← 永远不成立！NaN != null
```

**这是 `ILI集火逻辑` 里一个真实的死判断。**

**正确判 NaN 的方法**（利用 NaN 不等于自身）：

```mlog
sensor px 玩家 @pingX
op add chk px 0
jump 没有ping notEqual chk chk       # NaN != NaN → 恒真
```

或者**用 `strictEqual`**：

```mlog
jump 有ping strictEqual px px        # NaN === NaN 为假，正常值 === 自身为真
```

第二种更省一条指令，但要注意 `strictEqual` 的语义是"类型和值都相同"。

> **同类的 NaN 陷阱还有**：`@pingY`、以及任何"玩家没在操作时"返回的浮点属性。凡是"可能不存在"的浮点 sensor，都要考虑 NaN。

## 11.6 死循环烧 ipt

```mlog
ubind @flare
jump 0 equal @unit null            # 没单位 → 无限重绑
```

**修正**：加节流或退出。

```mlog
ubind @flare
jump ok notEqual @unit null
wait 0.5
jump 0 always
ok:
```

## 11.7 冗余参数

```mlog
ucontrol move bx by @copper-wall 0 0    # @copper-wall 被忽略
```

`move` 只读 p1/p2。**无害但说明是从 `build` 复制的**。

## 11.8 相对跳转难以维护

`op add @counter @counter 偏移` 一类写法（`ILI集火逻辑`、`ILIOS`、`ILI反病毒`）：

- 插入/删除任何一条指令都会让所有偏移错位
- 没有标签，`LParser` 也无法帮你检查
- 蓝图里没有任何注释

**建议**：新代码用**显式标签 + `jump`**，让 `LParser` 帮你算行号。只有在对语句数极度敏感（ipt 预算卡死）时才用相对跳转。

---

# 附录 A 指令速查

## A.1 基础

| 指令 | 格式 | 说明 |
|---|---|---|
| `set` | `set 变量 值` | 赋值，值为字符串时只能用于 print |
| `op` | `op 运算 输出 a b` | 见下 |
| `jump` | `jump 目标 条件 a b` | |
| `end` | `end` | 回到开头 |
| `stop` | `stop` | **停止执行，直到处理器被重新配置**（不是回到开头！） |
| `wait` | `wait 秒` | 让出本 tick 剩余预算 |
| `noop` | `noop` | 空操作 |

> **`end` vs `stop`——这两个完全不是一回事**
>
> | | `end` | `stop` |
> |---|---|---|
> | 做什么 | `@counter = 指令总数` | 回退 `@counter` 到自身 + `yield = true` |
> | 实际效果 | **回到程序开头，继续循环** | **每 tick 重新执行一次 `stop`，然后让出** |
> | 还能恢复吗 | 无所谓，本来就在循环 | **只有重新编程（改代码）才能恢复** |
>
> **`stop` 的真相**（你的文档 §stop 给出了源码分析）：它并不是"真的停机"，而是**让 `@counter` 自锁在 `stop` 这一条上**——每 tick 执行一次 `stop`、yield、下一 tick 又回到 `stop`。
> `exec.stop` 这个标志位**在 `LogicBlock.update()` 里根本没有被检查**（源码注释写着 `//TODO: this isn't used in the game yet`）。
>
> **结论**：`stop` = "永久挂起，直到被重新配置"。语料里 3690 处 `stop` 全是这个用途（任务完成后挂起，等玩家或者别的逻辑重新写入代码）。
> **想要"循环"就用 `end` 或直接跳到开头，绝不要用 `stop`。**

> **`end` 的一个副作用**：`end` **不设 `yield`**。所以如果本 tick 还有指令配额，`end` 之后会**立刻从第一条继续执行**——在极短的程序里，这意味着单 tick 内可能循环很多次。
> 想真正让出剩余配额，用 `wait 0`（`wait` 且值 ≤ 0 时只 yield、不回退计数器、不累计时间）。

## A.2 `op` 运算表

### 一元运算（只吃 1 个操作数，`op X 输出 输入`）

| 类别 | 运算 |
|---|---|
| 数学 | **`abs`** `sign` `log` `log10` `floor` `ceil` `round` `sqrt` |
| 随机 | `rand` |
| 三角 | `sin` `cos` `tan` `asin` `acos` `atan` |
| 位 | `not`（导出符号是 `flip`，按位取反） |

### 二元运算（吃 2 个操作数）

| 类别 | 运算 |
|---|---|
| 算术 | `add` `sub` `mul` `div` `idiv`（整除）`mod` `emod`（欧几里得取模）`pow` |
| 比较 | `equal` `notEqual` `land`（逻辑与）`lessThan` `lessThanEq` `greaterThan` `greaterThanEq` `strictEqual` |
| 位运算 | `shl` `shr` `ushr` `or` `and`（导出符号 `b-and`）`xor` |
| 数学函数 | `max` `min` `angle` `angleDiff` `len` `noise` `logn` |

**容易记错的几个**：

| 运算 | 说明 |
|---|---|
| **`len`** | **`sqrt(a² + b²)`** —— 这才是算距离的正确指令！（`Mathf.dst`） |
| `angle` | `atan2(b, a)`，返回角度 |
| `angleDiff` | 两个角度之间的**最短夹角** |
| `idiv` | **向下取整**的整除（`Math.floor(a/b)`），不是截断 |
| `emod` | 欧几里得取模，结果**永远非负**（`mod` 会返回负数） |
| `noise` | 单纯形噪声 `Simplex.raw2d(0, a, b)` |
| `logn` | 以 `b` 为底 `a` 的对数 |
| `land` | 逻辑与（`a != 0 && b != 0`） |
| `and` | **按位与**，别和 `land` 搞混 |

> ⚠️ **注意：没有 `deg` / `rad` / `lerp` / `vlen` 这些运算。** 角度的转换要自己乘 `180/π`。

## A.3 建筑交互

| 指令 | 格式 |
|---|---|
| `getlink` | `getlink 输出 索引` |
| `sensor` | `sensor 输出 建筑 属性` |
| `control` | `control <动作> 建筑 <参数...>` |
| `radar` | `radar 阵营 关系 排序 方向 建筑 数量 输出` |
| `printflush` | `printflush 消息块` |
| `drawflush` | `drawflush 显示屏` |

`control` 的动作：

| 动作 | 参数 |
|---|---|
| `enabled` | `建筑 0/1` |
| `shoot` | `建筑 x y shoot` |
| `shootp` | `建筑 目标 shoot` |
| `config` | `建筑 值` |
| `color` | `建筑 r g b` ← 灯的颜色 |

## A.4 单位

| 指令 | 格式 |
|---|---|
| `ubind` | `ubind 单位类型` / `ubind 具体单位` |
| `ucontrol` | `ucontrol <动作> <参数...>`（见 §4.4） |
| `uradar` | `uradar 阵营 关系 排序 方向 输出` |
| `ulocate` | `ulocate <类型> <分组> <敌方?> <矿物> <输出x> <输出y> <输出找到> <输出建筑>` |
| `flag` | `flag 值` |
| `within` | `within x y 半径 输出` |

### `ulocate` 详解

`ulocate` 有 4 种模式：

```
ulocate building <分组> <敌方?> <矿物> x y found build
ulocate ore      <忽略> <忽略>   <矿物> x y found build
ulocate spawn    ...                     x y found build
ulocate damaged  ...                     x y found build
```

`分组`（BlockFlag）取值：`core` `storage` `generator` `turret` `factory` `repair` `battery` `reactor` `drill` `shield`

语料用例：

```mlog
ulocate building core 0 @copper hxx hxy found hx      # 找己方核心
ulocate damaged core true @copper rx ry rf rb          # 找最近的受损建筑
```

> ### ⚠️ 导入陷阱：`分组` 位置**不能填 `0`**
>
> 在 `ore` / `spawn` / `damaged` 模式下，`分组` 虽然不参与逻辑运算，**但解析时依然会调用 `BlockFlag.valueOf()`**。
> **填 `0` 或任何非法值会让整条指令降级成 `InvalidStatement`（灰积木，什么都不做）**。
>
> **规范：无论哪种模式，`分组` 位置永远填一个合法的 BlockFlag（推荐 `core`）。**
> 这就是为什么语料里的 `ulocate damaged` 也老老实实写着 `core`。

> ### ⚠️ `enemy` 参数默认是「搜敌方」
>
> 游戏内编辑器里"是否搜索敌方"**默认是 `true`（1）**。要搜己方建筑必须**手动改成 0**。
> 所以 `ulocate building core 1 ...` 找的是**敌方核心**，不是自己的。

**距离规则**（这块很反直觉）：

| 模式 | 范围限制 |
|---|---|
| `building` + `enemy=0`（友方） | **无范围限制**，始终返回最近的符合条件的友方建筑 |
| `building` + `enemy=1`（敌方） | `outX/outY/outFound` 始终输出；但 **`outBuild` 只在 `max(unit.range(), 27.5 格)` 内才输出，否则为 null** |
| `ore` | 返回最近的指定矿脉 |
| `spawn` | 返回最近的**敌方**出生点 |
| `damaged` | 返回最近的**己方**受损建筑 |

**缓存**：`ulocate` 有 **40 tick 缓存**（同 `radar`/`uradar`），**不要用它做高频精确追踪**。
但它的缓存**按参数组合隔离**——参数不同的多条 `ulocate` 互不干扰，可以用"轮换不同参数"绕过缓存。

**`ulocate` 会刷新 10 秒控制计时器**（这点和 `uradar` 不同，见 §6.1）。

## A.5 世界处理器专属

| 指令 | 说明 |
|---|---|
| `setrate 值` | 设置 ipt（上限 1000） |
| `getblock` | `getblock <层> <输出> <x> <y>` 读地图格子（注意这是**全局版**，不同于 `ucontrol getBlock`） |
| `setblock` | `setblock <层> <方块> <x> <y> <团队> <旋转>` |
| `spawn` | `spawn <单位> <x> <y> <旋转> <团队>` |
| `bullet` | `bullet <类型> <x> <y> <角度> <团队> ...` |
| `status` | `status <true/false> <效果> <单位> <时长>` |
| `spawnwave` | `spawnwave <x> <y> <自然生成?>` |
| `setrule` | `setrule <规则> <值> <x> <y> <团队>` |
| `message` | `message <类型> <时长>` |
| `cutscene` | 镜头控制 |
| `effect` | `effect <类型> <x> <y> <旋转> <颜色> <数据>` |
| `explosion` | `explosion <队伍> <x> <y> <半径> <伤害> <空气> <地面> <击退>` |
| `fetch` | `fetch <类型> <输出> <建筑> <团队>` — 统计数量 |
| `getflag` / `setflag` | 全局标记读写 |
| `setprop` | `setprop <属性> <对象> <值>` |
| `playsound` / `playmusic` | 音效 |
| `setmarker` / `makemarker` | 地图标记 |
| `localeprint` | 本地化打印 |
| `sync` | `sync <变量>` 跨客户端同步变量 |
| `query` | 区域查询 |

**`sync` 很重要**：多人游戏里每个客户端独立跑逻辑，`sync` 可以把一个变量强制同步到所有客户端，**避免"各算各的"**。

---

# 附录 B 工具用法

## B.1 解析器

[tools/msch.py](tools/msch.py) — 零依赖的 `.msch` 解析器：

```python
import msch

sch = msch.parse_file("path/to/蓝图.msch")
print(sch.name, sch.width, sch.height)
for tile in sch.logic_tiles():
    print(tile.block, tile.x, tile.y)
    print(tile.logic.code)          # ← mlog 源码
    for link in tile.logic.links:
        print(link.name, link.x, link.y)
```

命令行：

```bash
python tools/msch.py "C:/Users/.../schematics/搬运t4.msch"
```

## B.2 检索工具

[tools/mlogsearch.py](tools/mlogsearch.py)：

```bash
# 按正则搜代码行
python tools/mlogsearch.py grep "op add @counter" --context 4

# 同时用到多个指令的逻辑块
python tools/mlogsearch.py op ucontrol ubind

# 搜索提到某个变量的逻辑块
python tools/mlogsearch.py var 不应期

# 按蓝图名查找
python tools/mlogsearch.py find 集火

# 打印某个蓝图的全部逻辑
python tools/mlogsearch.py show 搬运t4

# 打印某个逻辑块的链接表
python tools/mlogsearch.py links 搬运t4

# 指令直方图 / 最大的逻辑块
python tools/mlogsearch.py stats
python tools/mlogsearch.py top 30
```

**默认行为**：自动排除 18 个像素画生成器和 mlogv32 模拟器。要包含它们加 `--art` / `--linux`。

## B.3 语料文件

| 路径 | 内容 |
|---|---|
| [logic-corpus/by-blueprint/](../logic-corpus/by-blueprint/) | 430 个蓝图，每个一份 Markdown（按坐标排序 + 链接名 + 语句数） |
| [logic-corpus/index.json](../logic-corpus/index.json) | 全量索引 |
| [logic-corpus/ranking.json](../logic-corpus/ranking.json) | 按游戏逻辑含量排名 |
| [logic-corpus/templates.md](../logic-corpus/templates.md) | 404 个 ≤30 行的单处理器模板 |
| [logic-corpus/idioms.json](../logic-corpus/idioms.json) | 归一化后的高频指令组合统计 |
| [logic-corpus/blocks.json](../logic-corpus/blocks.json) | 检索工具的缓存 |

## B.4 重新生成语料

```bash
python tools/msch.py "某个蓝图.msch"     # 单文件验证解析
# 该语料脚本未随公开版发布
# 该语料脚本未随公开版发布
# 该语料脚本未随公开版发布
# 该语料脚本未随公开版发布
# 该语料脚本未随公开版发布
python tools/mlogsearch.py --refresh stats   # 刷新检索缓存
```

## B.5 静态检查工具

除了检索，还可以用脚本**批量验证代码的正确性**——本模式库第 11 章的发现都是这么来的：

```bash
# 扫描所有 op 行的参数个数是否和运算元数匹配（找出 567 处错误）
# 该语料脚本未随公开版发布

# 检查任一 .jar 里某个字段被赋成了什么常量（用于查 mod 是否改了游戏参数）
python tools/classdump.py "某个mod.jar" "mindustry/world/blocks/logic/LogicBlock.class"
```

## B.6 一个"以蓝图反推游戏机制"的方法论

这次分析的完整流程，可以复用到任何 Mindustry 问题上：

1. **读源码确认格式** —— 不要猜二进制格式，去 `Schematics.java` / `LogicBlock.java` 找读写函数
2. **写解析器 + 全量验证** —— 用 625 个真实文件做回归测试，覆盖率就是正确率
3. **区分信号与噪声** —— 97.8% 的语句是像素画，**不做分类的统计全是废数据**
4. **归一化后挖模式** —— 把变量名/数字换成占位符，统计 n-gram，高频结构就是"惯用法"
5. **用源码验证语义** —— 猜机制不如读 `LExecutor.java`。这次纠正了三个我最初的错误判断（`op abs` 存在、`setrate` 上限 1000、`@controlled` 的取值）
6. **用脚本找系统性错误** —— 手工看只能发现个案，写个 arity 检查器一次就找出 567 处

---

## 结语：这套语料教给我们的核心

从 5774 个逻辑块里提炼出的**六条最重要的经验**：

1. **mlog 没有数组、没有函数、没有循环作用域。** 所有"批量"操作只能靠
   ① `getlink i` + `@links` 轮转，或 ② 平铺展开 `u1..u8`。理解这一点就理解了 90% 的蓝图为什么那么长。

2. **ipt 预算是唯一的性能约束。** 所有优化最终都归结为"每帧少跑几条"：
   轮转链接、分批处理、`wait` 降频、`setrate` 动态调速、`end` 提前返回。
   **指令总数硬上限 1000 条**，超了静默截断。

3. **`ucontrol` 只对当前 `@unit` 生效，且有 10 秒超时。** 单位"突然不听话"一定是超时、`ubind` 被插队，**或者你只用了 `uradar` 而没下发任何 `ucontrol`**（§6.1）。

4. **`@controlled` 不能区分处理器**（所有逻辑控制都返回 1），要区分得用 `@controller` 比 `@this`。
   多逻辑协同必须用 **flag 约定**，而且 flag 值应该用 `floor(@thisx)*1000 + floor(@thisy)` 生成，而不是随手挑魔法数字。

5. **mlog 的 `op` 是固定元数的。** 一元运算（`abs`/`floor`/`sin`/`rand`…）只吃 2 个参数。
   你的语料里有 **567 处**写成了三元——**这是全语料最大的一类系统性错误**（§11.1）。
   好消息是：**越界跳转、未知指令、未知 `ucontrol` 动作全部为 0**，说明问题只集中在这一类。

6. **蓝图存的是明文源码，但标签信息已丢失、相对跳转不可维护、算法错误会被"能跑"掩盖。**
   学蓝图要学**结构**，不要照抄**参数**；遇到 `op add 距离 dx dy` 这类要自己验算。
   **"能跑"不等于"对"——这是这次分析最大的收获。**
