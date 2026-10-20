# mindustry-blueprint

**Mindustry 蓝图与 mlog 逻辑工具链** —— 一个 DSH skill。

解析 `.msch` 蓝图(提取逻辑明文源码)、按逻辑生成可粘贴的蓝图码、静态检查 mlog、
查方块 content ID 与 mlog 指令格式。**纯标准库,零第三方依赖。**

## 装到 DSH

```bash
# 整个目录丢进 skills 目录
cp -r mindustry-blueprint "$DSH_HOME/skills/"
```

或者打包成 `.dspack` 分发(见下)。

## 用法

```bash
cd mindustry-blueprint/tools

# 解析:看蓝图里的方块、链接和逻辑源码
python mlog.py parse "schematics/无线超.msch"

# 检查:生成前必做,能抓出 @dead 反用等真实 bug
python mlog.py check logic.mlog

# 生成:产出可粘贴的蓝图码(默认打印到 stdout)
python mlog.py gen logic.mlog --name "我的逻辑" --link dome1@3,1

# 生成:连目标方块一起放(--with-block 坐标是【中心格】)
python mlog.py gen logic.mlog --name "无线超" \
    --link dome1@3,1 --with-block overdrive-dome@4,2=248 \
    --out paste.txt --binary out.msch

# 查参考数据
python mlog.py id overdrive      # 方块 content ID + 尺寸
python mlog.py cmd ulocate       # 指令格式
python mlog.py selftest          # 429 个真实蓝图往返校验
```

`selftest` 会自动找 Mindustry 的 schematics 目录;找不到时设 `MINDUSTRY_SCHEMATICS`。

## 文档

| 文件 | 内容 |
|---|---|
| [SKILL.md](SKILL.md) | 规范:铁律、标准流程、最容易搞错的坐标约定 |
| [REFERENCE.md](REFERENCE.md) | 完整知识库:编号体系、机制、坑、被推翻的旧结论 |
| [PATTERNS.md](PATTERNS.md) | 逻辑模式库(按兵控/物流/火控/建造/显示分类,附源码依据) |
| [BLUEPRINT-ANALYSIS.md](BLUEPRINT-ANALYSIS.md) | 蓝图层逐类精讲与工程分析 |

## 参考数据

| 文件 | 内容 |
|---|---|
| `tools/wiki_block_ids.json` | 422 个原版方块 → content ID |
| `tools/block_sizes.json` | 446 个方块尺寸(从源码推导) |
| `tools/cmd_index.json` | 86 条 mlog 指令的格式/参数/注意事项 |

## 三个必须知道的坑

1. **方块坐标存的是「中心格」,不是左上角。**
   一个 3×3 方块要占据 `(3,1)–(5,3)`,中心得写 `(4,2)`。
   (源码 `Tile.setBlock()` 的 `offset = -(size-1)/2`;624 个真实蓝图实证:按"角"解释会产生 11 处重叠,按"中心"0 处。)

2. **蓝图里存的是 mlog 明文源码**,不需要反编译。但**跳转目标已从标签编译成行号**,
   标签信息丢失 —— 增删一行会让所有 `jump` 偏移。

3. **content ID 是"构造顺序号"。** 原版方块先构造、mod 后追加,
   所以 **mod 不会让原版方块的 ID 偏移**;但要小心**游戏版本差异**。
   蓝图本身**不存 content ID**,游戏按方块名解析。

## 验证状态

- **429/429** 含逻辑的真实蓝图,逻辑代码 + 链接 **逐字节往返一致**
- 静态检查器在你成熟的蓝图上约 2 个误报/块 —— **当提示器用,不要为它改正确的代码**

## 打包成 .dspack

```bash
# 目录内
git init -b main && git add . && git commit -m "feat: mindustry-blueprint skill"
```

发布到 GitHub 时:仓库打 **`dsh-pack`** 话题、根目录有 manifest、发**正式** Release
(资产 = `.dspack` + 同名 `.sha256` 侧车,64 位小写 hex)。详见 DSH 的 `publish-to-github` 技能。

## 许可

MIT
