---
name: y3-optimize-terrain-image-prompt
description: 将用户的原始地图/地形描述优化为适合文生图模型生成"机器可识别地形规划图"的提示词。该提示词服务于 y3-gen-terrain-from-image，而不是服务于人类审美。适用于用户希望先通过 AI 文生图生成一张地图图片，再用图片转地形流程在 Y3 编辑器中还原地形的场景。触发词：优化地图生成提示词、生成适合图片转地形的提示词、文生图转地形提示词、图片转地形前置提示词、让AI生成适合识别的地图图。
---

# Y3 图片转地形专用提示词优化器

## 目标

在不改变用户原始地图设计意图的前提下，将用户的自然语言描述改写成一组适合文生图模型使用的提示词，使生成的图片更适合后续 `y3-gen-terrain-from-image` 进行 CV + AI 识别。

## 流水线说明

本 Skill 生成的地形图将经过以下处理流水线：

```
地形图（本 Skill 生成的提示词）
    + 高度图（DA3MONO-LARGE 自动从地形图推算）
         ↓
y3-gen-terrain-from-image
    ├── CV + AI：水域识别、大陆分割、纹理分配
    ├── 高度图：高度层级直接读取
    └── 后处理：装饰物、植被根据地形数据 + 用户描述自动放置
```

**因此，地形图只需要表达：水体、地面纹理、高度起伏。装饰物（树木、山石、建筑、出生点）和植被（草、花）由后处理阶段根据地形数据自动生成，不需要在地形图中画出来。**

## 优先服务目标

1. 水域边界清晰，水体类型（深水/浅水/平面水）颜色可区分
2. 地面纹理区域（草地/沙地/岩石/雪地）颜色语义明确
3. 高度起伏有自然明暗，便于 DA3MONO-LARGE 推算深度
4. 零装饰物图标、零植被图案（这些由后处理补充）
5. 低噪声、低艺术化干扰，适合 CV 色彩聚类
6. 图片边界与地图边界 1:1 对应

**本 Skill 只负责将用户原始地图描述优化为适合"图片转地形"的文生图提示词。不负责生成图片，不负责调用 Y3 MCP，不负责写入地形，不负责放置装饰物。**

---

## 输入

用户可以提供以下任意信息（如果只提供原始描述，直接优化，不必强制追问）：

**地形图相关（直接影响图片生成）：**
1. 原始地图描述
2. 游戏类型
3. 地图尺寸或比例
4. 水域分布（深水湖泊/河流、浅水河道、沼泽积水）
5. 高度地貌（山脉、丘陵、高地、峡谷、盆地等）
6. 地面纹理区域（草地、沙漠、雪地、沼泽、岩石等）
7. 使用的文生图模型类型（Midjourney、Stable Diffusion、DALL·E、通义万相、即梦等）
8. 风格要求（奇幻、写实、卡通、科幻——仅影响色调，不影响结构）

**后处理相关（转为参数格式，不写入提示词）：**
- 首都/出生区位置 → `--capital "center"` 或 `--capital "x,z"`
- 资源点/怪物巢穴/地牢数量偏好 → `--node-counts "resource=5,lair=8"`
- 树木、植被、桥梁：全部自动生成，无需记录

> 当用户提及出生点位置或节点数量时，直接提取为参数格式写入"后处理参数"节即可。其他装饰物意图不需要记录。

---

## 输出格式

必须输出以下六节内容：

```
## 优化后的正向提示词
...

## 负向提示词
...

## 设计保真说明
- 地形图中保留了：...（水域/高度/纹理相关）
- 后处理阶段实现：...（出生点/建筑/树木密度等，不在地形图中）

## 后处理参数
--capital "..."        # 首都/出生区位置，如 "center" 或 "32,48"（仅当用户指定时填写）
--node-counts "..."    # 节点数量覆盖，如 "resource=5,lair=8,dungeon=2,ruin=6"（仅当用户有明确偏好时填写）

## 可选参数建议
- 画幅：
- 风格：
- 细节：
- 随机性：

## 风险提醒
- ...
```

> **后处理参数说明**：这两行参数在用户启动 `y3-gen-terrain-from-image` 时传给 `cv_postprocess_plan.py`。
> 树木、植被、桥梁由后处理自动生成，无需记录。如果用户没有特别说明首都位置或节点数量，两行都可省略（脚本有合理默认值）。

除非用户明确要求英文，否则默认输出中文提示词。

如果用户指定使用英文效果更好的文生图模型（如 Midjourney、Stable Diffusion、DALL·E），或者明确要求英文版，则额外输出：

```
## English Positive Prompt
...

## English Negative Prompt
...
```

如果用户明确要求"只输出提示词"，则只输出正向提示词和负向提示词两节。

---

## 核心原则

### 1. 不改变用户原意

必须保留用户原始描述中的核心设计意图：地图主题、地貌类型、主要区域关系、阵营或出生点布局、道路河流桥梁山脉的位置关系、特殊玩法需求、用户明确要求保留的风格。

可以增加"机器可读性约束"，但不能擅自新增会改变地图结构的元素。

**错误示例：**
- 用户原意：一个中央湖泊，四周是森林和丘陵
- 错误优化：一个中央火山，四周是岩浆，森林被烧毁（改变了核心地貌）
- 正确优化：一张俯视正交地形规划图，中央是边界清晰的蓝色湖泊，湖泊四周分布深绿色森林和浅棕色丘陵，区域边界清楚，色块简洁，适合后续图片转地形识别

### 2. 生成"地形规划图"，不是"风景插画"

必须引导文生图模型生成 top-down / orthographic / flat terrain planning map 风格：

- 优先使用：俯视图、正交视角、地形规划图、游戏地图草图、机器可读、清晰色块、低纹理噪声、边界清晰、无透视、无阴影
- 避免使用：电影感、超真实、氛围光、景深、日落、云雾、写实摄影、复杂纹理、精美插画

如果用户要求奇幻、科幻、写实、卡通等风格，可以保留主题，但必须弱化视觉装饰。例如"奇幻风格岛屿地图"应优化为"奇幻主题的俯视正交地形规划图，保持区域色块清晰、无复杂插画、无文字、无装饰边框"。

### 3. 地貌颜色使用固定 RGB 协议

下游 CV 识别按固定颜色映射，必须在提示词中明确指定这些颜色。不得用渐变、纹理或光影替代颜色区分。

**水体（高优先级，颜色必须稳定）：**

| 水体类型 | 颜色名 | 目标 RGB | Y3 对应 |
|---------|--------|---------|---------|
| 深水（不可通行） | 深海蓝 | `RGB(25, 55, 135)` | deep_water |
| 浅水（可通行河道） | 青蓝 | `RGB(70, 165, 205)` | shallow_water |
| 平面水/沼泽水 | 暗蓝绿 | `RGB(45, 100, 90)` | plain_water |
| 沙滩/岸边 | 浅米黄 | `RGB(220, 200, 150)` | 低地地面纹理 |

**地面纹理（按高度层分组）：**

| 地貌 | 颜色名 | 目标 RGB | Y3 高度层 |
|------|--------|---------|---------|
| 草地平原 | 浅草绿 | `RGB(130, 185, 95)` | h=0 |
| 沙漠/荒地 | 沙黄 | `RGB(215, 185, 110)` | h=0 |
| 沼泽地面 | 暗黄绿 | `RGB(90, 120, 70)` | h=0 |
| 雪地（平坦） | 蓝白 | `RGB(225, 230, 240)` | h=0 |
| 丘陵草坡 | 橄榄绿 | `RGB(100, 130, 60)` | h=2 |
| 山地岩石 | 棕褐 | `RGB(130, 90, 55)` | h=4 |
| 高山雪峰 | 灰白 | `RGB(210, 212, 218)` | h=6 |
| 火山（仅用户要求） | 深灰+红橙 | `RGB(60,60,60)` + `RGB(200,80,30)` | h=4~6 |

> 颜色作为提示词目标值，文生图模型不会精确还原，但大方向一致即可让 CV 正确分类。

**颜色分离关键约束（防止高度区域碎片化）：**
- 不同高度层的颜色**色相差距必须明显**：草地平原（浅草绿）、丘陵（橄榄绿）、山地（棕褐）三者色相差距足够大，CV 聚类才能清晰分开
- 同一高度层的颜色**不能混入其他高度层的色调**：平原区域内不能出现橄榄绿或棕褐色的碎斑
- 高度过渡（平原→丘陵→山地）应该是**大块连续色区**，不是像素级混合散布
- 图片中若平原/丘陵/山地颜色过于接近或随机混杂，会导致地形碎片化，斜坡无法正常连通

### 4. 高度起伏用自然明暗表达（适配 DA3 深度估算）

高度图由 DA3MONO-LARGE 从地形图自动推算，因此地形图需要保留**自然的、由高度引起的明暗差异**：

- 高处（山顶）颜色稍亮，低处（谷地/水边）颜色稍暗——这是 DA3 判断深度的依据
- 使用**一致方向的柔和平行光**，避免多光源、强点光源、阴影过黑
- 山脉从山脚到峰顶颜色自然过渡（不需要完全离散色带，DA3 可以读连续变化）
- 禁止电影感打光、戏剧性阴影、氛围光——这些会让 DA3 误判深度

> 与旧协议的区别：旧协议要求"离散高度色带"让 AI 直接读高度；新协议改为"自然明暗"让 DA3 自动推算，两者对图片生成的要求不同。

### 5. 禁止文字、图例、罗盘和 UI 元素

除非用户明确要求，必须在负向提示词中禁止：文字、数字、图例、罗盘、UI 面板、网格线、坐标轴、水印、地名标签、路标文字、装饰边框。这些元素会干扰 CV 聚类、水陆分割、纹理识别、高度推断和装饰物识别。

### 6. 严禁一切装饰物和植被图案

**装饰物（树木、山石摆件、建筑、出生点、道路摆件）和植被（草、花、芦苇）由 y3-gen-terrain-from-image 后处理根据地形数据自动放置，地形图中绝对不能出现这些元素的视觉表现。**

必须在负向提示词中禁止：

- **树木相关**：树冠图案、树木图标、独立树木、丛林插画、森林写实场景
  - 森林区域只用深绿色色块表示纹理，不画任何树形
- **山石相关**：山峰插画、写实岩石、山石摆件、三角山形图标
  - 山地只用棕色/灰棕色色块表示，高度由 DA3 读取，不需要画山峰形状
- **建筑相关**：房屋、基地、塔楼、城墙、出生点标记、资源点图标、路标
- **其他**：植被贴图、草地写实效果、花朵、芦苇、船只、人物、怪物、车辆
- **道路**：道路只允许作为纯色细线区域（与周围地面颜色有轻微区分），不允许写实道路纹理

用户描述中的"森林""出生点""村庄"等意图：**记录到"设计保真说明"和"后处理备注"，提醒用户这些将在后处理阶段自动生成，不要在地形图提示词中表现**。

### 7. 保持地图边界与画面边界一致

必须加入以下约束：地图内容填满整个画布，地图边界与图片边界严格对齐，不要倾斜，不要留白边，不要装饰相框。后续图片转地形会将图片坐标映射到编辑器地图网格，因此图片边界应与地图边界 1:1 对应。

---

## 工作流程

### Step 1：提取用户原始意图并分类

从用户输入中提取，并分为两类：

**地形图元素（写入提示词）：**
- 地图主题、风格
- 水域分布（湖泊/河流/沼泽类型和位置）
- 高度地貌（山脉/丘陵/峡谷的位置和相对关系）
- 地面纹理区域（草地/沙漠/雪地/岩石的分布）
- 道路（仅表现为细线色块，不画写实道路）

**后处理元素（记录到"后处理备注"，不写入提示词）：**
- 森林/树木（后处理按纹理自动放置）
- 建筑/基地/出生点（后处理按用户描述放置）
- 资源点/特殊游戏区域（后处理放置）
- 植被密度偏好（后处理参数）
- 桥梁（后处理按水域自动识别）

### Step 2：判断水体类型

根据用户描述判断水体类型：
- 湖泊、主干河流、海洋、不可通行水域 → 深水（深海蓝）
- 可蹚过的小河、浅滩、窄河道 → 浅水（青蓝）
- 沼泽水面、积水洼地 → 平面水（暗蓝绿）
- 水边岸地、沙滩 → 浅米黄

如果用户没有明确区分，根据上下文合理推断。

### Step 3：构造正向提示词

正向提示词结构必须包含：
1. 地图主题与用户原意
2. 俯视正交与地形规划图要求
3. 水域布局与固定颜色（深海蓝/青蓝/暗蓝绿）
4. 地面纹理区域与固定颜色（按 RGB 协议）
5. 高度自然明暗（便于 DA3 推算深度）
6. 边界与构图要求
7. 零装饰物约束

### Step 4：构造负向提示词

负向提示词必须包含两组：

**视觉干扰组：**
透视视角、斜视角、3D场景、电影感光照、强烈定向阴影、写实摄影、景深、云雾、多光源、强烈高光、夜晚效果、文字、数字、地名、图例、罗盘、UI、水印、装饰边框、随机噪点、模糊边界

**装饰物禁止组（必须完整）：**
树木图标、树冠图案、独立树木、丛林场景、山峰插画、写实岩石、山石摆件、建筑、房屋、基地、塔楼、城墙、出生点标记、资源点图标、路标、植被贴图、草地写实效果、花朵、芦苇、船只、人物、怪物、车辆

### Step 5：输出可选参数建议

通用建议：

```
画幅：1:1 或与目标地图比例一致
风格：flat map / orthographic map / terrain planning map
清晰度：高
细节：中低
写实程度：低
随机性：中低
```

Stable Diffusion 类：CFG 5~7，Steps 25~35，Sampler DPM++ 2M Karras

Midjourney 类：--style raw，--ar 1:1，较低 stylize

---

## 正向提示词模板（中文）

```
这是一张类Majesty奇幻策略游戏的完整地图全览图，用于游戏编辑器图片转地形，主题为：{用户原始地图主题}。地图为正方形，代表约128×128格的游戏区域，包含从首都到外圈荒野的全部游戏内容。画面视角相当于从极高空俯视整个王国全境，如同策略游戏（魔兽争霸、星际争霸）的全图总览界面——首都、河流、山脉、森林、外圈荒野全部同时可见，画面内没有任何局部特写，每一处地形元素都只占画面的一小部分。
地图内容必须填满整个画布，画面四边即地图四边界，不存在画外区域，无倾斜、无透视、无留白、无装饰边框。

使用固定颜色语义表达地形类型：
- 深水/河流（不可通行）：深海蓝，约 RGB(25,55,135)；水域必须用宽阔色块表达，宽度至少占地图宽度的5%，禁止用细线代替
- 浅水（可通行河道）：青蓝色，约 RGB(70,165,205)
- 平面水/沼泽水：暗蓝绿，约 RGB(45,100,90)
- 沙滩/水边岸地：浅米黄，约 RGB(220,200,150)
- 草地平原：浅草绿，约 RGB(130,185,95)
- {其他地面纹理区域按协议颜色}
- 丘陵坡地：橄榄绿，约 RGB(100,130,60)
- 山地：棕褐色，约 RGB(130,90,55)
- 高山雪峰：灰白色，约 RGB(210,212,218)

不同地貌区域边界清晰，颜色稳定，低纹理噪声。地形高度通过自然光照明暗表现：山地和丘陵自然明亮，平原居中，低洼沼泽和河谷略暗；使用来自统一方向的柔和平行光，使高处与低处有可见的明暗层次差异，便于深度估算模型（DA3）读取高度信息。禁止电影感打光、戏剧性强阴影、多光源。

整体风格为俯视游戏地图，保留地形高低的自然光影感，适合计算机视觉进行水域识别、大陆分割和纹理分配，以及深度估算模型生成高度图。
```

## 负向提示词模板（中文）

```
【视觉干扰】不要透视视角，不要斜视角，不要电影感光照，不要戏剧性强阴影，不要多光源，不要写实摄影，不要景深，不要云雾，不要夜晚效果，不要复杂纹理，不要随机噪点，不要模糊边界，不要文字，不要数字，不要地名标签，不要图例，不要罗盘，不要UI面板，不要水印，不要装饰边框。

【装饰物禁止】不要树木图标，不要树冠图案，不要独立树木，不要丛林场景，不要山峰插画，不要写实岩石，不要山石摆件，不要建筑，不要房屋，不要基地，不要出生点标记，不要资源点图标，不要路标，不要植被贴图，不要草地写实效果，不要花朵，不要芦苇，不要船只，不要人物，不要怪物，不要车辆，不要任何装饰性图标。地面区域只用色块表达地形类型，不绘制任何装饰性图案。
```

## 正向提示词模板（英文）

```
This is a complete top-down game map overview for a Majesty-style fantasy strategy game, for game-editor image-to-terrain generation, theme: {user original map theme}. The map is square, representing approximately 128×128 grid tiles of gameplay area, encompassing everything from the capital city to the outer wilderness. The map content must fill the entire canvas — the four edges of the image are the four map boundaries, with no content outside the frame. No tilt, no perspective, no blank margins, no decorative frame.

Map layout: {preserve the user's original water/terrain/elevation layout, excluding decorations}.

Use fixed color semantics to represent terrain types:
- Deep water (impassable): dark navy blue, approx RGB(25,55,135)
- Shallow water (passable river): cyan blue, approx RGB(70,165,205)
- Plain water / swamp water: dark teal, approx RGB(45,100,90)
- Beach / waterside shore: pale beige, approx RGB(220,200,150)
- Grass plains: light grass green, approx RGB(130,185,95)
- {other ground texture zones in protocol colors}
- Hills / slopes: olive green, approx RGB(100,130,60)
- Mountains: brown, approx RGB(130,90,55)
- High peaks / snow: gray-white, approx RGB(210,212,218)

Terrain regions should have clear boundaries, stable colors, and minimal texture noise. Terrain elevation is expressed through natural lighting: mountains and hills are naturally brighter, plains are mid-tone, low swamps and valleys are slightly darker — use soft, consistent single-direction parallel lighting so that height differences are visible, enabling depth estimation models (DA3) to read elevation information. No cinematic lighting, no dramatic shadows, no multiple light sources.

Overall style: top-down game map, retaining natural lighting variation from terrain elevation, suitable for computer vision (water detection, continent segmentation, texture assignment) and depth estimation models for height map generation.
```

## 负向提示词模板（英文）

```
[Visual noise] No perspective view, no tilted view, no cinematic lighting, no dramatic shadows, no multiple light sources, no photorealistic rendering, no depth of field, no fog, no clouds, no night effects, no complex textures, no random noise, no blurry boundaries, no text, no numbers, no place labels, no legend, no compass, no UI panels, no watermark, no decorative border.

[Decoration prohibition] No tree icons, no tree canopy patterns, no individual trees, no jungle scenes, no mountain peak illustrations, no realistic rocks, no stone decorations, no buildings, no houses, no bases, no spawn point markers, no resource point icons, no road signs, no vegetation textures, no realistic grass effects, no flowers, no reeds, no boats, no characters, no monsters, no vehicles, no any decorative icons. Ground areas should be represented as color blocks indicating terrain type — no decorative patterns of any kind.
```

---

## 禁止行为

1. 禁止为了美观擅自改变地图的水域/高度/纹理结构
2. 禁止把俯视地图改成风景画、插画、写实照片
3. 禁止加入用户没有要求的地形元素
4. 禁止鼓励强阴影、透视、景深、多光源、写实摄影
5. 禁止在地形图提示词中加入任何装饰物（树木/山石/建筑/出生点/植被）
6. 禁止只输出"更漂亮"的提示词
7. 禁止省略负向提示词（尤其是装饰物禁止组）
8. 禁止将"森林"转化为树冠图标区域——森林只是深绿色纹理色块
9. 禁止将"山地"转化为山峰插画——山地只是棕色/灰棕色色块
10. 禁止将"出生点/基地/村庄"转化为建筑图标——这些由后处理放置
11. 禁止鼓励生成文字、图例、罗盘、边框、水印
12. 禁止使用电影级打光、戏剧性阴影——这会干扰 DA3 深度估算

---

## 与 y3-gen-terrain-from-image 的衔接建议

生成图片后，提醒用户：

**地形图验收标准：**
1. 正交俯视，无文字，无图例，无罗盘，无装饰边框
2. 水域颜色稳定（深水/浅水/平面水颜色有区分）
3. 地面纹理区域颜色稳定（草地/沙漠/岩石/雪地颜色有区分）
4. 无树木图标，无山峰插画，无建筑，无任何装饰物
5. 地图内容填满画布，分辨率足够清晰

**后续流程：**
1. 将地形图交给 DA3MONO-LARGE 生成高度图
2. 将地形图 + 高度图一起提供给 `y3-gen-terrain-from-image`
3. 将本次输出的"后处理参数"直接传给 `cv_postprocess_plan.py`（无特殊需求可省略）
4. 树木、植被、桥梁、道路、游戏节点由后处理自动生成
