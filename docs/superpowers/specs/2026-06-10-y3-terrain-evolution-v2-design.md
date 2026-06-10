# Y3 地形演化 Skill v2 设计文档

**日期**: 2026-06-10
**Skill 路径**: `skills/y3-maker-config/skills/y3-terrain-evolution/`
**地图尺寸**: 256×256 格子，每格 200×200 坐标单位

---

## 背景

在现有 `y3-terrain-evolution` Skill（程序化生成 + LLM Loop）基础上进行方案 B 扩展：

- 升级高度噪声算法（fBm + Ridged Noise + Domain Warping）
- 新增 Voronoi 宏观布局（主题驱动的区域骨架）
- 新增 A* 道路规划（文明时代）
- 调整评分策略（地质/文明用数据评分，生态用视觉评分）
- 新增 Three.js 预览服务器（仅在生态时代后触发截图评分）
- 分步 MCP 写入（A/B/C 三个 Pass，每步暂停让用户在编辑器确认）

### 去掉的内容（Y3 不支持）

| 原方案内容 | 原因 |
|---|---|
| 岩浆系统 | Y3 无对应 MCP 接口 |
| 视觉模型截图评分（地质/文明时代） | 仅生态时代有价值，其余时代数据评分更可靠 |

---

## 整体架构：三层分离

```
数据层（Python 脚本）
  → 程序化生成 world_state.json / ecology_layer.json / civilization_layer.json

预览层（Three.js）
  → 仅在生态时代主评分通过后触发
  → 本地 HTTP 服务 + 俯视截图 → Claude API 视觉评分

写入层（MCP）
  → 分 Pass A / B / C 写入，每步暂停等用户确认
```

---

## Stage 0：前置准备

### 0.1 依赖检测

```bash
python scripts/check_deps.py
```

### 0.2 配置读取与确认

读取 `config/world_config.json`，向用户确认：

```
地图尺寸: 256 × 256
种子: {seed}
主题: {theme}（如 forest_valley）
水域目标比例: {target_water_ratio}%
山地目标比例: {target_mountain_ratio}%
允许裂隙: {allow_cracks}
允许斜坡: {allow_slopes}
```

**主题选项**（影响 Voronoi 宏观布局）：

| 主题 ID | 名称 | 特征 |
|---|---|---|
| `forest_valley` | 森林山谷 | 四周山地，中心低地，河流汇聚 |
| `lake_plain` | 湖泊平原 | 大面积平地，散布湖泊，低起伏 |
| `mountain_village` | 山地村庄 | 山脊为主，平坦聚落区嵌入山间 |
| `swamp_ruins` | 沼泽废墟 | 低洼湿地为主，碎裂水域，少量高地 |
| `arctic_peak` | 雪山极地 | 高峰突出，大面积雪地，冰湖 |

### 0.3 资产配置（asset_profiles.json）

优先使用 `config/asset_profiles.json`（已填写 model_id → 直接使用）。
model_id 未填写 → 跳过模型放置，只生成群系标签。

### 0.4 纹理配置（texture_profiles.json）

已填写 → 全功能纹理评估
未填写 → 跳过特殊纹理，只做通用逻辑规则评估

### 0.5 创建输出目录

```
output/
├── world_state.json
├── terrain_summary.json
├── ecology_layer.json
├── civilization_layer.json
├── texture_assignments.json
├── patch_history.json
├── texture_issues.json
└── final_report.md
```

---

## Stage 1：地质时代

> **目标**: 生成地形骨架（高度、水域、河流、裂隙、斜坡、生物群系初分类）
> **推进条件**: overall ≥ 70 且 connectivity ≥ 60 且 all_land_connected = true
> **评分方式**: 数据评分（JSON 摘要 → LLM 文本评估）

### 1.1 程序化生成（Voronoi + 噪声升级）

```bash
python scripts/generate_terrain.py \
  --config config/world_config.json \
  --output-dir output/
```

**算法流程（相比 v1 的变化）**：

1. **Voronoi 宏观布局**（新增）
   根据 `theme` 撒关键点（山脉脊线、低地、水源、出生点、目标点）→ Voronoi 分区 → 生成 `layout_mask`（每区的高度 bias）

2. **fBm + Ridged Noise + Domain Warping**（升级）
   - Domain Warping：先用一层 fBm 扭曲采样坐标，再采样主噪声，使山脉自然蜿蜒
   - Ridged Noise：`ridged = 1 - |noise|`，生成锋利山脊
   - 叠加：`hill_map = fBm * 0.5 + Ridged * 0.3 + layout_bias * 0.2`

3. **悬崖台阶**：连续高度 → 离散整数层级（cliff_map），指数分布（低台阶多，高台阶少）

4. **水域**：高度阈值 → deep/shallow/plain 分类，大水体（>1.8%）→ plain water

5. **河流**：梯度流（从高处沿最低邻居流向水域）→ shallow_water 格子

6. **裂隙**：随机断层线（Bresenham + 随机游走）→ crack_map

7. **斜坡检测**：cliff_map 相邻差值 ≥ 1 → slope_map（flat=1/2/3）
   ⚠️ 斜坡必须主动写入（Pass A 最后执行），不依赖引擎自动生成

8. **生物群系初分类**：高度 + 水距 + cliff 层级 → biome_map
   （mountain / hill / forest / plain / wetland / coastal / water）

**world_state.json 新增字段**：`theme`、`layout_map`

### 1.2 生成地形摘要

```bash
python scripts/analyze_terrain.py \
  --world-state output/world_state.json \
  --output output/terrain_summary.json
```

**摘要新增字段**（用于新增评分维度）：

| 字段 | 说明 |
|---|---|
| `mountain_chain_count` | 高值格子连通链数量（山脉走势） |
| `mountain_chain_avg_length` | 平均山脊链长度 |
| `river_validity_ratio` | 河流中下坡格子占比（合法性） |
| `coastal_avg_width` | 水岸 coastal 区域平均宽度（格子数） |

### 1.3 LLM 数据评分（地质时代）

AI 读取 `output/terrain_summary.json`，参照 `prompts/terrain_era_eval_prompt.md` 评分。

**评分维度（在原有基础上新增）**：

| 维度 | 说明 |
|---|---|
| `composition` | 整体构图，山地/平原/水域分布是否有层次 |
| `terrain_rhythm` | 高低节奏，不能全平或全山 |
| `water_system` | 水域是否集中在低洼，不碎裂 |
| `connectivity` | 陆地连通性 |
| `boundary_design` | 边界处理 |
| `mountain_linearity` | **新增** 山脉是否形成连绵走势（非孤岛噪声点） |
| `river_validity` | **新增** 河流是否合法下坡 |
| `water_bank_transition` | **新增** 水岸过渡是否自然（coastal 区域是否足够宽） |

### 1.4 主评估分支

```
overall >= 70 AND connectivity >= 60 → 进入 1.5（纹理评估）
否则 → apply_patch.py --era terrain → 回到 1.2
连续 5 轮未达标 → 询问用户是否继续或降低阈值
```

### 1.5 纹理评估（地质时代后）

参照 `prompts/texture_terrain_eval_prompt.md`，阈值 ≥ 65，不达标记录但不阻断。

---

## Stage 2：生态时代

> **目标**: 生物群系细化 + 植被/模型分布方案
> **推进条件**: overall ≥ 65
> **评分方式**: 数据评分（主评估）→ **视觉评分**（主评估通过后，Three.js 截图 → Claude vision）

### 2.1 生成生态层

```bash
python scripts/generate_ecology.py \
  --world-state output/world_state.json \
  --asset-profiles output/asset_profiles.json \
  --output output/ecology_layer.json
```

### 2.2 更新摘要 + LLM 数据评分

参照 `prompts/ecology_era_eval_prompt.md`

**评分维度**：`biome_identity`、`vegetation_reasonability`、`density_rhythm`、`ecological_believability`

### 2.3 主评估分支

```
overall >= 65 → 进入 2.4（视觉评分）
否则 → apply_patch.py --era ecology → 回到 2.2
```

### 2.4 视觉评分（生态时代专属，唯一一次截图）

```bash
# 步骤 1：启动预览服务器（后台）
python scripts/preview_server.py --background --port 9876

# 步骤 2：截图 + 视觉评分
python scripts/visual_eval.py \
  --era ecology \
  --world-state output/world_state.json \
  --ecology output/ecology_layer.json \
  --output output/visual_eval_ecology.json
```

**Three.js 渲染内容**：
- 高度位移（hill_map）
- biome 颜色着色（mountain=灰 / forest=绿 / water=蓝 / wetland=橄榄 / coastal=棕黄）
- 模型分布热力图（密度着色，非实际模型）
- 摄像机：俯视 45° 固定

**visual_eval.py 流程**：
1. 检查 localhost:9876 是否已有运行中的 server；若无则启动 `preview_server.py --background`
2. POST `/screenshot` → base64 PNG
3. 构造 prompt（含当前时代、关键统计数据、审美评分维度）
4. 调用 Claude API（claude-sonnet-4-6，vision 输入）
5. 解析返回 → `output/visual_eval_ecology.json`

**`visual_eval_ecology.json` 输出 schema**：

```json
{
  "era": "ecology",
  "overall": 72,
  "dimensions": {
    "composition": 75,
    "biome_contrast": 70,
    "biome_transition": 68,
    "density_rhythm": 74,
    "naturalness": 78
  },
  "issues": ["东北角生物群系边界过硬", "水域过于分散"],
  "suggestions": ["增加 coastal 过渡带宽度", "合并碎片湖泊"],
  "ready_to_advance": true
}
```

`visual_overall` 即 `overall` 字段，Stage 2.4 分支读取此值。

**preview_server.py 生命周期**：
- Stage 2.4 首次调用 `visual_eval.py` 时，脚本检查端口 9876 是否可用：
  - 可用 → 启动服务器（后台进程，记录 PID 到 `output/preview_server.pid`）
  - 已占用 → 复用已有进程（无需重启）
- 视觉评分 Patch 重试时（重跑 2.1 → 重跑视觉评分），server 保持运行，`/world_state` 接口返回更新后的 JSON
- Stage 2 结束后（进入 Stage 3）：server 继续保留，不主动关闭（用户可在浏览器继续预览）
- 下次 Skill 启动时：如 PID 文件存在且进程仍活跃，直接复用

**视觉评分维度**（审美维度，数据难以量化的部分）：

| 维度 | 说明 |
|---|---|
| `composition` | 整体构图，是否有视觉焦点 |
| `biome_contrast` | 生物群系颜色对比是否明确 |
| `biome_transition` | 群系过渡是否自然（无硬切边界） |
| `density_rhythm` | 植被/模型疏密是否有节奏感 |
| `naturalness` | 整体是否看起来自然 |

**视觉评分分支**：

```
visual_overall >= 65 → 进入 Stage 3
visual_overall < 65 → 生成视觉修改建议 → apply_patch.py --era ecology → 重跑 2.1 → 重跑视觉评分
连续 3 轮视觉未达标 → 询问用户（3 轮上限由 world_config.json era_thresholds.max_visual_iterations 配置）
```

### 2.5 纹理评估（生态时代后）

阈值 ≥ 70，不达标记录但不阻断。

---

## Stage 3：文明时代

> **目标**: A* 道路规划 + 聚落放置
> **推进条件**: overall ≥ 60 且 unconnected_settlements = 0
> **评分方式**: 数据评分

### 3.1 生成文明层

```bash
python scripts/generate_civilization.py \
  --world-state output/world_state.json \
  --ecology output/ecology_layer.json \
  --asset-profiles output/asset_profiles.json \
  --output output/civilization_layer.json
```

**A* 道路规划（新增）**：

```
输入: 聚落位置列表 + cliff_map（坡度 cost）
连通性: 4-connectivity（上下左右，不允许对角线移动）
  ⚠️ 不用对角线是为了防止道路绕过悬崖角落（corner-bypass 问题）

Cost Map:
  - 相邻 cliff_map 差值 ≥ 2 → 极高 cost（Y3 悬崖边界不可通行，traversability 评分也会惩罚此类格子）
  - 差值 = 1 → 中等 cost
  - 差值 = 0 → 低 cost
  - 水域格子 → 不可通行（cost = ∞）
  - 已有道路格子 → cost 减半（鼓励共线复用）

A* 路径: 连通所有聚落（MST 选路顺序减少总长度）
输出: road_cells[] → civilization_layer.json
```

### 3.2 LLM 数据评分（文明时代）

参照 `prompts/civilization_era_eval_prompt.md`

**评分维度（原有基础上新增）**：

| 维度 | 说明 |
|---|---|
| `settlement_terrain_fit` | 聚落是否在平坦区域 |
| `road_design` | 道路是否连通、走向自然 |
| `gameplay_space` | 可探索空间分布 |
| `visual_readability` | 功能区域是否可读 |
| `landmark_exploration` | 地标和探索点 |
| `traversability` | **新增** 道路是否跨越 cliff_map 差值 ≥ 2 的格子（不可通行边界） |
| `settlement_connectivity` | **新增** 所有聚落是否可达（连通分析） |
| `path_ratio` | **新增** 主路 vs 支路比例（避免全主路或全支路） |

### 3.3 主评估分支 + 特殊纹理评估

```
overall >= 60 AND unconnected_settlements = 0 → Stage 4
否则 → apply_patch.py --era civilization → 回到 3.2
连续 5 轮未达标 → 询问用户
```

---

## Stage 4：稳定时代

### 4.1 最终验证

```bash
python scripts/validate_world.py \
  --world-state output/world_state.json \
  --ecology output/ecology_layer.json \
  --civilization output/civilization_layer.json \
  --output output/validation_report.json
```

### 4.2 生成最终报告（final_report.md）

包含各时代评分、纹理问题汇总、已知问题列表。

### 4.3 用户确认写入

```
是否开始 MCP 分步写入？
1. Y3 编辑器已打开
2. 目标地图已加载
3. y3editor MCP 已连接

输入 "确认写入" 继续
```

---

## Stage 5：分步 MCP 写入

每个 Pass 完成后暂停，用户在编辑器确认效果后再继续。

### CLI 接口定义（mcp_writer.py v2）

```bash
python scripts/mcp_writer.py \
  --world-state output/world_state.json \
  --ecology output/ecology_layer.json \
  --civilization output/civilization_layer.json \
  [--texture-assignments output/texture_assignments.json] \
  --pass A|B|C \           # 新增：指定执行哪个 Pass
  --single-batch 1 \       # 每批 100 格，循环直到 all_done
  [--restart] \            # 从当前 Pass 头部重来（不影响其他 Pass）
  [--url <url>] \
  [--timeout <s>]
```

进度文件：每个 Pass 独立存储（`output/mcp_progress_A.json`、`_B.json`、`_C.json`），`--restart` 仅清除当前 Pass 的进度文件。

### Pass A：地形骨架

```bash
python scripts/mcp_writer.py \
  --world-state output/world_state.json \
  --pass A --single-batch 1
```

写入顺序（⚠️ 斜坡不在此 Pass，见 Pass C）：
1. `terrain_hill_lift_block` — FBM 连续起伏（hill_map）
2. `terrain_set_height_block` — 悬崖台阶（cliff_map，API height = level × 2）
3. `terrain_set_crack_block` — 裂隙（terrain_height = -40）
4. `terrain_set_deep_water_block` — 深水
5. `terrain_set_shallow_water_block` — 浅水（含河流）
6. `terrain_set_plain_water_block` — 平面水（湖面/海面）

完成后输出：
```
✅ Pass A 完成（地形骨架，无纹理/斜坡）
请在 Y3 编辑器中查看地形高度和水域效果。
确认后输入 "继续 B" 执行纹理写入。
```

### Pass B：纹理

```bash
python scripts/mcp_writer.py \
  --world-state output/world_state.json \
  --texture-assignments output/texture_assignments.json \
  --pass B --single-batch 1
```

写入：`terrain_cover_draw_block`（地形材质 + 道路纹理模拟）

完成后输出：
```
✅ Pass B 完成（纹理）
请在 Y3 编辑器中查看纹理效果。
确认后输入 "继续 C" 执行装饰物和斜坡写入。
```

### Pass C：装饰物 + 斜坡

```bash
python scripts/mcp_writer.py \
  --world-state output/world_state.json \
  --ecology output/ecology_layer.json \
  --civilization output/civilization_layer.json \
  --pass C --single-batch 1
```

写入顺序（斜坡必须在植被之后）：
1. `terrain_vegetation_draw_block` — 地表贴片（草/花/芦苇）
2. `terrain_set_road_block` — 斜坡（**必须在所有地形/纹理/植被之后写**）
3. `entity_create_block` — 3D 模型（树木/岩石/建筑/聚落摆件）

完成后输出：
```
✅ Pass C 完成（装饰物 + 斜坡）
地形演化全部写入完成。
```

每个 Pass 支持 `--restart` 从 Pass 头部重来，不影响其他 Pass 的进度。

---

## 文件结构

```
y3-terrain-evolution/
├── SKILL.md                          ← 主 Skill 文件（更新）
├── config/
│   ├── world_config.json             ← 修改：256×256，新增 theme 字段
│   ├── era_weights.json              ← 保留
│   ├── texture_profiles.json         ← 保留
│   └── asset_profiles.json           ← 保留
├── prompts/
│   ├── terrain_era_eval_prompt.md    ← 修改：新增 3 个维度
│   ├── ecology_era_eval_prompt.md    ← 保留
│   ├── civilization_era_eval_prompt.md ← 修改：新增 3 个维度
│   ├── texture_terrain_eval_prompt.md ← 保留
│   ├── texture_special_eval_prompt.md ← 保留
│   └── patch_plan_format.md          ← 保留
├── scripts/
│   ├── check_deps.py                 ← 保留
│   ├── generate_terrain.py           ← 修改：Voronoi + fBm+Ridged+DomainWarping
│   ├── generate_ecology.py           ← 保留
│   ├── generate_civilization.py      ← 修改：A* 道路规划
│   ├── analyze_terrain.py            ← 修改：新增 4 个摘要字段
│   ├── apply_patch.py                ← 保留
│   ├── validate_world.py             ← 保留
│   ├── preview_server.py             ← 新增：Three.js HTTP 服务器
│   ├── visual_eval.py                ← 新增：截图 + Claude API 视觉评分
│   └── mcp_writer.py                 ← 修改：支持 --pass A/B/C
└── static/
    └── viewer.html                   ← 新增：Three.js 俯视渲染页面
```

---

## 实现注意事项

### world_config.json 需更新的字段

```json
{
  "seed": 42,
  "map_width": 256,
  "map_height": 256,
  "theme": "forest_valley",
  "generation_rules": { ... },
  "era_thresholds": {
    "terrain_advance_score": 70,
    "ecology_advance_score": 65,
    "civilization_advance_score": 60,
    "max_iterations_per_era": 8,
    "max_visual_iterations": 3
  },
  ...
}
```

### generate_terrain.py 需删除的错误注释

`generate_terrain.py` 第 417 行有如下过时注释，**必须删除**：
```python
# slope_map 标注出 cliff_map 中相邻高差=2的格子（引擎会在这些位置自动生成斜坡）
# 仅作参考和评估输出，不参与 MCP 写入（terrain-adjacency-rules.md §5.2）
```
v2 中斜坡必须通过 Pass C 的 `terrain_set_road_block` 主动写入，不依赖引擎自动生成。

### generate_ecology.py CLI 说明

v2 保留 `--texture-profiles` 参数（与 v1 兼容），但可选。SKILL.md 调用时如已配置纹理则传入，未配置则省略。

---

## 关键约束与注意事项

### Y3 地形系统约束

| 约束 | 处理方式 |
|---|---|
| cliff_map 是离散整数台阶，不是连续高度 | 算法量化后 API height = level × 2 |
| 斜坡只有横向/纵向/角落三种，不是连续坡面 | 检测相邻 cliff_map 差值 ≥ 1 的格子，flat=1/2/3 |
| 任何地形/水体/纹理操作都会覆盖斜坡 | Pass C 中斜坡写入在植被之后、entity 之前，严格放在所有地形/纹理/植被完成后 |
| 道路 cliff_map 差值 ≥ 2 的格子实际不可通行 | A* cost map 中此类格子设极高代价 |
| 运行时修改需开启「允许地形修改」 | SKILL.md 中提醒用户 |

### 评分策略

| 时代 | 评分方式 | 理由 |
|---|---|---|
| 地质时代 | 数据评分 | 结构性问题可算法验证，数字比图像准确 |
| 生态时代 | 视觉评分（唯一截图） | 审美特质在此时最丰富，biome 颜色已完整 |
| 文明时代 | 数据评分 | 连通性/通行性是精确计算问题 |

### MCP 写入顺序（不可更改）

hill → cliff → crack → deep_water → shallow_water → plain_water → texture → vegetation → slope → **entity（最后）**
