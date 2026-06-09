---
name: y3-gen-terrain-from-image
description: 从 2D 平面地图图片生成 Y3 编辑器地形。当用户上传一张或多张地图图片（手绘草图、规划图、战略地图等）并希望在 Y3 编辑器中还原这张地图的地形时使用。触发词：从图片生成地形、图片转地形、上传地图图片生成地形、根据图片刷地形、图片生成地图。
---

# Y3 地形图片生成（y3-gen-terrain-from-image）

## 📐 前置知识：地图规格与分辨率约定

在开始任何生成流程之前，必须了解以下基础规格，所有脚本参数、提示词和识别逻辑都基于此设计。

| 参数 | 值 | 说明 |
|------|-----|------|
| **地图类型** | Y3 大型地图 | 编辑器选项中的"大型" |
| **地图格子数** | 256 × 256 | 地形网格单元数量 |
| **单元格大小** | 50 × 50 cm | 游戏世界中每格的实际尺寸 |
| **地图实际尺寸** | 128 × 128 m | 256格 × 50cm = 12800cm = 128m |
| **默认镜头可见范围** | 25 × 25 格 | 游戏运行时玩家视野范围 |
| **原图 / 高度图分辨率** | 2048 × 2048 px | 源图固定尺寸，每格对应 8×8 像素 |
| **装饰图生成方式** | 分块生成 | GPT Image 2 单次最大输出限制 |
| **装饰图分块规格** | 每块 1024 × 1024 px | 对应地图 128 × 128 格区域 |
| **装饰图分块数量** | 4 × 4 = 16 块 | 拼合后覆盖完整 2048 × 2048 |

### 装饰图分块说明

GPT Image 2 单次生成分辨率有限，装饰图需分 16 块生成后拼合：

```
┌────┬────┬────┬────┐  每块 1024×1024 px
│ 00 │ 01 │ 02 │ 03 │  对应地图格子：每块 128×128 格
├────┼────┼────┼────┤
│ 10 │ 11 │ 12 │ 13 │  格子坐标范围：
├────┼────┼────┼────┤    块(row,col) → 格x: col×128 ~ (col+1)×128
│ 20 │ 21 │ 22 │ 23 │                  格z: row×128 ~ (row+1)×128
├────┼────┼────┼────┤
│ 30 │ 31 │ 32 │ 33 │  生成时裁切对应区域的地形原图作为底图
└────┴────┴────┴────┘
```

节点坐标由 Round 3 Step 3.2 程序化强制叠加，无需在提示词中指定。  
所有块生成完毕后，用 `cv_decoration_extract.py` 拼合后整体提取。

---

通过 **Stage -1图片准备（高度灰度图→地形原图→装饰图）→ CV聚类 → AI纹理标注 → 生成CSV → MCP写入** 流程，将地图还原为 Y3 编辑器中的真实地形。

---

## Stage -1：图片准备（三张图全部确认后才能进入 Stage 0）

> ⛔ **所有图片（高度灰度图、地形原图、16 张装饰图）必须全部生成并由用户逐一确认符合要求，才能进入 Stage 0。**
> 任何图片不满足要求，返回对应步骤修改提示词，重新让用户生成。
>
> **三张图的依赖关系与核心约定：**
> - 高度灰度图：定义地形骨架（水域/陆地边界 + 海拔高度），纯灰度，无纹理，无装饰
> - 地形原图：以高度灰度图为参考底图（img2img），**仅进行纹理染色**，不改变地形布局
> - 装饰图（16块）：以地形原图裁切块为参考底图（img2img），**仅叠加植被/森林/建筑等装饰物**，不改变地形

### -1.1 风格选择 + 高度灰度图提示词

扫描 `styles/` 目录，读取每个子目录下 `rules.json` 的 `style_id`/`style_name`/`description`，展示可用风格：

| 风格 ID | 名称 | 描述 |
|---------|------|------|
| `dark_fantasy` | 暗黑奇幻 | Majesty 风格，水域广布，北部危险，压抑阴暗 |
| `temperate_fantasy` | 温带奇幻 | 草地明亮，含雪峰/火山/腐化区 |

用户选定 `<style_id>` 后，加载 `styles/<style_id>/rules.json`，询问地图主题描述（`{map_theme}`）。

**读取 `height_map_prompt` 字段，展示高度灰度图提示词：**

```
【<style_name>】高度灰度图提示词（复制到 Midjourney / DALL-E / SD 等，建议用 text2img）：

正向提示词：
[height_map_prompt.template 填充 {map_theme} 后的完整内容]

反向提示词：
[height_map_prompt.negative_prompt]

亮度协议（生成时必须严格遵守）：
  深水（≥3格宽）     → 亮度 20  （近黑）
  浅水（1-2格宽河道）→ 亮度 55
  平面水（积水洼地） → 亮度 80
  陆地 h=0（平原）   → 亮度 120
  陆地 h=2（丘陵）   → 亮度 155
  陆地 h=4（山地）   → 亮度 190
  陆地 h=6（雪峰）   → 亮度 230  （近白）

要求规格：2048×2048 px，PNG，纯灰度，无纹理，无装饰，平涂色块，无渐变

生成完毕后，将图片保存到本地，告诉我图片的完整路径。
```

> ⛔ **禁止 AI 调用任何图片生成 API**，所有图片由用户手动生成。

---

### -1.2 解析高度灰度图 + 地形原图提示词

用户提供高度灰度图路径后，AI 读取该图，按亮度协议识别：
- 水域区域（亮度 < 100）：深水 / 浅水 / 平面水 分布
- 陆地各高度区域（120 / 155 / 190 / 230）：平原 / 丘陵 / 山地 / 雪峰分布

AI 简述识别结果（各区域大致占比和分布），然后**读取 `terrain_image_prompt` 字段**，展示地形原图提示词：

```
【<style_name>】地形原图提示词（建议使用 img2img 模式，参考图 = 高度灰度图）：

正向提示词：
[terrain_image_prompt.template 填充后的完整内容]

反向提示词：
[terrain_image_prompt.negative_prompt]

img2img 约定（必须告知 AI 图像工具）：
  · 以高度灰度图为参考底图
  · 仅进行纹理染色，不改变任何地形边界
  · 水域位置、陆地轮廓、山峰位置必须与高度图完全一致

风格说明：[terrain_image_prompt.style_notes]
要求规格：2048×2048 px，PNG，俯视正交投影，无文字无图标

生成完毕后，将图片保存到本地，告诉我图片的完整路径。
```

---

### -1.3 解析地形原图 + 装饰图提示词（16 块）

用户提供地形原图路径后，AI 读取该图，分析：
- 各区域纹理分布（草地 / 山地 / 雪地 / 腐化区等）
- 水域边界和内陆水道分布

按 Round 3 的 4×4 分块方式（每块覆盖 128×128 格 = 512×512 px），AI 将地形原图在脑中划分为 16 个块区域，**读取 `decoration_image_prompt_template` 字段**，为每个块（row=0~3, col=0~3）填充提示词并一次性展示：

```
块 (row=0, col=0) 装饰图提示词（img2img 参考 = 地形原图该区域裁切）：
  · 仅在原图纹理上叠加装饰物，不改变地形
  · [base_prompt 填充 block_row=0/block_col=0/该块的地形描述]
  · 颜色协议（必须严格）：
      forest_sparse=(100,210,50)  forest_medium=(20,160,20)  forest_dense=(0,90,0)
      rock_cluster=(0,200,200)    road_main=(220,50,20)       bridge=(0,60,220)
      resource_point=(255,210,0)  monster_lair=(150,0,200)    dungeon_entrance=(70,0,150)
  输出规格：1024×1024 px，PNG，命名：decoration_block_0_0.png

块 (row=0, col=1) 装饰图提示词：
  ...（共 16 条）
```

> ⚠️ **装饰图中不包含游戏节点位置**（资源点/巢穴/地牢）—— 节点由 Round 2 规划完成后，在 Round 3 Step 3.2 程序化强制叠加，无需 AI 绘制。

用户生成 16 张装饰图，命名为 `decoration_block_{row}_{col}.png`，放入同一目录，告知目录路径。

---

### -1.4 确认所有图片（关卡检查）

| 图片类型 | 数量 | 规格要求 |
|---------|------|---------|
| 高度灰度图 | 1 张 | 纯灰度，亮度协议正确，2048×2048 px |
| 地形原图 | 1 张 | 纹理完整，地形与高度图一致，2048×2048 px |
| 装饰图 | 16 张 | 颜色协议正确，仅装饰叠加无地形改动，各 1024×1024 px |

用户逐一确认所有图片符合要求后，记录路径，进入 Stage 0：
- `<height_map_path>` — 高度灰度图（Stage 0.5 用于生成 height_grid.npy）
- `<terrain_path>` — 地形原图（Round 1 CV 聚类输入）
- `<decoration_dir>` — 装饰图目录（Round 3 直接使用）

**任何图片不满足要求 → 返回对应步骤修改提示词，重新生成该图片。**

---

## 🔄 整体架构总览

```
Stage -1 ─── 图片准备（三图全部确认后才能继续）
              ├─ -1.1 选风格 → 生成高度灰度图提示词 → 用户生成 height_map.png
              │         亮度协议：深水=20 浅水=55 平水=80 h0=120 h2=155 h4=190 h6=230
              ├─ -1.2 AI解析高度图 → 生成地形原图提示词（img2img，仅染色不改地形）
              │         → 用户生成 source_map.png
              ├─ -1.3 AI解析原图 → 生成16块装饰图提示词（img2img，仅叠加装饰不改地形）
              │         → 用户生成 decoration_block_r_c.png × 16
              └─ -1.4 用户确认三类图片全部符合要求 → 记录路径 → 进入 Stage 0

Stage 0 ──── 前置检查
              ├─ MCP 探活 + get_map_info → map_info.json
              ├─ check_cv_deps.py
              ├─ 接收路径：height_map_path / terrain_path / decoration_dir
              └─ cv_height_reader.py（height_map.png）→ height_grid.npy

Round 1 ──── 地形数据生成（以 source_map.png 为输入）
              ├─ cv_cluster.py K=20 → labels.npy / palette.json
              ├─ cv_cluster_analysis.py K=50 → palette_enhanced.json
              ├─ cv_downsample.py → labels_grid.npy
              ├─ AI 标注水域 + 三类水体分类 → water_type_clusters.json
              ├─ cv_continent_split.py → water_mask / continent_map
              ├─ cv_water_classify.py → water_type_grid.npy
              ├─ AI 分配纹理（模式C：按聚类）
              └─ gen_round1_csv.py → terrain_grid.csv / texture_grid.csv

Round 2 ──── 节点 + 道路规划（数据生成，不写 MCP）
              ├─ gen_water_map.py → bridges.json（AI 识别桥梁位置）
              ├─ cv_postprocess_plan.py → postprocess_plan.json / road_grid.npy
              ├─ 用户确认规划预览
              └─ 生成 spatial_analysis.json（节点 + 桥梁汇总，Round 3 前置）

Stage 5 ──── MCP 地形写入（仅地形+纹理）
              ├─ mcp_batch_writer.py --single-batch 1 → 地形高度 + 水域 + 纹理
              └─ cv_terrain_preview.py（可选预览）

Round 3 ──── 装饰写入（必选，Stage 5 之后）
              ├─ cv_stitch_blocks.py stitch → 拼合16张装饰图 → decoration_design.png
              ├─ Step 3.2 强制叠加节点位置（spatial_analysis.json → 彩色圆点覆盖）
              ├─ cv_decoration_extract.py → decoration_manifest.json
              ├─ AI 审查 manifest
              └─ mcp_round3_writer.py → 写入所有装饰（森林/山石/桥梁/节点/道路/植被）
```

### CSV / JSON 产出表

| 文件 | 产出阶段 | 说明 |
|------|---------|------|
| terrain_grid.csv | Round 1 | 深水/浅水/平面水 + 斜坡(slope,h) + 陆地(ground,h) |
| texture_grid.csv | Round 1 | 纹理 ID（按聚类ID精细分配） |
| postprocess_plan.json | Round 2 | 游戏节点坐标 + 道路格子 |
| bridges.json | Round 2 | 桥梁位置 + 朝向 |
| spatial_analysis.json | Round 2 | 节点+桥梁汇总（Round 3 前置） |
| decoration_manifest.json | Round 3 | 装饰布局（mcp_round3_writer.py 写入） |

### Mask / Grid 体系

| 文件 | 分辨率 | 类型 | 产出步骤 |
|------|--------|------|----------|
| height_grid.npy | 网格 | int32 | Stage 0.5（cv_height_reader.py 解析高度灰度图） |
| height_full.npy | 原图 | int32 | Stage 0.5（副产出） |
| albedo.png | 原图 | 图片 | Step 0.6（可选，去光影） |
| water_mask_full.npy | 原图 | bool | Round 1 Step 1.3 |
| water_mask_grid.npy | 网格 | bool | Round 1 Step 1.3 |
| water_type_grid.npy | 网格 | int8 | Round 1 Step 1.3b |
| continent_map_full.npy | 原图 | int32 | Round 1 Step 1.3 |
| continent_map_grid.npy | 网格 | int32 | Round 1 Step 1.3 |
| distance_map.npy | 网格 | float32 | Round 2 Step 2.1 |
| road_grid.npy | 网格 | bool | Round 2 Step 2.1 |

---

## 🧠 Y3 地形常识（AI 必须遵守）

| # | 常识 | 说明 |
|---|------|------|
| 1 | **AI 看 RGB 判断颜色** | palette.json 中有 `rgb` 字段，AI **必须**使用 `rgb` 字段判断颜色，**禁止**自行从 `bgr` 字段转换 |
| 2 | **CV 只做特征聚类** | CV 做颜色/明度等特征聚类，但不做任何语义判断（不标注水/陆地），所有语义判断由 AI 完成 |
| 3 | **cliff_tex_id 全部默认 0** | cliff_tex_id 统一为 0 |
| 4 | **高度来自高度灰度图** | Stage -1.1 生成的高度灰度图使用固定亮度协议（h0=120/h2=155/h4=190/h6=230），由 cv_height_reader.py 解析为 height_grid.npy，不再依赖 AI 语义推断 |
| 5 | **albedo 替代原图** | Step 0.6 de-lighting 后，所有 CV 步骤使用 albedo.png；跳过 Step 0.6 时直接用地形原图 |
| 6 | **纹理有两种分配模式** | 模式B（按大陆组，avg_rgb接近时只能1种纹理）；**模式C（推荐，按聚类ID，每个簇独立纹理，需 labels_grid.npy）** |
| 7 | **Y3 三类水体必须区分** | 深水（挖2层，不可通行）/ 浅水（挖1层，可通行，有悬崖边）/ 平面水（不挖，铺在地面）。**引擎 spread_water_type 规则**：刷水后 DFS 感染所有相连水格统一类型，深水/浅水不能直接相邻否则互相覆盖 |
| 8 | **cliff 在 Y3 中专指裂缝** | `cliff` = terrain_height=-40 的地形空洞（不可通行），**不是悬崖或山峰**。山峰是 ground 高地 + 装饰摆件，通过 terrain_set_crack_block 写入 |

---

## ⛔ 全局禁令（最高优先级）

| # | 禁令 | 正确做法 |
|---|------|----------|
| 1 | ⛔ **禁止 AI 输出坐标/锚点/多边形** | AI 只定义语义，空间定位由 CV 完成 |
| 2 | ⛔ **禁止 AI 描述区域边界** | 不写"x:10~50, z:20~80"、"左岸锚点"等 |
| 3 | ⛔ **禁止跳过 CV 聚类直接生成 CSV** | 必须先运行对应轮次的 CV 脚本 |
| 4 | ⛔ **禁止跳过 CSV 直接调 MCP** | 必须读 CSV 逐格调 MCP |
| 5 | ⛔ **禁止跳过 CV 依赖检测** | 没有 opencv/numpy 就不能继续 |
| 6 | ⛔ **禁止跳过用户确认直接写入 MCP** | Round 2 规划结果必须经用户确认后才能进入 Stage 5 写入 |
| 7 | ⛔ **禁止猜测地图尺寸** | 必须从 get_map_info 获取 |
| 8 | ⛔ **MCP 连接失败时禁止继续任何后续步骤** | 必须提示用户连接 y3editor MCP 后重试，不得用 read_map_size.py 替代 |
| 9 | ⛔ **禁止将所有水域统一写为 deep_water** | 必须跑 cv_water_classify.py 生成 water_type_grid.npy，gen_round1_csv.py 必须传 --water-type-grid，否则引擎 spread_water_type 会把浅水全部感染为深水 |
| 10 | ⛔ **禁止用像素亮度跨色相比较来判断高度** | 深棕火山比浅绿草地暗，但火山是高地。明度只在同一色相区域内有效（见 y3-terrain-basics.md），跨色相应使用语义高度分配 |
| 11 | ⛔ **禁止跳过 Step 1.3b 水体类型分类** | 即使 Step 1.2 区分了水域簇，也必须生成 water_type_clusters.json 并跑 cv_water_classify.py |

---

## Stage 0：前置检查

### 0.1 MCP 探活 + 获取地图信息

调用 `get_map_info`（无参数），返回 JSON 包含 `project_path`、`map_name`、`map_path`、`width`、`height`。

**必须将返回的 JSON 保存到 `<output_dir>/map_info.json`**，后续脚本会自动从此文件读取地图尺寸，**AI 不再需要手动传入 width/height 参数**。

```python
import json
map_info = {...}  # get_map_info 返回内容
with open("<output_dir>/map_info.json", "w") as f:
    json.dump(map_info, f, indent=2)
```

若调用失败（MCP 未连接、返回错误、超时等任何异常），**必须立即终止整个流程，禁止继续任何后续步骤**。输出以下提示并等待用户响应：
```
⚠️ 无法连接到 Y3 Editor MCP Server，流程已终止！
请检查：
1. Y3 编辑器是否已打开？
2. y3editor MCP Server 是否已连接？（检查 CodeMaker MCP 面板）
3. 目标地图是否已加载？
确认后告诉我"重新检查"。
```

> 🔴 **严禁降级处理**：不得尝试从 `read_map_size.py`、`terrain.json`、历史缓存或任何其他来源获取地图尺寸。
> `get_map_info` 是获取地图信息的 **唯一合法来源**，连接失败就是失败，没有 Plan B。

### 0.2 CV 依赖检测（静默自动安装）

运行：
```bash
python scripts/check_cv_deps.py
```

脚本会自动检测并在缺失时静默安装依赖，**无需用户介入**。

| 结果 | 处理 |
|------|------|
| `{"status": "ok", ...}` | ✅ **静默继续**，不输出任何信息给用户 |
| `{"status": "missing", "install_failed": true, ...}` | ⚠️ 提示用户："自动安装 `<missing>` 失败，请手动执行 `pip install <missing>` 后告诉我'重新检查'。" |

### 0.3 确认图片路径 + 规划参数

Stage -1 已完成三类图片准备，此处确认路径和规划参数：

> "请确认以下路径（来自 Stage -1）：
>
> **当前风格**：`<style_id>`
>
> **图片路径：**
> 1. **高度灰度图路径**（height_map）：Stage -1.1 生成的灰度图
> 2. **地形原图路径**（terrain_map）：Stage -1.2 生成的彩色地图
> 3. **装饰图目录**（decoration_dir）：Stage -1.3 生成的16张图所在目录
>
> **规划参数（可选）：**
> 4. **首都/出生区位置**：如 `center`（默认）、`32,48`（具体格坐标）等
> 5. **节点数量偏好**：如 `resource=5,lair=8,dungeon=2,ruin=6`"

记录：`<height_map_path>`、`<terrain_path>`、`<decoration_dir>`、`<capital>`（默认 `center`）、`<node_counts>`（默认空）、`<style_id>`。

### 0.4 创建工作输出目录

所有轮次的中间文件和最终 CSV **统一输出到** `<skill_dir>/output/` 目录：

```
<dir> = .codemaker/skills/y3-gen-terrain-from-image/output/
```

后续所有脚本的 `--output-dir` 参数统一使用此路径。

> ⚠️ AI **禁止**自行选择其他工作目录（如 `terrain_gen_work/`），必须使用 `<skill_dir>/output/`。

### 0.5 高度图读取（必须执行）

高度灰度图使用固定亮度协议（Stage -1.1 约定），阈值可直接推导：

| 分界 | 阈值 | 说明 |
|------|------|------|
| 水域 / h=0 | 100 | 亮度<100为水域（20/55/80），≥100为陆地 |
| h=0 / h=2 | 137 | (120+155)/2 |
| h=2 / h=4 | 172 | (155+190)/2 |
| h=4 / h=6 | 210 | (190+230)/2 |

```bash
python scripts/cv_height_reader.py <height_map_path> \
  --output-dir <dir> \
  --grid-size <W>x<H> \
  --thresholds 137,172,210 \
  --height-values 0,2,4,6
```

> ⚠️ 水域区域（亮度 20/55/80）会被读为 h=0，这是正常的 —— 水域的实际高度由 Round 1 的 water_mask 独立控制，gen_round1_csv.py 会以 water_mask 为准覆盖。
> ⚠️ 若高度图存在大量孤立碎片，运行 Step 0.5b 平滑处理。

输出：`height_full.npy`、`height_grid.npy`、`height_grid_preview.png`

查看预览图确认 h=4/h=6 区域与原图山峰/雪峰位置一致。

### 0.5b【可选】高度网格平滑

仅当高度图产生大量孤立小区域（碎片化）时运行：

```bash
python scripts/cv_height_smooth.py \
  --height-grid <dir>/height_grid.npy \
  --water-mask  <dir>/water_mask_grid.npy \
  --output-dir  <dir> \
  --min-area 8
```

> min-area 推荐：64×64 用 4，128×128 用 8，256×256 用 16。

### 0.6【可选，需高度图】De-lighting — 去光影提取纹理贴图

> 可选步骤。若地形原图存在明显光照阴影影响纹理识别，可运行去光影处理。后续 CV 步骤改用 albedo.png；否则跳过，直接使用 terrain_path 原图。

```bash
python scripts/cv_delighting.py <terrain_path> <height_path> \
  --output-dir <dir>
```

输出：`albedo.png`（后续 CV 步骤改用此图替代原图）、`cast_shadow_mask.npy`。

若 albedo 效果异常（颜色偏差大），可手动指定光源方向重跑：
```bash
python scripts/cv_delighting.py <terrain_path> <height_path> \
  --output-dir <dir> --light-az 135 --light-el 45
```

---

## Round 1：水域 + 大陆连通分割 + 纹理

> **目标**：剥离水域，识别大陆连通区域，为每个大陆分配基础纹理。
> **AI Prompt 模板**：`templates/round1_water_continent_prompt.md`

### Step 1.1：CV 色相聚类

> **输入图片**：优先使用 Step 0.6 输出的 `albedo.png`（若已运行去光影）；否则直接使用 `<terrain_path>` 地形原图。

**K 值选择**：

> 💡 **风格感知（优先）**：先读取 `styles/<style_id>/rules.json` 的 `cv_hints.recommended_k`，以该值为准。
> 当前 `dark_fantasy` 风格推荐 **K=20**（原因：`cv_hints.complexity_reason`）。
> 仅当 cv_hints 未定义时，参考下表手动选择。

| 地图类型 | 推荐 K | 原因 |
|---------|--------|------|
| 简单地图（色彩区域清晰，颜色差异大） | K=15 | 簇数少，语义清晰 |
| 复杂地图（暗黑奇幻等，含相近暗色区域） | **K=20** | 分离相近暗色（如火山深棕 vs 腐化深紫 vs 深水，K=15 时会混入同一簇） |
| 颜色极复杂 | K=25 | 酌情提高 |

> ⚠️ 若某些语义区域颜色相近（如火山深棕与腐化深紫 rgb 差距 <20），K=15 会将其归入同一簇导致无法独立分配纹理/高度，必须提高 K 值。

```bash
# 使用地形原图（默认）；若已运行 Step 0.6，改用 <dir>/albedo.png
python scripts/cv_cluster.py <terrain_path> \
  --k 20 \
  --hsv-weights 2.0,1.0,0.8 \
  --output-dir <dir>
```

输出：
- `cluster_preview.png` — 像素分辨率预览图
- `palette.json` — 每簇 RGB/BGR/HSV + 占比
- `labels.npy` — 高分辨率聚类标签矩阵（2048×2048 等原图分辨率）
- `centers_bgr.npy` — 簇中心 BGR

**同步生成网格分辨率标签（供 per-cluster 纹理分配使用）：**

```bash
python scripts/cv_downsample.py <dir>/labels.npy \
  --width <W> --height <H> \
  --linear-clusters <水域簇ID,如1,4,6> \
  --output-dir <dir>
```

> `<W>x<H>` = get_map_info 返回的网格尺寸。`--linear-clusters` 传水域簇 ID（Step 1.2 完成后可回填，或跳过先用多数投票）。
> 输出 `labels_grid.npy`（网格分辨率，每格对应一个聚类 ID），供 Step 1.6 的 `--cluster-texture-config` 模式使用。

### Step 1.1b：双重聚类交叉分析（增强水域识别）

在粗聚类(K=20)基础上，新增细聚类(K=50)并做交叉分析，为每个粗簇补充内部纹理复杂度、颜色统计、空间形态等多维特征，帮助 AI 精确区分水域与深色陆地。

```bash
python scripts/cv_cluster_analysis.py <dir>/cropped.png \
  --labels-coarse <dir>/labels.npy \
  --palette <dir>/palette.json \
  --k-fine 50 \
  --output-dir <dir>
```

> `cropped.png` 是 cv_cluster.py 对 albedo.png 自动裁剪后的版本（边缘文字去除），已存于 `<dir>/`。

输出：
- `labels_fine.npy` — K=50 细聚类标签矩阵
- `palette_enhanced.json` — 增强色板（palette.json 超集），每个簇新增：
  - `internal_complexity`: 内部微簇数量、Shannon 熵、主导微簇占比、Top-5 微簇明细(含 RGB)
  - `color_stats`: RGB 标准差、RGB 极差、Laplacian 方差（纹理能量）
  - `spatial_shape`: 紧凑度、长宽比、连通区域数、最大区域占比
  - `border_neighbors`: 边界接触的其他簇 ID 列表

### Step 1.2：AI 标注水域簇 + 同步完成三类水体分类

AI 看 `cluster_preview.png` + `palette_enhanced.json`（**使用 `rgb` 字段判断颜色**）+ 原图，**同步完成两件事**：

> 💡 **风格感知（优先）**：先读取 `styles/<style_id>/rules.json` 的 `cv_hints.water_color_hints`，
> 以其定义的 `deep_water_rgb_range` / `shallow_water_rgb_range` / `plain_water_rgb_range` 作为水域识别的**第一判据**。
> RGB 落在范围内的簇优先判定为对应水体类型，再结合 `internal_complexity` / `spatial_shape` 辅助确认。
> `cv_hints.cluster_analysis_notes` 记录了该风格下易混淆色的说明，识别前必须阅读。

**① 判断水域 vs 陆地**（使用 `internal_complexity` / `color_stats` / `spatial_shape` 辅助）

**② 对水域簇按 Y3 三类水体规则进行分类**

**Y3 三类水体判断规则**（来自 `references/y3-terrain-basics.md`）：

| 原图特征 | Y3 类型 | 引擎行为 |
|---------|---------|---------|
| 深蓝大海、大湖（≥3格宽，无桥） | `deep_water` | 挖2层悬崖，不可通行，深蓝不透明 |
| 浅蓝海岸带、1~2格宽河道 | `shallow_water` | 挖1层，可通行但有悬崖边（类似河道截面）|
| 内陆细水道、积水洼地（<1格宽） | `plain_water` | 不挖地形，直接铺在地面，几乎透明 |

> ⚠️ **spread_water_type 感染规则**：引擎刷水后 DFS 感染所有相邻水格统一类型。深水与浅水如果直接相邻，后写的类型会覆盖先写的。因此 CSV 中三类水体必须正确区分，MCP 写入顺序按 deep→shallow→plain。

以表格展示所有簇，标记水域分类：

| 簇 ID | RGB | 占比 | 判断 | Y3水体类型 |
|--------|-----|------|------|------------|
| 16 | [6, 47, 114] | 20.9% | ✅ 水域 | deep_water |
| 0  | [15, 83, 130] | 4.4% | ✅ 水域 | deep_water |
| 17 | [35, 125, 150] | 5.6% | ✅ 水域 | shallow_water |
| 4  | [57, 144, 158] | 3.1% | ✅ 水域 | plain_water |
| 2  | [113, 142, 64] | 21.2% | 陆地 | — |

**同步输出 `water_type_clusters.json`**（Step 1.3b 直接使用）：

```json
{
  "deep_water_clusters":    [16, 0],
  "shallow_water_clusters": [17],
  "plain_water_clusters":   [4],
  "all_water_clusters":     [16, 0, 17, 4]
}
```

展示后直接记录，**无需用户确认，直接继续**。

### Step 1.3：CV 大陆连通分割

```bash
python scripts/cv_continent_split.py <dir>/labels.npy --water-clusters 5,1,11 --image <dir>/cropped.png --output-dir <dir>
```

> 🔴 **`--image` 必须传 `cropped.png`（裁剪后的图片），不能传原始图片！**
> `labels.npy` 是基于裁剪后图片聚类的，两者尺寸必须对应。

输入：`labels.npy` + 水域簇 ID 列表 + 裁剪后图片路径（`--image`，推荐传入） + 地图尺寸
处理：
1. 在原图 labels 上将水域簇像素标记为 mask
2. 对非水域像素用 `cv2.connectedComponents` 做连通分割
3. 桥梁碎片过滤
4. 下采样 water_mask 和 continent_map 到网格分辨率

输出：
- `water_mask_full.npy` / `water_mask_grid.npy` — 水域 mask
- `continent_map_full.npy` / `continent_map_grid.npy` — 大陆编号图（0=水域, 1~N=大陆）
- `continent_summary.json` — 各大陆面积、bbox、avg_rgb（传入 `--image` 时含平均 RGB）
- `continent_preview.png` — 大陆分区可视化（不同颜色）

### Step 1.3b：水域类型分类（必须执行）

使用 Step 1.2 输出的 `water_type_clusters.json`，将簇标签映射到网格：

```bash
python scripts/cv_water_classify.py \
  --labels      <dir>/labels.npy \
  --water-types <dir>/water_type_clusters.json \
  --water-mask  <dir>/water_mask_grid.npy \
  --output-dir  <dir>
```

输出：
- `water_type_grid.npy` — 每格水体类型（0=陆地, 1=深水, 2=浅水, 3=平面水）
- `water_type_preview.png` — 水体类型分布可视化

> ⛔ **此步骤不可跳过**（见全局禁令 #9）。`gen_round1_csv.py` 必须传入 `--water-type-grid`，否则全部写为 deep_water，浅水海岸带/内陆水道全部消失。

### Step 1.4：纹理分组 + AI 分配纹理（两步法）

#### Step 1.4a：运行脚本自动分组（确定性）

```bash
python scripts/gen_round1_csv.py \
  --water-mask <dir>/water_mask_grid.npy \
  --continent-map <dir>/continent_map_grid.npy \
  --output-dir <dir> \
  --group-only
```

脚本自动完成：
- 读取 `continent_summary.json` 的 `avg_rgb`
- 用 Union-Find 将 RGB 欧氏距离 < 30 的大陆归为同一**纹理组**
- 面积 ≤ 5 的碎片大陆不参与分组（后续自动继承邻近大陆纹理）
- 输出 `texture_groups.json`（含每组的大陆列表、加权 avg_rgb、面积）

> ⛔ **禁止 AI 自己写分组脚本或手动计算距离**，必须调用上述脚本

#### Step 1.4b：AI 分配纹理 + 【方案A】语义高度

**纹理分配（两种模式）**：

**模式 C（推荐，按聚类 ID，精细纹理）**：每个色簇独立分配纹理，适合大部分地图。

AI 看 `palette.json` 各簇 RGB + `references/texture-color-map.md`，为每个聚类 ID 分配纹理：

```json
{
  "2": 170,  "7": 146,  "9": 2,   "11": 24,
  "12": 185, "15": 53,  "10": 90, "8": 193
}
```

> 模式 C 需在 Step 1.6 中使用 `--cluster-texture-config` 和 `--labels-grid` 参数。

**模式 B（按大陆组）**：仅当各大陆颜色差距明显（avg_rgb 距离 > 30）且无需精细纹理时使用。

### Step 1.4c：纹理面板确保（自动）

AI 收集 Step 1.4b 中分配的所有纹理 ID，调用 MCP 接口 `ensure_terrain_textures` 自动将缺失纹理添加到编辑器面板：

```
调用 ensure_terrain_textures(texture_ids=[194, 109, ...])
```

**根据返回结果处理**：

| 字段 | 处理 |
|------|------|
| `added` 非空 | ✅ 纹理已自动添加到面板，继续 |
| `failed` 非空 | ⚠️ 面板已满（32个上限），将 failed 中的纹理替换为 `current` 列表中最接近的已有纹理，更新 Step 1.4 的纹理分配 JSON |
| `not_downloaded` 非空 | ⚠️ 提示用户手动下载对应纹理或选择替代纹理 |
| 所有字段正常 | ✅ 直接继续生成 CSV |

> ⚠️ **必须在生成 CSV 之前完成此步骤**，否则 MCP 写入纹理时可能静默失败。

### Step 1.5b【可选】高度边界分析

仅在使用方案B（高度图）且需要斜坡规划时运行：

```bash
python scripts/cv_height_boundary.py \
  --continent-map <dir>/continent_map_grid.npy \
  --water-mask    <dir>/water_mask_grid.npy \
  --height-grid   <dir>/height_grid.npy \
  --output-dir    <dir>
```

输出：`height_boundary_report.json`、`height_boundary_preview.png`

> 若报告中出现高差 > 2 的边界，回到 Step 1.4b 调整高度分配（相邻大陆高差 ≤ 2），再重新运行。

### Step 1.5c【可选】自动斜坡规划

仅在地图设计需要可通行斜坡（高低地连接）时运行：

```bash
python scripts/cv_slope_auto.py \
  --height-grid <dir>/height_grid.npy \
  --water-mask  <dir>/water_mask_grid.npy \
  --output-dir  <dir> \
  --target-slope-pct 12 \
  --sparse-step 4
```

输出：`slope_decision.json`（`slope_cells` 列表，传给 gen_round1_csv.py `--slope-decisions`）

> 无需斜坡时跳过此步骤，gen_round1_csv.py 省略 `--slope-decisions` 参数。

---

### Step 1.5：水域后处理（按需执行，非必须）

> ⚠️ **执行前必须判断地图是否有内陆水体**：

```bash
python scripts/water_postprocess.py <dir>/water_mask_grid.npy
```

脚本行为：检测所有未接触地图四边的孤立水域，**将其填回陆地**。

| 地图特征 | 是否执行 |
|---------|---------|
| 地图中无内陆湖泊/河流（水域只在边界） | ✅ 可执行，清除聚类噪声 |
| 地图中有内陆湖泊、河流、水道 | ⛔ **跳过**，执行后内陆水体将被填为陆地，永久丢失 |

> 跳过此步骤的地图，内陆水体由 cv_continent_split.py 的桥梁碎片过滤保留，数量以实际输出为准。

### Step 1.6：调用脚本生成 terrain_grid.csv(final) + texture_grid.csv(final)

**模式 B（按大陆组分配纹理，有高度图）**：

```bash
python scripts/gen_round1_csv.py \
  --water-mask           <dir>/water_mask_grid.npy \
  --continent-map        <dir>/continent_map_grid.npy \
  --group-texture-config '{"1": 194, "2": 109, "3": 147}' \
  --height-grid          <dir>/height_grid.npy \
  --water-type-grid      <dir>/water_type_grid.npy \
  --boundary-report      <dir>/height_boundary_report.json \
  --slope-decisions      <dir>/slope_decision.json \
  --output-dir           <dir>
```

**模式 C（按聚类 ID 分配纹理，per-pixel 精细纹理）**：

```bash
python scripts/gen_round1_csv.py \
  --water-mask              <dir>/water_mask_grid.npy \
  --continent-map           <dir>/continent_map_grid.npy \
  --cluster-texture-config  '{"0":194,"3":165,"7":165,"9":146,"11":171,"13":132,"14":170}' \
  --labels-grid             <dir>/labels_grid.npy \
  --height-grid             <dir>/height_grid.npy \
  --water-type-grid         <dir>/water_type_grid.npy \
  --boundary-report         <dir>/height_boundary_report.json \
  --slope-decisions         <dir>/slope_decision.json \
  --default-texture         194 \
  --output-dir              <dir>
```

> `--slope-decisions` 接受两种格式，脚本自动识别：
> - **cv_slope_auto.py 输出**（像素级）：`{"mode":"pixel_level","slope_cells":[...]}`，**不需要 `--boundary-report`**
> - **旧版手动决策**：`{"decisions":[{"boundary_id":...,"traversable":...}]}`，需要 `--boundary-report`
>
> **无水体类型分类时**：省略 `--water-type-grid`，全部默认深水。

脚本自动完成：
- 按组展开纹理/高度到所有大陆（同组同纹理/同高度）
- 碎片大陆 → 自动继承最近大陆纹理（高度同理）
- **terrain_grid.csv(final)**：
  - 深水格 → `deep_water,0,{cid}`
  - 浅水格 → `shallow_water,0,{cid}`
  - 平面水格 → `plain_water,0,{cid}`
  - 斜坡格 → `slope,{h},{cid}`
  - 陆地格 → `ground,{h},{cid}`
- **texture_grid.csv(final)**：水域格→`0`，陆地格→对应纹理 ID
- 输出高度分布统计（h=0/2/4/6 各格数）和水体类型分布（深水/浅水/平面水）

> ⛔ **禁止 AI 自行编写脚本生成 CSV**，必须调用 `scripts/gen_round1_csv.py`
> ⛔ **禁止省略 `--water-type-grid` 参数**，否则所有水域默认写为 deep_water，浅水/平面水消失（违反 Y3 水体设定）
> ⛔ **模式C（--cluster-texture-config）时禁止跳过 Step 1.4a 的 --group-only 分组步骤**

---

## Round 2：后处理 — 装饰物 + 游戏节点 + 道路 + 植被

> **目标**：基于地形数据（高度/纹理/水域）+ 用户描述，规则驱动生成装饰物、游戏节点、道路网络和植被。不再依赖图片识别，全部由地形数据驱动。

### Step 2.0：桥梁识别（保留，从地形图识别）

生成水域字符地图，AI 看地形图识别桥梁位置：

```bash
python scripts/gen_water_map.py <dir>/terrain_grid.csv <dir>/water_map.txt
```

AI 看 `<terrain_path>`（原始地形图）+ `water_map.txt`，识别所有跨水域的桥梁结构：
- 找到水域上的棕色/浅色短条结构
- 对照 `water_map.txt` 确认坐标落在 `W` 格子上
- 记录 `bridges: [{"x": ..., "z": ..., "yaw": ...}]`

将桥梁数据保存到 `<dir>/bridges.json`，供后续合并写入。

---

### Step 2.1：后处理规划（自动，Majesty 类游戏风格）

```bash
python scripts/cv_postprocess_plan.py \
  --height-grid  <dir>/height_grid.npy \
  --texture-grid <dir>/texture_grid.csv \
  --water-mask   <dir>/water_mask_grid.npy \
  --map-info     <dir>/map_info.json \
  --output-dir   <dir> \
  --capital      "<capital>" \
  --node-counts  "<node_counts>" \
  --game-style   majesty
```

> `<capital>` 和 `<node_counts>` 来自 Stage 0.3 收集的用户参数（或 y3-optimize-terrain-image-prompt 的"后处理参数"节）。
> 未提供时省略这两个参数，脚本使用默认值（首都自动检测中心平地，节点数按地图面积计算）。

脚本自动完成（无需 AI 参与）：

| 步骤 | 逻辑 |
|------|------|
| 确定首都 | 中心区域最近 h=0 陆地格 |
| 距离场 | Dijkstra 从首都出发，地形成本加权（平原×1，丘陵×3，山地×8） |
| 资源点 | 中圈（30~62%距离），平地优先，分散放置 |
| 怪物巢穴 | 外圈（48~82%距离），任意地形 |
| 地牢 | 最外圈（62~100%），山地优先 |
| 遗迹 | 全图散布（15~100%） |
| 道路 | A* 从首都连接所有资源点/地牢/巢穴 |
| 树木/山石 | 地形规则（h=0~2→树，h≥4→石），避开道路和节点 |

输出：
- `postprocess_plan.json` — 完整规划（所有节点坐标 + 装饰物位置）
- `distance_map.npy` — 距离场
- `road_grid.npy` — 道路格子
- `postprocess_preview.png` — **可视化预览（首都/节点/道路/地形叠加图）**

### Step 2.2：AI 审查规划（需用户确认）

AI 展示 `postprocess_preview.png` 给用户，并汇报规划摘要：

```
规划摘要：
  首都：(x, z)
  资源点：N 个（位置列表）
  怪物巢穴：N 个
  地牢：N 个
  遗迹：N 个
  道路：N 格
  树木：N 个 / 山石：N 个

是否满意？如需调整，可：
  - 重新指定首都位置（--capital "x,z"）
  - 调整节点数量（--node-counts "resource=5,lair=8"）
  - 手动修改 postprocess_plan.json 中的节点坐标
```

用户确认后继续。若需重跑，修改参数后重新执行 Step 2.1。

---

### Step 2.3：生成 spatial_analysis.json（Round 3 前置，必须完成）

> `spatial_analysis.json` 是 Round 3 的唯一前置输入，汇总了节点位置和桥梁候选坐标，供 `gen_gray_context.py` 叠加彩色圆点，以及 Round 3 Step 3.5 强制覆盖游戏节点。

从 `postprocess_plan.json`（节点）和 `bridges.json`（桥梁）合成：

```python
import json, pathlib

run = pathlib.Path('<dir>')
plan = json.loads((run / 'postprocess_plan.json').read_text(encoding='utf-8'))
bridges_raw = json.loads((run / 'bridges.json').read_text(encoding='utf-8')) \
    if (run / 'bridges.json').exists() else []

def nodes_of(type_):
    return [{'x': n['x'], 'z': n['z']} for n in plan.get('nodes', []) if n['type'] == type_]

spatial = {
    'resource_points':   nodes_of('resource'),
    'monster_lairs':     nodes_of('lair'),
    'dungeon_entrances': nodes_of('dungeon'),
    'bridge_candidates': [{'x': b['x'], 'z': b['z']} for b in bridges_raw],
    'capital':           plan.get('capital', {}),
    'road_grid_path':    str(run / 'road_grid.npy'),
}
(run / 'spatial_analysis.json').write_text(
    json.dumps(spatial, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"spatial_analysis.json saved — nodes: {sum(len(v) for v in spatial.values() if isinstance(v,list))}")
```

输出：`spatial_analysis.json`（Round 3 Step 3.1 / 3.5 读取）

---

## Stage 5：MCP 批量写入

> **核心原则**：AI 通过 **循环调用** `mcp_batch_writer.py --single-batch 1` 完成地形+纹理写入。
> ⛔ **禁止跳过 CSV 直接凭记忆调 MCP。禁止 AI 逐块调用 use_mcp_tool。**
> ⛔ **禁止 AI 在循环写入期间做任何其他操作（不调 use_mcp_tool、不编写脚本、不修改文件）。**
> ⛔ **禁止 AI 以"脚本卡住"为由自行中断或换方案。每次调用最多等待 ~30 秒。**
> ⛔ **禁止 AI 修改 `--single-batch` 参数值。必须始终为 1，不得改为 10/50 或其他值。**
> ⛔ **禁止 AI 在命令后面加管道（`| findstr` / `| grep`）或用 `for /L` 循环包裹命令。**
>
> 💡 **设计说明**：`--single-batch 1` 每次执行 100 格、约 5 秒返回。这个频率是刻意设计的——
> 让 AI 保持调用心跳，防止长时间无响应导致超时断连。不要试图"优化"这个参数。

### 5.1 单批循环模式（默认）

AI **必须**使用 `--single-batch 1` 模式循环调用脚本。每次调用执行 1 批（100 格），约 5 秒后返回。
**参数 `1` 不可更改**——这是保持 AI 调用心跳的关键设计，不是性能瓶颈。

**循环模板（AI 严格按此执行）：**

```
重复执行以下步骤，直到 BATCH_RESULT 的 status == "all_done"：

1. 执行命令:
   python scripts/mcp_batch_writer.py \
     --terrain-csv <dir>/terrain_grid.csv \
     --texture-csv <dir>/texture_grid.csv \
     --single-batch 1

2. 查看 stdout 最后一行的 BATCH_RESULT:
   - status == "in_progress" → 打印进度，继续步骤 1
   - status == "pass_complete" → 打印已完成的 pass，继续步骤 1
   - status == "all_done" → 退出循环，地形写入完成，继续 Round 3
   - 命令执行失败（非零退出码）→ 报错停止，等待用户指令

3. ⛔ 禁止在步骤 1 和步骤 2 之间做任何其他操作
```

**BATCH_RESULT 输出格式**（脚本 stdout 最后一行）：

| status | 含义 | AI 行为 |
|--------|------|---------|
| `in_progress` | 当前 pass 未完成 | 继续调用 |
| `pass_complete` | 当前 pass 完成，还有下一个 | 继续调用 |
| `all_done` | 全部写入完成 | 退出循环 |

脚本内部写入顺序（严格不可调换）：
- **Pass 1: Crack** — 裂缝（精简版中无 crack 数据，自动跳过）
- **Pass 2: Ground Height** — 地形高度（逐层叠加写入，有高度数据时生效）
- **Pass 3: Water** — deep_water 写入
- **Pass 4: Slope** — 斜坡（精简版中无 slope 数据，自动跳过）
- **Pass 5: Texture** — 纹理统一刷

> ⚠️ **所有地形 MCP 接口只需传 `cliff_tex_id`**，引擎内部自动查表获取 cliff_type/cliff_mat/cliff_texture 三件套。
> ⚠️ **不要传 cliff_mat / cliff_type / cliff_texture / mesh_type**，这些参数已移除。

### 5.2 可选参数

| 参数 | 说明 |
|------|------|
| `--single-batch [N]` | 单批模式，每次执行 N 批后退出（默认 1，即 100 格/次） |
| `--dry-run` | 只解析 CSV 并输出统计，不实际写入 |
| `--restart` | 忽略进度文件，从头开始 |
| `--url <url>` | 覆盖 MCP Server URL |
| `--timeout <s>` | MCP 调用超时秒数（默认 300） |

> 💡 **备选全量模式**：不传 `--single-batch` 时脚本一口气执行所有 Pass（用户手动运行时使用，AI 不应使用此模式）。

### 5.3 输出完成摘要 + 地形预览图（可选）

地形写入完成后输出摘要，然后进入 Round 3：

```
✅ 地形写入完成（Stage 5）
  - 总格子数：65536
  - ground: N 格 | deep_water: N 格 | slope: N 格
  - 纹理覆盖：N 格

→ 下一步：Round 3 装饰图设计层
```

可选：生成预览图验证地形效果后再进入 Round 3：

在写入 Y3 前或后，可以随时生成预览图验证地形效果：

```bash
# 高度色模式（快速验证高度分布）
python scripts/cv_terrain_preview.py \
  --terrain-csv <dir>/terrain_grid.csv \
  --output-dir  <dir> \
  --scale 4

# 纹理色模式（更接近实际效果）
python scripts/cv_terrain_preview.py \
  --terrain-csv <dir>/terrain_grid.csv \
  --texture-csv <dir>/texture_grid.csv \
  --output-dir  <dir> \
  --scale 4
```

输出 `terrain_preview_height.png` 或 `terrain_preview_texture.png`。颜色含义：
- 深蓝=深水，青蓝=浅水，暗绿=平面水
- 浅绿=h=0平原，橄榄绿=h=2丘陵，棕褐=h=4山地
- **黄橙色=斜坡**（高亮显示，便于检查连通性）

---

## 文件结构

```
y3-gen-terrain-from-image/
├── SKILL.md                                ← 本文件
├── output/                                 ← ⭐ 统一工作输出目录（每次任务建子目录如 output/01/）
│   ├── source_map.png                      ← 原始地形图副本（规避中文路径）
│   ├── cropped.png                         ← Round 1: 自动裁剪后原图（去边缘文字）
│   ├── cluster_preview.png                 ← Round 1: 聚类预览
│   ├── cluster_preview_labeled.png         ← Round 1: 带簇 ID 标注预览
│   ├── cluster_preview_grid.png            ← Round 1: 网格分辨率聚类预览
│   ├── palette.json / palette.png          ← Round 1: K 簇色板
│   ├── palette_enhanced.json               ← Round 1: 增强色板（含复杂度/空间形态）
│   ├── labels.npy / centers_bgr.npy        ← Round 1: 原图分辨率聚类标签
│   ├── labels_fine.npy                     ← Round 1: K=50 细聚类标签
│   ├── labels_grid.npy                     ← Round 1: 网格分辨率聚类标签（模式C纹理分配用）
│   ├── cluster_grid.csv                    ← Round 1: 网格聚类 ID 文本格式
│   ├── water_type_clusters.json            ← Round 1: AI 定义三类水体簇（Step 1.2 输出）
│   ├── water_type_grid.npy                 ← Round 1: 水体类型网格（0=陆,1=深,2=浅,3=平面）
│   ├── water_type_preview.png              ← Round 1: 水体类型分布可视化
│   ├── water_mask_full.npy / *_grid.npy    ← Round 1: 水域 mask（全图/网格分辨率）
│   ├── continent_map_full.npy / *_grid.npy ← Round 1: 大陆编号图
│   ├── continent_summary.json              ← Round 1: 大陆面积/bbox/avg_rgb
│   ├── continent_preview.png               ← Round 1: 大陆分区可视化
│   ├── texture_groups.json                 ← Round 1: 纹理分组（模式B用）
│   ├── height_grid.npy                     ← Round 1: 语义高度（方案A）或读取高度（方案B）
│   ├── height_grid_preview.png             ← Round 1: 高度层级可视化
│   ├── terrain_grid.csv                    ← ⭐ Round 1 final: 含三类水+斜坡+地面高度
│   ├── texture_grid.csv                    ← ⭐ Round 1 final: 纹理 ID（模式C多种纹理）
│   ├── terrain_preview_height.png          ← 高度色预览（深蓝=深水,青=浅水,绿=h=0,棕=h=4,白=h=6）
│   ├── terrain_preview_texture.png         ← 纹理色预览
│   ├── water_map.txt                       ← Round 2: 水域字符地图（W=水/.=陆，桥梁识别用）
│   ├── continent_subregions.json           ← Round 2: 大陆子区域分析
│   ├── decoration_input.json               ← Round 2: AI 装饰物标注
│   └── decoration_entities.json            ← Round 2 final
├── templates/
│   ├── round1_water_continent_prompt.md    ← Round 1 AI prompt
│   └── round2_decoration_prompt.md         ← Round 2 AI prompt
├── styles/
│   └── dark_fantasy/                       ← 暗黑奇幻风格（Stage -1 选定后加载）
│       ├── rules.json                      ← 风格规则：cv_hints/terrain_image_prompt/decoration_image_prompt_template/element_rules
│       ├── model_catalog.json              ← 该风格专属模型目录
│       └── decoration_logic.py            ← 程序化布局逻辑（封边/水边植被/危险区）
├── scripts/
│   ├── check_cv_deps.py                    ← CV 依赖检测（必须首先运行）
│   ├── cv_stitch_blocks.py                 ← ⭐ Round 3: 灰度图切分 + 16块装饰图拼合
│   ├── cv_cluster.py                       ← ⭐ Round 1: 色相 K-means 聚类，推荐 K=20
│   ├── cv_cluster_analysis.py              ← ⭐ Round 1: 双重聚类交叉分析（K=50细聚类）
│   ├── cv_downsample.py                    ← ⭐ Round 1: 下采样→labels_grid.npy + cluster_grid.csv
│   ├── cv_continent_split.py               ← ⭐ Round 1: 大陆连通分割 + water_mask
│   ├── cv_water_classify.py                ← ⭐ Round 1: 三类水体分类→water_type_grid.npy（必须运行）
│   ├── water_postprocess.py                ← Round 1: 填回孤立水域（有内陆水体时跳过）
│   ├── gen_round1_csv.py                   ← ⭐ Round 1: 生成 terrain + texture CSV
│   ├── cv_terrain_preview.py               ← ⭐ 地形预览图生成
│   ├── cv_height_reader.py                 ← 方案B: 高度图读取（可选）
│   ├── cv_height_smooth.py                 ← 方案B可选: 高度网格平滑
│   ├── cv_delighting.py                    ← 可选: 去光影（需高度图）
│   ├── cv_height_boundary.py               ← 可选: 高度边界分析（斜坡规划前置）
│   ├── cv_slope_auto.py                    ← 可选: 自动斜坡规划
│   ├── cv_postprocess_plan.py              ← ⭐ Round 2: 游戏节点+道路规划
│   ├── cv_vegetation_fill.py               ← ⭐ Round 2: 植被填充
│   ├── cv_subregion_analysis.py            ← Round 2: 大陆子区域分析
│   ├── decoration_postprocess.py           ← ⭐ Round 2: 装饰物实体后处理
│   ├── gen_water_map.py                    ← ⭐ Round 2: 水域字符地图（桥梁识别）
│   ├── mcp_batch_writer.py                 ← ⭐ Stage 5: 批量 MCP 写入
│   ├── mcp_entity_writer.py                ← ⭐ Stage 5: 实体批量写入
│   ├── mcp_utils.py                        ← MCP 工具函数
│   ├── gen_round4_csv.py                   ← 已废弃（legacy）
│   └── read_map_size.py                    ← 已废弃（legacy，禁止在流程中使用）
└── references/
    ├── terrain-mcp-api.md                  ← MCP 接口速查
    ├── terrain-adjacency-rules.md          ← Y3 地形邻格约束规则（水体联带修改/斜坡规则）
    ├── y3-terrain-basics.md                ← Y3 引擎地形常识（三类水体/高度/斜坡/坐标系）
    ├── texture-ids.md                      ← 170 种纹理映射表
    ├── texture-color-map.md                ← 纹理颜色映射表
    ├── decoration_catalog.json             ← 装饰物模型目录
    └── decoration-model-ids.md             ← 装饰物/植被 ID 映射表
```

---

## MCP 接口速查

完整清单见 `references/terrain-mcp-api.md`。

| MCP Tool | 用途 | 使用阶段 |
|----------|------|----------|
| `get_map_info` | 探活 + 地图尺寸 | Stage 0 |
| `terrain_set_deep_water_block` | 深水（挖2层，不可通行） | Stage 5 Pass 3 |
| `terrain_set_shallow_water_block` | 浅水（挖1层，可通行，有悬崖边） | Stage 5 Pass 3 |
| `terrain_set_plain_water_block` | 平面水（不挖，铺在地面） | Stage 5 Pass 3 |
| `terrain_set_height_block` | 地形高度 | Stage 5 Pass 2 |
| `terrain_cover_draw_block` | 纹理 | Stage 5 Pass 5 |
| `terrain_vegetation_draw_block` | 植被 | Stage 5.3 |
| `entity_create_block` | 装饰物（桥梁/树木/节点） | Stage 5.3 |
| `ensure_terrain_textures` | 纹理面板管理 | Step 1.4c |
| `terrain_set_crack_block` | 裂缝（cliff，地形空洞） | Stage 5 Pass 1 |

---

## 注意事项

- **图片与地图 1:1 对应**：图片边界 = 地图边界，图片左上角 = 格点 (0,0)
- **大地图耗时**：128×128 约 170 次/Pass，CV 分割约 5-10 秒
- **MCP 调用中断恢复**：CSV 已持久化，中断后可从 CSV 重新开始写入
- **植被坐标系**：与地形坐标系不同，`terrain_vegetation_draw_block` 内部已处理
- **CV 依赖**：需要 `opencv-python` + `numpy`，约 45MB，通过 pip 安装
- **每轮交互**：两轮共约 3~4 次 AI-用户交互

## Round 3：装饰写入（必选，Stage 5 之后执行）

> **前置条件（必须全部满足）：**
> - Stage -1 已完成：16 张装饰图（`decoration_block_{row}_{col}.png`）已由用户确认，目录路径记录为 `<decoration_dir>`
> - Stage 5 已完成（地形已写入编辑器）
> - `height_grid.npy` / `water_mask_grid.npy` / `water_type_grid.npy`（Round 1 产出）
> - `spatial_analysis.json`（Round 2 Step 2.3 产出，包含节点坐标 + 桥梁候选）
>
> **当前风格**：`<style_id>`（来自 Stage -1）

### Step 3.1：验证并拼合 16 块（自动）

```bash
python scripts/cv_stitch_blocks.py stitch \
  --input-dir <decoration_dir> \
  --output <dir>/decoration_design.png \
  --grid-size 4 \
  --block-size 1024 \
  --output-size 2048
```

脚本自动：
- 验证 16 张图都存在且为 1024×1024 px，任意缺失则打印列表并以退出码 1 终止
- 按 4×4 顺序拼合为 4096×4096 px
- 缩放到 2048×2048 输出（使用最近邻插值，保护精确 RGB 颜色）

⛔ 任意块缺失或尺寸错误时，**禁止继续后续步骤**，提示用户返回 Stage -1.3 补充对应块后重跑。

### Step 3.2：强制叠加游戏节点位置

```python
import json, pathlib
from PIL import Image
from scripts.gen_gray_context import overlay_candidates

run = pathlib.Path('output/{run_id}')
spatial = json.loads((run / 'spatial_analysis.json').read_text(encoding='utf-8'))
img = Image.open(str(run / 'decoration_design.png'))

CANDIDATE_COLORS = {
    'resource_points':   (255, 210,   0),
    'monster_lairs':     (150,   0, 200),
    'dungeon_entrances': ( 70,   0, 150),
    'bridge_candidates': (  0,  60, 220),
}
for key, color in CANDIDATE_COLORS.items():
    overlay_candidates(img, spatial.get(key, []), color, dot_radius=1)

img.save(str(run / 'decoration_design.png'))
print("Game node positions enforced")
```

### Step 3.3：CV 元素提取（整体提取，基于已拼合的完整图）

```bash
python scripts/cv_decoration_extract.py output/{run_id} \
  --theme {theme} \
  --style <style_id>
```

> ⚠️ **`--style <style_id>` 必须传入**，否则风格 `element_rules`（高度限制、密度规则）和程序化布局（封边密林、水边植被、危险区围林）不会生效。

可用主题（`--theme`）：`grassland`、`autumn`、`desert`、`ice_snow`、`default`

输出：`output/{run_id}/decoration_manifest.json`

检查警告日志：
- `unknown_pixels.log` — 未识别颜色（距离 > 90），说明某块颜色偏差过大，需重新生成对应块
- `shape_warnings.log` — 尺寸不足被跳过的元素
- `height_warnings.log` — 因高度不符合风格规则被跳过的元素

### Step 3.4：查看并修改元素清单

读取 `decoration_manifest.json`，按需修改元素：

```python
import json
m = json.load(open('output/{run_id}/decoration_manifest.json', encoding='utf-8'))
print(m['summary'])
for e in m['elements']:
    print(e['id'], e['type'], e['grid_pos'])
```

修改元素（直接编辑 JSON）：
- `model_group`：改用其他主题模型池
- `model_ids`：指定具体模型 ID 列表
- `density`：sparse / medium / dense（仅 area 类型）
- `radius`：调整覆盖范围（仅 area 类型）
- `status`：改为 `skipped` 跳过写入

### Step 3.5：MCP 批量写入

```bash
python scripts/mcp_round3_writer.py output/{run_id}/decoration_manifest.json [--dry-run]
```

- `--dry-run`：只统计，不实际写入
- `--batch-size N`：覆盖默认分级批次（road=100, 游戏节点=20, 其他=50）
- `--url URL`：MCP Server 地址（默认从 mcp_settings.json 读取）

输出：更新后的 `decoration_manifest.json`（status 字段变为 written/failed）

### 注意事项

- Round 2 的 `cv_vegetation_fill.py` 在 Round 3 流程中**不再调用**
- 游戏节点（resource_point、monster_lair、dungeon_entrance）当前以 `entity_create_block` + 占位模型写入；正式上线前需与策划确认物编实体 ID
- 若某块 `unknown_pixels.log` 报错超过 5%，说明该块颜色偏差过大，需重新生成对应块后从 Step 3.4 重跑
- 已验证端到端流程（20×20格合成地图，22个单元测试全部通过）