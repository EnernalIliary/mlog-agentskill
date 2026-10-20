# 版本表（build 147 → 160）

只收**与 mlog 语法/语义有关**的条目。来源：Anuken/Mindustry 的 GitHub Release 说明
（v146/v147/v150 直接取自 release API，v152–v160 取自 Steam 公告镜像
<https://store.steampowered.com/news/app/1127400>），发布日期取自
<https://mdtwiki.top/index.php?title=版本记录>。

| build | 日期 | 逻辑相关变更 |
|---|---|---|
| 146 | 2023-09-04 | **v7 起点 = 报告基线**。原文五条逻辑条目：「Added logic unit autoPathfind command (default wave pathfinding)」、「Made logic unbind command set `@unit` to null」、「Added logic sensors for shields, content ID (inverse of lookup command)」、「Added logic particle effect instruction」、「Added logic sync instruction」；另修「internal legacy blocks being logic constants」。<br>**`read`/`write` 按名字读写另一个处理器 / message 方块属于 v7 基线**（v146 说明里未单列，但 v7 起才有；v6 的 `read` 只能拿数字下标访问记忆格） |
| 147 | 2025-04-11 | **`format`（文本显示）+ draw 变换指令**；世界处理器可显示任意贴图/形状；地图内世界处理器脚本管理 UI；另有概括句「logic blocks，尤其 world processors 的许多新功能」——**未逐条列出** |
| 148 | 2025-04-21 | 未见逻辑条目 |
| 149 | 2025-04-30 | 未见逻辑条目 |
| 150 | 2025-07-23 | **`select`（三元运算）**；可从字符串 / message 方块里读字符；可读写 canvas 方块；`text align` 由「指令静态字段」改成**常量变量** |
| 151 | 2025-08-25 | 未见逻辑条目 |
| 152 | 2025-09-27 | 修：绑定的单位在逻辑块里不会被保存 |
| 153 | 2025-10-30 | 逻辑编辑器支持「在两行之间插入指令」 |
| 154 | 2025-12-16 | **音效大规模重命名**，原文写明「will break mods and logic」⇒ 旧 `playsound` 名字静默失效 |
| 155 | 2026-02-09 | `draw image` 允许把别的 display 当图源 |
| 156 | 2026-03-24 | 修：`wait` 的时间不保存；boost 由「命令」改成「姿态」；新增 3×3 canvas 方块 |
| 157 | 2026-04-09 | 无逻辑条目 |
| 157.3 | — | **新增 `bullet`（生成弹丸）指令**；新增 ping 文本 / 位置传感器 |
| 157.4 | — | **新增世界逻辑空间查询指令（`getblock`）**；修 `bullet` 引起的存档问题 |
| 158 | 2026-05-24 | message 方块文本上限固定为 400；处理器压缩代码上限 16 KB；`@queries` 世界变量曾致存档损坏 |
| 159 | 2026-07-06 | 新增「单位是否在飞 / 埃里克尔方块热量」传感器；新增播放音乐指令；**`read` 可读处理器链接**；hotfix 修 logic read 崩溃 |
| 159.5 | — | 新增「当前播放音乐」逻辑变量、音乐音量规则 |
| 160 | 2026-09-11 | `within` 不再施加逻辑控制；逻辑标记可当光源；**camera 传感器转为特权专用**；**`setrate` 对非特权处理器开放**；逻辑字符串支持 `\uXXXX` / `\n` / `\"` / `\\` 转义；**内存格可存任意对象**；cutscene 控制增强；`status` 接受状态效果变量、时长可被 sensor 读；编辑器本地化 |
| 160.2 | — | 撤销 `setblock` 坐标取整（坐标**不再**取整） |
| 160.5 | — | 修 `0x` / `0b` 数值超过 `Long.MAX_VALUE` 时解析失败 |
| 160.6 | — | 修「逻辑里的空字段导致参数错位」 |

**146 是报告基线，不是"第一条要报的版本"**。v7 之前的写法（数字下标的 `read`/`write`、
`draw`、`control` …）全部视为「一直存在」，不报；只有**基线之后新增**的语句才会让一份
蓝图在别人机器上跑不了、或者变成 `noop`。判断写成 `floor > BASELINE_BUILD`
（`mlogcheck.py` 里的常量 `BASELINE_BUILD = 146`），不是硬编码 147。

`effect` / `sync` / `autoPathfind` / 内容 ID 传感器都在基线里，所以**永不报告** ——
它们是 v7 的标志，不是风险。

## 已经写进 `tools/instr_semantics.json` 的 `min_build`
| 语句 | min_build | 依据 |
|---|---|---|
| `effect` | 146 | v146「Added logic particle effect instruction」 |
| `sync` | 146 | v146「Added logic sync instruction」 |
| `format` | 147 | v147「Instructions for displaying text and applying drawing transformations for logic processors」 |
| `select` | 150 | v150「Added 'select' (ternary) logic operation」 |
| `bullet` | 157 | v157.3「Added a processor instruction for spawning bullets」 |
| `getblock` | 157 | v157.4「Added a world logic spatial query instruction」 |

`ucontrol autoPathfind` 也是 146（v146「Added logic unit autoPathfind command」），
但 `min_build` 挂在**语句**上，子命令级别暂未建模。

## 两条「存在但不是原来的意思」

- `setrate`：早就有，但**只有世界处理器能用**；v160 起才对非特权处理器开放。
- `playsound`：语句一直在，但 v154 重命名了绝大多数音效 ⇒ 老名字不会报错，只是**不响**。

## 还没确定的部分

- 147 那句概括（「许多新功能，尤其 world processors」）没有逐条列出，其中可能还有
  别的语句是 147 才有的。
- 148 / 149 / 151 只是公告里**没提到**逻辑，不等于没有改动。
- `format` 在 147 首版里的占位符语法（`{}` 与 `{n}`）是否与 159 完全一致，未核。
- `noop` 不是版本特性：它是 `InvalidStatement` 的注册名（`LStatements.java:48-49`），
  `LParser.java` 有四处会产生它——解析异常（`:143-147`）、特权语句出现在非特权处理器
  （`:150-152`）、mod 自定义语句需要特权（`:166-168`）、助记符不认识（`:171-173`）。
  所以看到 `noop` 时，「版本不一致」只是**两种**可能之一。
