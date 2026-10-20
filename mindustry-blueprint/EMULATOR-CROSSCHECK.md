# 第二实现交叉验证：mindcode 的处理器模拟器

> 我的静态分析（`mlogcheck` / `mlogval` / `mlogcross`）全部建立在读
> `Mindustry-Source/core/src/mindustry/logic/*.java` 之上。读源码会读错，
> 所以每一条"语言事实"都需要一个独立实现来复核。
>
> 这里用的是 [`cardillan/mindcode`](https://github.com/cardillan/mindcode) 自带的
> 处理器模拟器 —— 一个**不读我这份源码**、由别人独立写的 mlog 执行器。

> **2026-10 后记**：日常已经改用仓库根的 `tools/mlogsim.py` —— 它驱动游戏真正的
> `LExecutor`（默认 v160.7 + JRE21），不需要 JDK 22 和 `mindcode.jar`；
> `out/probes/p1..p8` 已在 v159.3 与 v160.7 上复跑通过。mindcode 这条独立实现仍然有效
> （它的价值是"不读我的源码"），但不再是必跑项。下文保留当时的原始记录。

## 用的是哪一版

| 项 | 值 |
|---|---|
| 版本 | `v3.19.3`（2026-09-19），GitHub Releases 里的预编译 `mindcode.jar`，31.6 MB |
| 运行环境 | 需要 **JDK 22**（class file 66.0）；JDK 17 会报 `UnsupportedClassVersionError` |
| 默认 target | `8.2` = Mindustry v8 Build 160.1 |
| 跑代码 | `java -jar mindcode.jar pm <file>.mlog --run true` |
| 跑整张蓝图 | `java -jar mindcode.jar ps <file>.msch --run true --run-steps 2000` |

探针文件在 `out/probes/`（`p1`–`p7` 是 `.mlog`，`p8` 是 `.msch`）。

## 八条断言，逐条对账

| # | 断言（我写进代码的规则） | 模拟器结果 | 结论 |
|---|---|---|---|
| P1 | `equal <未赋值变量> null` 恒真（未赋值读作 0，`null` 也读作 0） | `jump ok equal neverassigned null` **跳了** → `P1-OK` | ✅ 一致 |
| P2 | `op logn r 0 2` 得 `null`（`-Infinity` → `setnum` 归一化成 null） | `strictEqual r null` 成立 → `P2-OK` | ✅ 一致 |
| P3 | `op div q 1 0` 得 `null` | `strictEqual q null` 成立 → `P3-OK` | ✅ 一致 |
| P4 | `sensor d @unit @dead`（`@unit` 为 null）返回数字 **1** | 打印 `P4 dead-of-null = 1` | ✅ 一致 |
| P5 | `print <未声明的名字>` 输出字符串 `null` | 打印 `P5:[null]` | ✅ 一致 |
| P6 | 记忆格读未写过的位置得数字 **0**（不是 null） | 打印 `P6-OK read-unset-mem = 0` | ✅ 一致 |
| P7 | `ubind` 认领后 `@controller == @this` | **模拟器不支持 `ubind`**：`Instruction 'ubind' not supported by Mindcode emulator.` | ⏸ 未验证 |
| P8 | `read x <别的处理器> "<名字>"` 只读得到对方**已声明**的变量；`write` 到未声明的名字不建槽 | `A=7`（已声明）/ `B=null`（未声明）/ `C=null`（先 `write 99` 再读，仍是 null） | ✅ 一致 |

P8 的蓝图：`processor1` @(0,0) 里 `set declared 7`，另一个处理器 @(3,0) 依次
`read a processor1 "declared"` / `read b processor1 "nope"` /
`write 99 processor1 "fresh"` / `read c processor1 "fresh"`。
输出 `A=7|B=null|C=null|` —— **`write` 到未声明的槽确实什么也不做**，槽不会按需创建。
这条正是 `mlogcross` 的 `cross reads … (never assigned)` 与 `mlogcheck` 的
`the slot must be declared there first` 的依据。

## 一致意味着什么、不一致意味着什么

- 一致的六条，从"我读源码得出的结论"升级为"两个独立实现都这么算"。
  文档里改写时可以直接标 **双实现确认**。
- 不一致时以 `LExecutor.java` 为准，然后查是我读错还是它没跟上版本
  （它自己的 release note 就写着"文档还没跟上 Build 160"）。
- 模拟器**不能**验证的东西，别指望它：没有世界、没有单位、`sensor` 只支持少数属性、
  `ubind`/`ucontrol` 全不支持。凡是"要有一个真实战场才会发生"的行为
  （比如 `@this` 那条死循环），模拟器和我一样看不见。

## 记录

首次跑通：2026-10-18。八条里六条一致、一条不支持、一条（P8）是新加的蓝图级探针。
