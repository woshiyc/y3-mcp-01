# Round 3 装饰实体层设计规范

**日期：** 2026-06-04  
**项目：** y3-gen-terrain-from-image  
**范围：** 在现有 Round 1/2 流水线基础上新增 Round 3，实现完整装饰实体层生成

---

## 1. 背景与问题

当前流水线（Round 1 + Round 2）存在的主要缺陷：

- 纹理单一，缺乏视觉层次感
- Round 2 植被使用简单规则（h=0放树、h≥4放石头），分布机械
- 无建筑/构筑物（城堡、神庙、哨楼等）
- 无道路视觉外观（仅算法路径，无模型）
- 游戏节点（资源点、巢穴、地牢）写入分散在 Round 2，难以统一管理
- 无元素修改机制，生成后不易调整

---

## 2. 设计目标

1. 新增 Round 3，统一负责所有装饰实体写入
2. 通过 GPT Image 2 生成装饰设计图，实现 AI 驱动的空间布局
3. 建立标准颜色语义协议，打通 AI 生成 → CV 提取 → MCP 写入全链路
4. 提供元素清单 + 修改模式，支持用户按位置选择元素并替换模型/物编类型
5. 全流程可中断恢复

---

## 3. 整体架构

### 3.1 流水线职责划分

```
Round 1: 地形基础层
  输入:  terrain_image.png (+ height_map.png)
  输出:  terrain_grid.csv, texture_grid.csv
  职责:  CV聚类 → 水域分类 → 大陆分割 → 高度/纹理赋值

Round 2: 空间分析层【纯分析，不写入实体】
  输入:  Round 1 输出
  输出:  spatial_analysis.json
  职责:  水域/大陆分布分析、高度热力图、桥梁候选位置、
         游戏节点候选位置、道路骨架路径
  变更:  vegetation_fill 规则禁用（由 Round 3 接管）
         游戏节点不再在此写入（移至 Round 3）

Round 3: 装饰实体层【全部实体写入】
  输入:  Round 1/2 输出 + 用户确认
  输出:  decoration_manifest.json + Y3编辑器实体
  职责:  灰度图生成 → AI装饰设计 → CV提取 → 用户修改 → MCP写入

Stage 5: 地形批量写入（原有，不变）
  输入:  terrain_grid.csv, texture_grid.csv
  职责:  批量写入地形高度和纹理
```

### 3.2 Round 2 输出格式（新增字段）

`spatial_analysis.json` 新增以下节点候选数据：

```json
{
  "bridge_candidates": [
    {"x": 60, "z": 50, "water_type": "shallow_water", "width": 3}
  ],
  "resource_points": [
    {"x": 80, "z": 40, "terrain_type": "ground", "priority": "high"}
  ],
  "monster_lairs": [
    {"x": 240, "z": 200, "distance_from_center": 85}
  ],
  "dungeon_entrances": [
    {"x": 160, "z": 160, "height": 4}
  ],
  "road_skeleton": {
    "nodes": [{"x": 50, "z": 30}, {"x": 160, "z": 160}],
    "edges": [[0, 1]]
  }
}
```

---

## 4. 颜色语义协议（Color Semantic Protocol v1.0）

Round 3 的核心约定。AI 生成装饰设计图时严格遵守，CV 提取时做反向映射。

### 4.1 颜色表

背景灰色由 Section 4.2 的过滤函数预先剔除，不参与后续颜色匹配。匹配池共 **11 种**装饰颜色。

形状规范是 CV 提取正确运行的前提：面状元素需要足够密集的色块让 DBSCAN 成功聚类；道路需要细线让骨架化产生有效路径；点状元素对形状不敏感但需要最小尺寸保证连通域被检测到。

| 类型 | 颜色名 | RGB | 形状类型 | 绘制形状要求 | 最小尺寸 |
|------|--------|-----|---------|------------|---------|
| **背景（无装饰）** | 灰色 | R≈G≈B（由4.2过滤） | — | — | — |
| forest_sparse（稀疏草木） | 黄绿 | (100, 210, 50) | area | 填满的实心不规则色块 | 6×6 格 |
| forest_medium（中密度森林） | 草绿 | (20, 160, 20) | area | 填满的实心不规则色块 | 8×8 格 |
| forest_dense（高密度密林） | 深绿 | (0, 90, 0) | area | 填满的实心不规则色块 | 10×10 格 |
| rock_cluster（山石群） | 青色 | (0, 200, 200) | area | 填满的实心不规则色块 | 4×4 格 |
| building_common（普通建筑） | 金橙 | (220, 160, 20) | point | 实心小方块 | 3×3 格 |
| building_landmark（特殊地标） | 洋红 | (200, 20, 120) | point | 实心小方块 | 3×3 格 |
| resource_point（资源采集点） | 纯金 | (255, 210, 0) | point | 实心小方块 | 3×3 格 |
| monster_lair（怪物巢穴） | 紫色 | (150, 0, 200) | point | 实心小方块 | 3×3 格 |
| dungeon_entrance（地牢入口） | 深紫 | (70, 0, 150) | point | 实心小方块 | 3×3 格 |
| road_main（主干道路） | 亮红 | (220, 50, 20) | path | 细线条，连续笔画 | 宽 2-3 格，长 ≥ 10 格 |
| bridge（桥梁） | 亮蓝 | (0, 60, 220) | point | 实心小方块 | 3×3 格 |

### 4.2 灰色过滤规则

```python
def is_gray(r, g, b, threshold=25):
    return max(abs(r-g), abs(g-b), abs(r-b)) < threshold
```

### 4.3 颜色识别规则

1. 先执行 Section 4.2 灰色过滤，过滤后的像素不再参与匹配
2. 每个非灰色像素计算与协议表 **11 种**装饰颜色的 RGB 欧氏距离
3. 归入距离最小的颜色对应的元素类型
4. 最近距离 > 60 的像素标记为未知色，写入 `unknown_pixels.log`

---

## 5. Step 3.1：灰度上下文图生成

**脚本：** `scripts/gen_gray_context.py`  
**输入：** `height_grid.npy`, `water_mask_grid.npy`, `water_type_grid.npy`, `spatial_analysis.json`  
**输出：** `output/{run_id}/gray_context.png`  
**分辨率：** 与游戏格子等比（1像素=1格，如 320×320）

### 5.1 亮度编码

```
deep_water    → 灰度值 20   (极暗)
shallow_water → 灰度值 60   (深暗)
plain_water   → 灰度值 80   (暗)
ground h=0    → 灰度值 120  (中灰)
ground h=2    → 灰度值 155  (浅灰)
ground h=4    → 灰度值 190  (亮灰)
ground h=6    → 灰度值 230  (近白)
```

### 5.2 候选位置标记叠加

在灰度图上叠加 `spatial_analysis.json` 中的候选位置，使用对应的颜色语义协议颜色绘制小圆点（半径2像素），让 AI 在绘制装饰时感知预留位置。

---

## 6. Step 3.2：AI 装饰设计图生成

**模型：** GPT Image 2（**image editing / inpainting 模式**，以 `gray_context.png` 为底图输入）  
**输入：** `gray_context.png` + `spatial_analysis.json` + 地图描述  
**输出：** `output/{run_id}/decoration_design.png`

**游戏节点位置强制保证：** GPT Image 2 inpainting 可能不完全遵守提示词中的坐标约束。Step 3.2 完成后，在进入 Step 3.3 之前，程序强制将 `spatial_analysis.json` 中的候选位置用对应协议颜色重绘（3×3像素色块）覆盖到 `decoration_design.png` 上，确保游戏节点位置在 CV 提取时一定存在。

### 6.1 Prompt 模板

```
【系统角色】
你是一位游戏关卡设计师，正在为一张俯视角RTS/RPG地图绘制装饰布局图。

【输入图说明】
输入图为灰度高度图：极暗=深水，暗=浅水，中灰=低地，浅灰=丘陵，近白=山峰。
图中彩色小圆点为预定游戏节点位置，请在这些位置使用对应颜色覆盖。

【任务】
在灰度图上，用下方颜色表中的纯色（无渐变、无混色）绘制装饰元素分布。

【颜色表】
[完整颜色语义协议表，见第4节]

【空间约束（由 spatial_analysis.json 注入）】
注：以下坐标为 gray_context.png 的像素坐标（1像素=1格，与grid_pos直接对应）
- 资源点(255,210,0) 放置在像素位置：{resource_positions_px}
- 巢穴(150,0,200) 放置在像素位置：{lair_positions_px}
- 地牢(70,0,150) 放置在像素位置：{dungeon_positions_px}
- 桥梁(0,60,220) 覆盖水域候选像素位置：{bridge_positions_px}
- 其余装饰按地形逻辑自由布局

【布局规则】
- 森林/植被只在灰度值 100-200 的区域（非水域、非山峰）
- 山石只在灰度值 160-230 的区域（高地/山腰）
- 建筑优先放置在平坦区域，远离水边
- 道路连接主要建筑/节点，沿平缓地形走

【形状规范（必须严格遵守，影响后续识别）】
面状元素（森林、山石）：
- 画成填满的实心色块，内部不留空洞，不画散点
- forest_sparse 单块最小 6×6 格，forest_medium 最小 8×8 格，forest_dense 最小 10×10 格
- rock_cluster 最小 4×4 格
- 多个同类色块之间间距 ≥ 5 格（让CV识别为独立群组）

点状元素（建筑、游戏节点、桥梁）：
- 画成 3×3 格的实心小方块
- 不同点状元素之间间距 ≥ 4 格

线状元素（道路）：
- 画成连续细线，宽度 2-3 格，不能画成粗色带
- 最短长度 ≥ 10 格，必须连续不断开
- 路口交叉处允许局部加粗（最多 4×4 格）

禁止：渐变色、半透明、混合颜色、散点、空心轮廓线
```

---

## 7. Step 3.3：CV 元素提取

**脚本：** `scripts/cv_decoration_extract.py`  
**输入：** `decoration_design.png`, `texture_grid.csv`  
**输出：** `output/{run_id}/decoration_manifest.json`

### 7.1 提取流程

```
[0] 图像预处理（所有像素操作之前必须执行）
    → 将 decoration_design.png 缩放至精确的 grid_size.w × grid_size.h 像素
    → 使用最近邻插值（cv2.INTER_NEAREST），避免颜色混合导致识别错误
    → 此步骤保证后续所有像素坐标与游戏格坐标1:1对应
    → 保证 DBSCAN 参数 eps=4 的含义为"4个游戏格"

[1] 灰色过滤
    → 跳过灰色背景像素

[2] 颜色分类
    → 每个装饰像素归入最近协议颜色（11种）
    → 距离 > 60 写入 unknown_pixels.log

[3] 空间聚类（按形状类型，参数基于1像素=1格）
    面状元素（forest_*, rock_cluster）
    └── DBSCAN(eps=4, min_samples=6)
        → 每个 cluster 像素数 < 16 → 写入 shape_warnings.log，跳过（不写入manifest）
        → 每个 cluster 像素数 ≥ 16 → 输出：中心格坐标 + 半径

    点状元素（building_*, resource_point, monster_lair, dungeon_entrance, bridge）
    └── 连通域分析
        → 每个连通域像素数 < 4 → 写入 shape_warnings.log，跳过
        → 每个连通域像素数 ≥ 4 → 输出：质心格坐标

    线状元素（road_main）
    └── 骨架化(skeletonize) → 路径采样
        → 骨架总像素数 < 10 → 写入 shape_warnings.log，跳过
        → 骨架总像素数 ≥ 10 → 输出：有序 waypoints 列表

    ⚠️ 若 shape_warnings.log 非空，Step 3.4 清单展示前输出警告摘要：
       "发现 N 个元素因尺寸不足被跳过，详见 shape_warnings.log"

[4] 模型分配
    → 元素类型 + 所在格的 texture_id
    → 查 references/decoration_model_catalog.json
    → 分配默认 model_group + model_ids
```

### 7.2 decoration_manifest.json 格式

```json
{
  "meta": {
    "map_id": "string",
    "run_id": "string",
    "generated_at": "ISO8601",
    "grid_size": {"w": 320, "h": 320},
    "total_elements": 287,
    "color_protocol_version": "1.0"
  },
  "elements": [
    {
      "id": "e_001",
      "type": "forest_medium",
      "shape": "area",
      "grid_pos": {"x": 45, "z": 32},
      "radius": 8,
      "density": "medium",
      "model_group": "grassland",
      "model_ids": [200009, 103050, 201627],
      "world_pos": {"x": -231.0, "y": 0.0, "z": 169.0},
      "source_color": [20, 160, 20],
      "status": "pending",
      "modified": false,
      "modify_history": []
    },
    {
      "id": "e_100",
      "type": "road_main",
      "shape": "path",
      "waypoints": [{"x": 50, "z": 30}, {"x": 75, "z": 60}],
      "width": 2,
      "model_ids": [205148],
      "source_color": [220, 50, 20],
      "status": "pending",
      "modified": false,
      "modify_history": []
    }
  ],
  "summary": {
    "forest_sparse": 0,
    "forest_medium": 0,
    "forest_dense": 0,
    "rock_cluster": 0,
    "building_common": 0,
    "building_landmark": 0,
    "resource_point": 0,
    "monster_lair": 0,
    "dungeon_entrance": 0,
    "road_main": 0,
    "bridge": 0
  }
}
```

**status 生命周期：**
```
pending → modified（用户修改后）
        → skipped（用户标记跳过）
        → written（MCP写入成功）
        → failed（写入失败，保留重试）
```

---

## 8. Step 3.4：元素清单与用户修改模式

### 8.1 清单展示

Skill 按类型分组输出清单，格式示例：

```
=== 装饰元素清单 === map: {map_id} | 共 {N} 个元素

【汇总】
  植被/森林   稀疏(12) 中密度(8) 高密度(5)
  山石        23 个群组
  建筑        普通(15) 地标(4)
  游戏节点    资源点(8) 巢穴(6) 地牢(3)
  交通        道路(4) 桥梁(7)

【森林/植被】
ID      | 类型          | 位置(x,z)  | 半径 | 密度   | 模型组
--------|--------------|-----------|------|--------|----------
e_001   | forest_medium | (45, 32)  |  8   | medium | grassland
...
```

### 8.2 支持的修改操作

**单个修改：**
```
e_001 改 model_group=jungle
e_042 改 model_ids=[200565, 200571]
e_003 改 density=sparse radius=6
e_200 skip
```

**批量修改：**
```
所有 forest_medium 改 model_group=autumn
x<160 AND type=building_common 改 model_ids=[103261]
北方区域(z<100) 的 rock_cluster 改 model_group=ice_snow
```

**位置模糊查询：**
```
(100, 80) 附近的元素有哪些
→ 输出: 半径10格内所有元素列表
```

### 8.3 修改确认

```
已修改 8 个元素：
  e_001 ~ e_008  forest_medium  model_group: grassland → autumn  ✓
  e_042          building_common model_ids 已更新              ✓

输入 [确认] 保存并进入写入阶段，或继续修改
```

---

## 9. Step 3.5：MCP 批量写入

### 9.1 写入顺序

```
① 道路      road_main      → entity_create_block（模型205148，沿waypoints铺设）
② 桥梁      bridge         → entity_create_block（manifest中指定模型）
③ 游戏节点  resource_point / monster_lair / dungeon_entrance
           → 【待确认】物编实体创建 MCP 工具名及参数结构
             实现前需确认：MCP方法名、实体ID格式、必填参数
             在接口确认前，此步骤以 entity_create_block + 占位模型暂代
④ 建筑/地标 building_*     → entity_create_block
⑤ 山石      rock_cluster   → entity_create_block × N（池内随机，散布半径内）
⑥ 森林/植被 forest_*       → entity_create_block × N（Poisson采样）
```

### 9.2 批次大小

| 元素类型 | MCP 调用 | 批次上限 |
|---------|---------|---------|
| road_main | entity_create_block | 100/批 |
| bridge | entity_create_block | 50/批 |
| 游戏节点 | 物编实体创建【待确认接口】 | 20/批 |
| building_* | entity_create_block | 50/批 |
| rock_cluster | entity_create_block | 50/批 |
| forest_* | entity_create_block | 50/批 |

### 9.3 面状元素位置展开

```python
density_factor = {"sparse": 0.15, "medium": 0.30, "dense": 0.50}
# N = π × radius² × density_factor
# 使用 Poisson Disk Sampling，最小间距 1.5 格
# 每个坐标从 model_ids 随机选取一个写入
```

### 9.4 中断恢复

恢复机制基于 `decoration_manifest.json` 中的 `status` 字段：
- `written` → 跳过
- `failed` → 重试
- `pending` / `modified` → 正常写入
- `skipped` → 跳过

`failed_entities.json` 是写入报告的人类可读摘要（包含失败元素的 id + 错误信息），不独立于 manifest 存储数据。重试时仍以 manifest 为数据源，`failed_entities.json` 仅用于快速定位问题。

### 9.5 写入完成报告

```
=== Round 3.5 写入完成 ===
总计: {N} 个元素
  ✓ 成功: {n}
  ✗ 失败: {n}  → 错误详情见 failed_entities.json，重试从 manifest 读取
  ○ 跳过: {n}
耗时: 约 {t} 分钟
```

---

## 10. 新增文件清单

### scripts/（新增）
```
gen_gray_context.py         Step 3.1 灰度图生成
cv_decoration_extract.py    Step 3.3 CV元素提取
mcp_entity_writer.py        Step 3.5 MCP实体批量写入（扩展现有）
```

### references/（新增）
```
decoration_model_catalog.json    元素类型 → 模型池映射（按地图主题）
color_protocol_v1.json           颜色语义协议机器可读版本
```

### output/{run_id}/（新增产物）
```
gray_context.png             Step 3.1 输出
decoration_design.png        Step 3.2 输出
decoration_manifest.json     Step 3.3 输出（用户修改后覆盖保存）
failed_entities.json         Step 3.5 失败实体（可重试）
unknown_pixels.log           CV未识别颜色警告（颜色距离 > 60）
shape_warnings.log           CV形状不足警告（元素因尺寸太小被跳过）
```

### SKILL.md（修改）
```
- 新增 Round 3 全流程说明
- 颜色语义协议表（完整版）
- Round 2 vegetation_fill 禁用说明
- 游戏节点移至 Round 3 说明
```

---

## 11. 约束与边界

- Round 3 依赖 Round 1/2 已完成（需要 terrain_grid.csv、spatial_analysis.json）
- GPT Image 2 API 调用需要网络连接，生成时间约 30-60 秒
- 装饰图分辨率上限由 GPT Image 2 支持的最大尺寸决定；超大地图（>512×512格）需分块生成后拼合
- `entity_create_block` MCP 接口当前标注为"复杂结构"，需在实现前确认接口参数
- 物编实体（游戏节点）的具体实体 ID 需与游戏策划确认，本规范仅定义占位类型

---

## 12. 不在本规范范围内

- Y3 游戏逻辑（触发器、技能、AI 行为）
- 地图测试与平衡性
- Round 1/2 内部逻辑修改
- 多人联机地图特殊规则
