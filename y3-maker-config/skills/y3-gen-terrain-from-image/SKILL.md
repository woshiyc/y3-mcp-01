---
name: y3-gen-terrain-from-image
description: 从 2D 平面地图图片生成 Y3 编辑器地形。当用户上传一张或多张地图图片（手绘草图、规划图、战略地图等）并希望在 Y3 编辑器中还原这张地图的地形时使用。触发词：从图片生成地形、图片转地形、上传地图图片生成地形、根据图片刷地形、图片生成地图。
---

# Y3 地形图片生成（y3-gen-terrain-from-image）

用户提供**地形图**（高度图可选），通过 **前置处理 → CV聚类 → AI语义标注 → 生成 CSV → MCP 写入** 流程，还原为 Y3 编辑器中的真实地形。

## 🔄 整体架构总览

```
地形图 ──┬── Stage 0: 前置处理
高度图 ──┤（可选）
（可选）  │
         ├── Round 1: 水域 + 大陆分割 + 纹理 + 高度
         │     ├─ cv_cluster.py (K≥20) → 粗聚类
         │     ├─ cv_cluster_analysis.py (K=50) → 增强分析
         │     ├─ cv_downsample.py → 网格分辨率标签
         │     ├─ AI 标注水域 + 三类水体分类
         │     ├─ cv_continent_split.py → 大陆分割
         │     ├─ cv_water_classify.py → 生成 water_type_grid.npy
         │     ├─ [方案A] AI 语义高度分配（推荐，无需高度图）
         │     │     └─ 直接按簇语义→ height_grid.npy
         │     ├─ [方案B] cv_height_reader.py（需提供高度图）
         │     │     ├─ cv_height_smooth.py（可选，消除碎片）
         │     │     └─ cv_height_boundary.py + cv_slope_auto.py
         │     ├─ [可选] cv_delighting.py → albedo.png（需高度图）
         │     ├─ AI 分配纹理（模式C：按聚类 / 模式B：按大陆组）
         │     └─ gen_round1_csv.py → terrain_grid.csv + texture_grid.csv
         │
         └── Round 2: 装饰物 + 游戏节点 + 道路 + 植被
               ├─ cv_subregion_analysis.py → 大陆子区域分析
               ├─ AI 逐大陆标注
               ├─ decoration_postprocess.py → decoration_entities.json
               ├─ cv_postprocess_plan.py → 游戏节点 + 道路规划
               └─ cv_vegetation_fill.py → 植被填充

最终 → mcp_batch_writer.py → Y3 编辑器
```

### CSV 产出表

| 文件 | Round 1 (final) | Round 2 (final) |
|------|----------------|-----------------|
| terrain_grid.csv | 深水/浅水/平面水 + 斜坡(slope,h) + 陆地(ground,h) | 不变 |
| texture_grid.csv | 大陆纹理（按聚类ID精细分配） | 不变 |
| decoration_grid.csv | 不存在 | 桥梁+树木 |

### Mask / Grid 体系

| 文件 | 分辨率 | 类型 | 产出步骤 |
|------|--------|------|----------|
| height_grid.npy | 网格 | int32 | 方案A语义分配 或 方案B Step 0.5 |
| height_full.npy | 原图 | int32 | 方案B Step 0.5（可选） |
| albedo.png | 原图 | 图片 | Step 0.6（可选，需高度图） |
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
| 4 | **高度优先语义分配** | 推荐方案A：AI 按色彩语义（草地→h=0，丘陵→h=2，山地/火山→h=4，雪山→h=6）直接分配；方案B（高度图灰度法）只在同一色相区域内有效，跨色相比较明度无意义（见 y3-terrain-basics.md） |
| 5 | **albedo 替代原图** | Step 0.6 de-lighting 后，所有 CV 步骤使用 albedo.png；无高度图时跳过，直接用原图 |
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
| 6 | ⛔ **禁止跳过用户确认直接生成** | 每轮的 AI 语义分配都需用户确认 |
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

### 0.3 接收图片 + 确认高度方案

> "请提供以下信息：
>
> **图片路径（必须）：**
> 1. **地形图**（terrain_map）：彩色地图，图片边界与地图边界 1:1 对应
>
> **可选输入：**
> 2. **高度图**（height_map）：灰度深度图，与地形图空间对齐（若不提供，使用方案A语义高度）
> 3. **首都/出生区位置**：如 `center`（默认）、`32,48`（具体格坐标）等
> 4. **节点数量偏好**：如 `resource=5,lair=8,dungeon=2,ruin=6`"

**处理逻辑**：

| 情况 | 高度方案 | AI 行为 |
|------|---------|---------|
| 提供高度图 | **方案B** | 跑 cv_height_reader.py，注意灰度法只在同色相内有效 |
| 无高度图 | **方案A（推荐）** | Step 1.4b 完成聚类后，AI 按色彩语义直接分配 height_grid |
| 高度图效果异常（暗色高地被误判为低地） | **切换方案A** | 放弃高度图，改用语义分配 |

记录：`<terrain_path>`、`<height_path>`（可选，方案B用）、`<height_method>`（A或B）、`<capital>`（默认 `center`）、`<node_counts>`（默认空）。

### 0.4 创建工作输出目录

所有轮次的中间文件和最终 CSV **统一输出到** `<skill_dir>/output/` 目录：

```
<dir> = .codemaker/skills/y3-gen-terrain-from-image/output/
```

后续所有脚本的 `--output-dir` 参数统一使用此路径。

> ⚠️ AI **禁止**自行选择其他工作目录（如 `terrain_gen_work/`），必须使用 `<skill_dir>/output/`。

### 0.5【方案B】高度图读取（可选，仅当用户提供高度图时执行）

> ⚠️ **方案B局限性**：灰度法假设"亮=高、暗=低"，但此假设**只在同一色相区域内有效**。
> 深棕色火山（暗）在灰度图里可能与深水一样黑，导致火山被误判为低地。
> 若发现此类问题，应切换到**方案A（语义高度）**。

灰度范围与阈值说明：先检查高度图实际灰度范围，再按四等分设置阈值：

```bash
python scripts/cv_height_reader.py <height_path> \
  --output-dir <dir> \
  --grid-size <W>x<H> \
  --thresholds <t1>,<t2>,<t3> \
  --height-values 0,2,4,6
```

> `<t1>,<t2>,<t3>` 按灰度范围 [min,max] 四等分计算。  
> 例：灰度范围 [8,123]，四等分阈值约为 36,65,94。  
> **禁止直接使用默认阈值 64,128,192**，必须先 `python -c "import cv2,numpy as np; img=cv2.imread('<path>',0); print(img.min(),img.max())"` 确认范围。

输出：`height_full.npy`、`height_grid.npy`、`height_grid_preview.png`

查看预览图，若 h=4/h=6 分布为 0（阈值设置导致高地消失），必须重新计算阈值。

### 0.5b【方案B可选】高度网格平滑

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

> 仅当同时有地形图和高度图时才能运行。无高度图则跳过，后续 CV 步骤直接使用原图。

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

> **输入图片**：优先使用 Step 0.6 输出的 `albedo.png`；无高度图时直接使用 `<terrain_path>` 原图。

**K 值选择**：

| 地图类型 | 推荐 K | 原因 |
|---------|--------|------|
| 简单地图（色彩区域清晰，颜色差异大） | K=15 | 簇数少，语义清晰 |
| 复杂地图（暗黑奇幻等，含相近暗色区域） | **K=20** | 分离相近暗色（如火山深棕 vs 腐化深紫 vs 深水，K=15 时会混入同一簇） |
| 颜色极复杂 | K=25 | 酌情提高 |

> ⚠️ 若某些语义区域颜色相近（如火山深棕与腐化深紫 rgb 差距 <20），K=15 会将其归入同一簇导致无法独立分配纹理/高度，必须提高 K 值。

```bash
# 无 albedo（无高度图，推荐）
python scripts/cv_cluster.py <terrain_path> \
  --k 20 \
  --hsv-weights 2.0,1.0,0.8 \
  --output-dir <dir>

# 有 albedo（有高度图）
python scripts/cv_cluster.py <dir>/albedo.png \
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

在粗聚类(K=15)基础上，新增细聚类(K=50)并做交叉分析，为每个粗簇补充内部纹理复杂度、颜色统计、空间形态等多维特征，帮助 AI 精确区分水域与深色陆地。

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

---

**【方案A】语义高度分配（无高度图时必须执行）**

> 方案A的核心原则：按色彩**语义**（地物类型）分配高度，而非按亮度。

**高度分配规则（对照 Y3 地形设定）**：

| 语义 | 典型颜色/簇 | Y3 高度 | 说明 |
|------|-----------|---------|------|
| 深水/浅水/平面水 | 蓝色水域簇 | —（由water_mask控制）| 水域不分配陆地高度 |
| 平原草地、低洼沼泽 | 绿色系簇 | **h=0** | Y3默认基础高度 |
| 丘陵、山脚过渡带 | 棕褐色系簇 | **h=2** | 1层悬崖高度 |
| 山地、火山体、冰地 | 深黑褐/灰色系簇 | **h=4** | 2层悬崖，注意深棕火山≠低地 |
| 雪山峰顶 | 白/极浅灰簇 | **h=6** | 3层悬崖，最高地标 |

> ⚠️ **关键陷阱**：深棕色火山（rgb≈60,50,45）与深水颜色亮度相近，但火山是 h=4 高地，不能因为颜色暗就分配 h=0。Y3地形规则：明度只在同一色相区域内表示高低，跨色相无效。

为每个陆地簇生成 `height_grid.npy`：

```python
CLUSTER_HEIGHT = {
  # 草地/低地 → h=0
  2: 0, 7: 0, 14: 0, 12: 0, 15: 0,
  # 丘陵 → h=2
  9: 2, 1: 2, 18: 2,
  # 山地/火山/冰地 → h=4
  11: 4, 13: 4, 3: 4,
  # 雪峰 → h=6
  10: 6, 8: 6, 19: 6,
}
# 对每格：if water_mask[z,x]: h=0 else: h=CLUSTER_HEIGHT[labels_grid[z,x]]
```

生成 `height_grid.npy` 后查看 `height_grid_preview.png` 确认分布（h=4/h=6 区域应与原图山峰位置一致）。

展示分配结果后**无需询问用户确认，直接继续**。

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

### Step 1.5b【可选，仅方案B】高度边界分析

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
> **无高度图时**：省略 `--height-grid`，改用 `--group-height-config '{"1":0,"2":2,"3":4}'`。
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

### Step 2.3：MCP 写入 — 装饰物 + 游戏节点 + 道路

将规划中的装饰物（树木/山石）和游戏节点（资源/巢穴/地牢/遗迹）写入 Y3：

**先处理桥梁**（来自 Step 2.0 的 bridges.json）：

将桥梁合并到 `decoration_input.json`，然后：

```bash
python scripts/decoration_postprocess.py \
  <dir>/decoration_input.json \
  <dir>/water_mask_grid.npy \
  <dir>/decoration_entities.json \
  --texture-grid <dir>/texture_grid.csv
```

**再处理游戏节点**（资源点/巢穴/地牢/遗迹 — 来自 postprocess_plan.json）：

AI 读 `postprocess_plan.json` 中的 `nodes` 数组，为每类节点选择合适的模型 ID（参考 `references/decoration_catalog.json`），生成 entity 列表，调用 `mcp_entity_writer.py` 写入。

**道路**：

道路在 Y3 中通过地面纹理覆盖 + 道路摆件实现。AI 读 `road_grid.npy` 中标记为 `True` 的格子，调用 `terrain_draw_texture_block` 覆盖道路纹理，再放置道路摆件实体。

---

### Step 2.4：植被填充（自动，纯规则）

```bash
python scripts/cv_vegetation_fill.py \
  --texture-grid <dir>/texture_grid.csv \
  --water-mask   <dir>/water_mask_grid.npy \
  --map-info     <dir>/map_info.json \
  --output-dir   <dir>
```

脚本按纹理类型自动铺设植被（无需 AI）：

| 纹理组 | 植被效果 |
|--------|---------|
| 草地系 | 草丛（密度 0.6~0.7） |
| 秋色系 | 枯草/落叶草（密度 0.4） |
| 沙漠系 | 稀疏荒草（密度 0.15） |
| 岩石/冰雪系 | 无植被 |
| 沼泽系 | 芦苇（密度 0.5） |
| 水域边缘格 | 水草（密度 0.3） |

> ⛔ **禁止 AI 自行编写植被生成逻辑**，必须调用 `scripts/cv_vegetation_fill.py`

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
   - status == "all_done" → 退出循环，进入 5.3 装饰物写入
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

### 5.3 装饰物写入（AI 调用 MCP）— ⛔ 必须执行，禁止跳过

> **⛔ 装饰物写入是 Stage 5 的必要组成部分，不是可选步骤。**
> 当 `decoration_entities.json` 存在且非空时，AI **必须**在地形+纹理写入完成（`all_done`）后立即执行装饰物写入。
> 禁止输出"JSON 已生成，可后续写入"然后停止。

**执行流程（AI 严格按此执行）：**

直接调用 `mcp_entity_writer.py` 脚本，它会自动读取 JSON、下载模型、分批调用 MCP：

```bash
python scripts/mcp_entity_writer.py <dir>/decoration_entities.json --download-models
```

脚本自动完成：
- 读取 `decoration_entities.json`（由 `decoration_postprocess.py` 生成的 entity list）
- 收集所有 `model_id`，自动调用 `download_editor_model_resource` 下载模型资源
- 分批调用 `entity_create_block`（默认每批 50 个，间隔 1 秒）
- 输出统计和 `ENTITY_RESULT` JSON

> ⚠️ **禁止 AI 手动复制 JSON 到 use_mcp_tool 参数**。必须使用脚本。
> ⚠️ 如需调整批次大小：`--batch-size 30`；调整延迟：`--delay 2.0`
> ⚠️ 先 dry-run 确认：`--dry-run`（只读取统计，不实际写入）

**entity 字段说明：**
```json
{
  "type": 16777216,
  "pos": [world_x, 0, world_z],
  "model_id": 201669,
  "yaw": 90,
  "pitch": 0,
  "roll": 0,
  "scale": [2.5, 2.5, 2.5],
  "stick_to_ground": true
}
```

> ⚠️ **type 必须是 `16777216`**（2^24 = RESOURCE_MODEL），不是 16！
> ⚠️ **旋转使用 yaw/pitch/roll 独立字段**，不是 rotation 数组！
> ⚠️ **不要自己生成 entity JSON**，必须使用 `decoration_postprocess.py` 脚本的输出！

**植被类装饰物** → 使用 `terrain_vegetation_draw_block`（⚠️ 植被坐标系与地形格点不同）

### 5.4 输出完成摘要

```
✅ 地形写入完成（Stage 5）
  - 总格子数：16384
  - ground: 8200 格 | deep_water: 3100 格 | slope: 420 格
  - 纹理覆盖：12000 格

✅ 后处理写入完成（Round 2）
  - 桥梁：2 个
  - 树木：180 个 | 山石：45 个
  - 游戏节点：资源点 5 | 巢穴 6 | 地牢 2 | 遗迹 8
  - 道路：384 格
  - 植被：2300 格
```

### 5.5 生成地形预览图（可选，不需要 MCP）

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
├── scripts/
│   ├── check_cv_deps.py                    ← CV 依赖检测（必须首先运行）
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