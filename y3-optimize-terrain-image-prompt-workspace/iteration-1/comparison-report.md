# Skill 测试对比报告：y3-optimize-terrain-image-prompt

**测试时间：** 2026-06-02  
**技能路径：** `E:\pycode\y3-maker-config\skills\y3-optimize-terrain-image-prompt\SKILL.md`  
**对比逻辑：** 相同用户输入，有技能版 vs 无技能基准版（Claude 自由发挥）

---

## 总体结论

| 维度 | 有技能版 | 无技能基准版 |
|------|----------|------------|
| 输出结构 | ✅ 六节完整（正向/负向/保真说明/为何适合/参数/风险） | ❌ 仅输出提示词本体，缺少说明类内容 |
| 俯视正交约束 | ✅ 明确要求 top-down orthographic，无透视无阴影 | ⚠️ eval-0/1 有提及，eval-2 完全缺失 |
| 颜色语义 | ✅ 每种地貌指定固定颜色，服务于 CV 聚类 | ⚠️ 有颜色描述但不系统，部分会干扰识别 |
| 高度表达 | ✅ 离散色带，禁止强阴影 | ❌ eval-2 用"戏剧性阴影"表达高度，干扰 CV |
| 干扰项控制 | ✅ 负向提示词完整禁止文字/图例/罗盘/阴影等 | ❌ eval-2 反而鼓励罗盘、羊皮纸纹理、电影光影 |
| 设计保真 | ✅ 明确列出保留/未改/增强的内容 | ⚠️ 保留了大部分设计，但无显式保真说明 |
| 模型适配 | ✅ 针对 Midjourney/SD 给出专项参数 | ⚠️ eval-1 给了 MJ 参数，但无通用建议 |
| 风险提醒 | ✅ 每个 eval 均有针对性风险提醒 | ❌ 无风险提醒 |
| 与 y3-gen-terrain-from-image 衔接 | ✅ 明确提示验收标准再交给下游技能 | ❌ 无衔接提示 |

---

## Eval 0：四人对战雪山地图

**用户输入：**
> 帮我优化一段地图生成提示词，用于图片转地形。我想要一张四人对战地图，中间有一座雪山，四角是玩家出生点，雪山周围有森林和两条河流，河上有桥。

### 有技能版（摘录核心正向提示词）

> 一张用于游戏编辑器图片转地形的俯视正交地形规划图，主题为：四人对战雪山地图。地图内容必须填满整个画布，地图边界与图片边界严格对齐，无倾斜、无透视、无留白、无装饰边框。
>
> 使用清晰、低噪声、机器可读的色块表达地形：深蓝色或青蓝色表示河流水域，浅绿色表示平原和出生点区域，深绿色表示森林，棕色和灰棕色表示中段山地，灰白色或白色表示雪山顶部。
>
> 高度通过明确的离散高度色带表达：河流水域最低，岸边和平原较低，森林略高于平原，丘陵和低山逐渐升高，中央山地更高，雪山顶部最高。

**负向提示词（有技能）：**
> 不要透视视角，不要斜视角，不要3D场景，不要电影感光照，不要强烈阴影，...不要让雪山呈现为照片级真实雪山，不要让河流变成细密流水纹理，不要让桥梁变成精细建筑结构图。

### 无技能基准版（摘录）

> Top-down 2D strategy game map, four-player battleground, symmetric layout, center features a tall snow-capped mountain peak with **glacial white terrain and rocky cliffs**, surrounded by **dense pine forests**, two winding rivers... **hand-painted fantasy style**, **bird's eye view, isometric-inspired 2D art, high detail, game-ready asset**

**负向提示词（无技能）：**
> asymmetric layout, random terrain, missing bridges, no spawn points, urban environment, desert biome...（只排除主题偏差，未禁止阴影/纹理/图例等 CV 干扰项）

### 对比小结

| 检查点 | 有技能 | 无技能 |
|--------|--------|--------|
| 俯视正交 | ✅ 明确禁止透视/阴影 | ⚠️ 提到 top-down，但同时用了 isometric-inspired（等距视角，有透视成分） |
| 颜色语义 | ✅ 每种地貌固定颜色 | ❌ 无系统颜色规范 |
| 高度离散色带 | ✅ | ❌ 无 |
| 禁文字/图例/罗盘 | ✅ | ❌ 无 |
| 输出结构完整 | ✅ 六节 | ❌ 仅提示词+表格 |
| 风险提醒 | ✅ 5 条 | ❌ 无 |

---

## Eval 1：热带岛屿火山地图（Midjourney）

**用户输入：**
> 生成一个热带岛屿，有环形沙滩，岛中心是火山，东边有小村庄，西边有沼泽。帮我优化成适合图片转地形的文生图提示词，我用的是 Midjourney。

### 有技能版（摘录核心）

- 中文六节完整输出 + 英文版（因用户指定 Midjourney）
- 每种地貌颜色固定：深蓝深海 / 浅黄环形沙滩 / 深绿丛林 / 黑灰+红橙火山口 / 暗绿偏蓝沼泽 / 浅棕村庄
- Midjourney 专项参数：`--style raw --ar 1:1 --stylize 30 --chaos 0`
- 风险提醒：火山口岩浆渲染过强会引入噪点、沙滩与平原色相近需强调差异

### 无技能基准版（摘录）

> aerial top-down satellite view of a tropical island terrain map, massive active volcano at the center with **dark rocky crater and lava flows**... **highly detailed topographic texture**... `--ar 1:1 --style raw --v 6`

### 对比小结

| 检查点 | 有技能 | 无技能 |
|--------|--------|--------|
| 输出语言 | ✅ 中文+英文双版本 | ❌ 仅英文 |
| 岩浆流控制 | ✅ 负向提示词明确禁止"岩浆喷发特效" | ❌ 正向提示词主动要求 `lava flows`（会污染 CV 颜色聚类） |
| 高度色带 | ✅ 从深海到火山顶六级离散 | ❌ 使用 `highly detailed topographic texture`（纹理复杂，干扰聚类） |
| 村庄简化 | ✅ 简洁浅棕色块，禁止建筑图标 | ❌ `small fishing village with wooden huts and docks`（复杂建筑细节） |
| Midjourney 参数 | ✅ stylize 30, chaos 0 | ⚠️ 有 `--style raw` 但无 stylize/chaos 控制 |

---

## Eval 2：奇幻沙漠迷宫地图

**用户输入：**
> 奇幻风格沙漠迷宫地图，中间有个绿洲，四周是沙丘，有隐藏的地下通道入口。

### 有技能版（摘录核心）

- 奇幻主题保留，但视觉约束保持机器可读
- 沙丘 / 通道 / 绿洲 / 入口各有专属颜色（通道比沙丘更浅，入口为深灰色块）
- 负向提示词额外加入：日落光效、氛围光、写实沙漠风景插画、骆驼、沙粒纹理
- 风险提醒：沙漠同色系统一风险（通道/沙丘色差不足）、迷宫通道过细、高度层级偏平

### 无技能基准版（摘录）

> ...sand dunes forming winding corridor walls, their ridges casting **dramatic shadows** under a warm amber sky...the map includes a **compass rose** in one corner...illustrated in an **antique parchment style**...**cinematic lighting**...aged parchment texture overlay

### 对比小结

| 检查点 | 有技能 | 无技能 |
|--------|--------|--------|
| 奇幻风格处理 | ✅ 保留主题，弱化视觉装饰 | ❌ 完全拥抱艺术化（羊皮纸、电影光影、荧光效果） |
| 罗盘/图例 | ✅ 负向明确禁止 | ❌ 正向主动加入罗盘（compass rose） |
| 阴影表达高度 | ✅ 使用离散色带，禁止强阴影 | ❌ 用"dramatic shadows"表达沙丘高度 |
| 地下入口处理 | ✅ 深灰/暗褐色块标记，与沙地形成色差 | ❌ 渲染为"石拱门+发光符文+活板门"，装饰复杂 |
| CV 可识别性 | ✅ 高 | ❌ 极低 |

---

## 各 Eval 文件路径

```
E:\pycode\y3-optimize-terrain-image-prompt-workspace\iteration-1\
├── eval-0-snow-mountain\
│   ├── with_skill\output.md
│   └── without_skill\output.md
├── eval-1-tropical-island\
│   ├── with_skill\output.md
│   └── without_skill\output.md
└── eval-2-fantasy-desert\
    ├── with_skill\output.md
    └── without_skill\output.md
```

---

## 结论与建议

**技能整体表现良好**，三个 eval 均正确输出了六节结构，颜色语义和高度表达均符合机器可读要求。与无技能基准版对比差异最显著的是 **Eval 2（奇幻沙漠）**——无技能版完全走向了"精美地图插画"方向，引入了罗盘、羊皮纸纹理、电影光影，对 CV 识别几乎没有价值；有技能版则在保留奇幻主题的同时，控制住了所有视觉干扰。

**潜在改进方向（可选）：**
1. 可在 SKILL.md 中补充对"地下通道/隐藏元素"的专项处理建议（当前模板无此类元素的默认颜色）
2. 可为常见中国文生图平台（通义万相、即梦）增加更多专项参数示例
