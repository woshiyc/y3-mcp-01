---
name: y3-terrain-evolution
description: 通过 LLM Loop + 程序化生成 + 分时代演化生成 Y3 地形地图。不需要图片输入，不读取已有地形，全程数据变换，最终 MCP 批量写入。触发词：地形演化、生成地形地图、terrain evolution、程序化地图生成、生成Y3地图。
---

# Y3 地形地图演化（y3-terrain-evolution）

通过 **分时代演化** 生成 Y3 地形地图：
地质时代（地形骨架）→ 生态时代（生物群系 + 模型放置）→ 文明时代（聚落 + 道路）→ 稳定时代（验证冻结）→ MCP 写入

每个时代内部运行 **双重 LLM 评估 Loop**：
- **主评估**：程序化生成 → JSON 摘要 → LLM 评估结构/生态/文明 → Patch → 循环直到达标
- **纹理评估**：主评估通过后 → LLM 评估纹理逻辑 → 记录纹理问题 → 推进下一时代

---

## ⛔ 全局禁令

| # | 禁令 |
|---|------|
| 1 | ⛔ **禁止 LLM 输出任何格子坐标** — 空间操作全部由脚本完成 |
| 2 | ⛔ **禁止跳过 LLM 主评估直接推进时代** — 每个时代必须通过评分阈值 |
| 3 | ⛔ **禁止在同一时代连续执行超过 5 轮 Patch 而不询问用户** |
| 4 | ⛔ **禁止在地质时代修改生态/文明层** — 严格遵守时代权重限制 |
| 5 | ⛔ **禁止跳过依赖检测直接运行生成脚本** |
| 6 | ⛔ **禁止在用户未确认时执行 MCP 写入** |
| 7 | ⛔ **禁止因纹理评估未通过而阻断主流程** — 纹理问题记录在案，不阻断时代推进 |

---

## Stage 0：前置准备

### 0.1 检查依赖

```bash
python scripts/check_deps.py
```

| 结果 | 处理 |
|------|------|
| `{"status": "ok"}` | ✅ 静默继续 |
| `{"status": "missing", ...}` | 自动安装，失败则提示用户手动安装 |

### 0.2 读取世界配置

读取 `config/world_config.json`，向用户确认关键参数：

```
地图尺寸: {map_width} x {map_height}
种子: {seed}
水域目标比例: {target_water_ratio * 100}%
山地目标比例: {target_mountain_ratio * 100}%
允许裂隙: {allow_cracks}
允许斜坡: {allow_slopes}
```

### 0.3 检查资产配置（asset_profiles.json）

询问用户是否有 `asset_profiles.json`（来自 y3-model-evaluator skill）：
- 有 → 询问路径，复制到 `output/asset_profiles.json`
- 没有 → 跳过模型放置，只生成群系标签

> **格子尺寸说明（09-地形系统.md）**：Y3 默认地形格子 = 50×50cm。
> 填写 `footprint_cells` 时：模型最大直径(cm) ÷ 50 = footprint_cells
> 示例：树冠 3m → 6格；大型岩石 1.5m → 3格；小灌木 0.5m → 1格
>
> asset_profiles 两类 system：
> - `entity_create`（默认）：3D 模型，按 `footprint_cells` 间距 Poisson 采样放置
> - `vegetation_draw`：地表贴片（草/花/芦苇），按 `vegetation_type` + `density` 区域整体铺设，无需间距

### 0.4 检查纹理配置（texture_profiles.json）

询问用户是否有填写好的 `texture_profiles.json`（config/ 目录已有模板）：
- 已填写 → 加载 `config/texture_profiles.json`，纹理评估全功能开启
- 未填写 → 使用通用地形逻辑规则评估，跳过特殊纹理（`enable_special_textures = false`）

> `texture_profiles.json` 需要用户根据 Y3 项目实际可用纹理资产填写 `y3_texture_id` / `y3_decal_id`。模板在 `config/texture_profiles.json`。

### 0.5 创建输出目录

所有产出统一写入 `output/` 目录：
```
output/
├── world_state.json              ← 当前世界状态（每次更新覆盖）
├── terrain_summary.json          ← LLM 评估用摘要（每次更新）
├── ecology_layer.json            ← 生态时代产出
├── civilization_layer.json       ← 文明时代产出
├── texture_assignments.json      ← 纹理分配方案（每次更新）
├── patch_history.json            ← 所有 Patch Plan 记录
├── texture_issues.json           ← 纹理评估问题记录（汇总）
└── final_report.md               ← 最终评估报告
```

用户确认后开始演化。

---

## Stage 1：地质时代（Era Terrain）

> **目标**：生成地形骨架。完成后地形基本冻结，后续时代只允许微调。
> **主评估推进条件**：overall ≥ 70 且 connectivity ≥ 60 且 all_land_connected = true

### 1.1 程序化生成初始地形

```bash
python scripts/generate_terrain.py \
  --config config/world_config.json \
  --texture-profiles config/texture_profiles.json \  # 可选
  --output-dir output/
```

产出 `output/world_state.json`，包含：
- `hill_map`：FBM 连续高度（用于 `terrain_hill_lift_block`）
- `cliff_map`：悬崖台阶层级（用于 `terrain_set_height_block`）
- `water_map`：水域类型（deep/shallow/plain）
- `slope_map`：斜坡方向（用于 `terrain_set_road_block`）
- `crack_map`：裂隙位置（用于 `terrain_set_crack_block`）
- `biome_map`：生物群系标签
- `texture_plan`：基于 texture_profiles 的初始纹理分配方案

### 1.2 生成地形摘要

```bash
python scripts/analyze_terrain.py \
  --world-state output/world_state.json \
  --output output/terrain_summary.json
```

### 1.3 LLM 主评估（地质时代）

**AI 读取 `output/terrain_summary.json`，参照 `prompts/terrain_era_eval_prompt.md` 输出评估结果。**

评分维度：`composition`、`terrain_rhythm`、`water_system`、`connectivity`、`boundary_design`

### 1.4 主评估分支

```
if ready_to_advance == true AND overall >= 70:
    → 执行 1.5（纹理评估）

if ready_to_advance == false OR overall < 70:
    → 执行地质时代 Patch（apply_patch.py --era terrain）
    → 回到 1.2

if 连续 5 轮仍未达标:
    → 询问用户："当前评分 {score}，是否继续迭代？还是降低阈值推进？"
```

### 1.5 LLM 地形纹理评估（地质时代后）

**AI 读取 `output/terrain_summary.json`（含 texture_plan 字段），参照 `prompts/texture_terrain_eval_prompt.md` 输出纹理评估结果。**

评分维度：`coverage_completeness`、`logic_correctness`、`biome_identity`、`gameplay_readability`

```
if texture_overall >= 65:
    → ✅ 纹理评估通过，进入 Stage 2

if texture_overall < 65:
    → 将 texture_patch_plan 写入 output/texture_issues.json（记录在案）
    → ⚠️ 提示用户纹理存在问题（不阻断流程）
    → 进入 Stage 2（纹理问题将在后续时代修正）
```

### 1.6 执行地质时代 Patch Plan（主评估未通过时）

```bash
python scripts/apply_patch.py \
  --world-state output/world_state.json \
  --patch '{ ... patch_plan JSON ... }' \
  --era terrain \
  --output output/world_state.json
```

> ⚠️ `--era terrain` 参数确保脚本遵守地质时代权重，只允许修改地形层。

---

## Stage 2：生态时代（Era Ecology）

> **目标**：根据地形生成生物群系 + 模型放置方案。
> **主评估推进条件**：overall ≥ 65

### 2.1 生成生态层

```bash
python scripts/generate_ecology.py \
  --world-state output/world_state.json \
  --asset-profiles output/asset_profiles.json \  # 可选
  --texture-profiles config/texture_profiles.json \  # 可选
  --output output/ecology_layer.json
```

产出：
- 生物群系确认（biome_map 精细化）
- 模型放置方案（每个模型类型的分布区域 + 采样坐标）
- 纹理分配方案更新（生态层细化 biome 纹理）

### 2.2 更新摘要

```bash
python scripts/analyze_terrain.py \
  --world-state output/world_state.json \
  --ecology output/ecology_layer.json \
  --output output/terrain_summary.json
```

### 2.3 LLM 主评估（生态时代）

**AI 参照 `prompts/ecology_era_eval_prompt.md` 评估生态层。**

评分维度：`biome_identity`、`vegetation_reasonability`、`density_rhythm`、`ecological_believability`

### 2.4 主评估分支

```
if ready_to_advance == true AND overall >= 65:
    → 执行 2.5（纹理评估）

if ready_to_advance == false OR overall < 65:
    → 执行生态时代 Patch（apply_patch.py --era ecology）
    → 回到 2.2

if 连续 5 轮仍未达标:
    → 询问用户
```

### 2.5 LLM 地形纹理评估（生态时代后）

**AI 参照 `prompts/texture_terrain_eval_prompt.md` 评估生态层纹理（重点：biome 辨识纹理）。**

通过阈值：overall ≥ 70（比地质时代更严，biome 辨识必须到位）

```
if texture_overall >= 70:
    → ✅ 纹理评估通过，进入 Stage 3

if texture_overall < 70:
    → 将 texture_patch_plan 追加写入 output/texture_issues.json
    → ⚠️ 提示用户（不阻断流程）
    → 进入 Stage 3
```

---

## Stage 3：文明时代（Era Civilization）

> **目标**：基于地形 + 生态生成聚落、道路、建筑。
> **主评估推进条件**：overall ≥ 60 且 unconnected_settlements == 0

### 3.1 生成文明层

```bash
python scripts/generate_civilization.py \
  --world-state output/world_state.json \
  --ecology output/ecology_layer.json \
  --asset-profiles output/asset_profiles.json \
  --texture-profiles config/texture_profiles.json \  # 可选
  --output output/civilization_layer.json
```

产出额外包含：
- 特殊纹理分配方案（怪物巢穴/聚落踩踏/遗迹石板等叙事纹理）

### 3.2 LLM 主评估（文明时代）

**AI 参照 `prompts/civilization_era_eval_prompt.md` 评估文明层。**

评分维度：`settlement_terrain_fit`、`road_design`、`gameplay_space`、`visual_readability`、`landmark_exploration`

### 3.3 主评估分支

```
if ready_to_advance == true AND overall >= 60 AND unconnected_settlements == 0:
    → 执行 3.4（特殊纹理评估）

if ready_to_advance == false:
    → 执行文明时代 Patch（apply_patch.py --era civilization）
    → 回到 3.2

if 连续 5 轮仍未达标:
    → 询问用户
```

### 3.4 LLM 特殊纹理评估（文明时代后）

**AI 读取 `output/civilization_layer.json`，参照 `prompts/texture_special_eval_prompt.md` 评估叙事纹理分配。**

评分维度：`narrative_coverage`、`narrative_logic`、`model_integration`、`coverage_density`

> 仅当 `texture_profiles.json` 中 `enable_special_textures = true` 且有填写 `y3_decal_id` 时运行。否则跳过此步骤。

```
if texture_overall >= 60:
    → ✅ 特殊纹理评估通过，进入 Stage 4

if texture_overall < 60:
    → 将 special_texture_patch_plan 追加写入 output/texture_issues.json
    → ⚠️ 提示用户（不阻断流程）
    → 进入 Stage 4

if texture_overall < 40:
    → 询问用户："特殊纹理评分 {score}，叙事感较弱。是否继续，还是先修正纹理分配？"
```

---

## Stage 4：稳定时代（Era Stable）

### 4.1 最终验证

```bash
python scripts/validate_world.py \
  --world-state output/world_state.json \
  --ecology output/ecology_layer.json \
  --civilization output/civilization_layer.json \
  --output output/validation_report.json
```

### 4.2 生成最终报告

AI 读取 `validation_report.json` 和 `output/texture_issues.json`，生成 `output/final_report.md`：

```
## 地形演化最终报告

### 地质层
- 地图尺寸: WxH
- 构图评分: XX | 高低节奏: XX | 水体系统: XX | 连通性: XX | 边界处理: XX
- 水域比例: XX%

### 生态层
- 生物群系数: N 种
- 模型放置数: N 个
- 区域辨识: XX | 植被合理性: XX | 密度节奏: XX

### 文明层
- 聚落数: N | 道路段数: N
- 地标数: N | 探索点: N

### 纹理评估汇总
- 地形纹理评分（地质后）: XX
- 地形纹理评分（生态后）: XX
- 特殊纹理评分（文明后）: XX
- 待修正纹理问题: N 项（详见 texture_issues.json）

### 已知问题
- ...
```

### 4.3 用户确认

展示报告，询问：
```
是否开始 MCP 写入到 Y3 编辑器？
请确认：
1. Y3 编辑器已打开
2. 目标地图已加载
3. y3editor MCP 已连接

输入 "确认写入" 继续，或 "放弃" 结束。
```

---

## Stage 5：MCP 批量写入

```bash
python scripts/mcp_writer.py \
  --world-state output/world_state.json \
  --ecology output/ecology_layer.json \
  --civilization output/civilization_layer.json \
  --texture-assignments output/texture_assignments.json \  # 可选
  --single-batch 1
```

写入顺序（严格不可乱序，来源：terrain-adjacency-rules.md + y3-terrain-basics.md）：
1. **Pass 1: Hill Lift** — `terrain_hill_lift_block`（FBM 连续地形起伏）
2. **Pass 2: Cliff Height** — `terrain_set_height_block`（悬崖台阶，API height = 层数 × 2；相邻高差=2处引擎自动生成斜坡）
3. **Pass 3: Crack** — `terrain_set_crack_block`（裂隙，terrain_height=-40）
4. **Pass 4: Deep Water** — `terrain_set_deep_water_block`
5. **Pass 5: Shallow Water** — `terrain_set_shallow_water_block`
6. **Pass 6: Plain Water** — `terrain_set_plain_water_block`
7. **Pass 7: Terrain Textures** — `terrain_cover_draw_block`（地形材质，格点坐标）
8. **Pass 8: Vegetation** — `terrain_vegetation_draw_block`（地表贴片：草/花/芦苇，非 3D 模型）
9. **Pass 9: Entities** — `entity_create_block`（3D 模型：树木/岩石/建筑/道路摆件，世界坐标）

> **斜坡不主动写**（terrain-adjacency-rules.md §5.2）：引擎在 cliff_height 写入后自动在相邻高差=2处生成斜坡。
> `slope_map` 仅保留在 `world_state.json` 中供分析和评估使用，不参与 MCP 写入。

每批 100 格，循环直到 `status == "all_done"`。

---

## 时代权重系统

详见 `config/era_weights.json`。核心规则：

| 时代 | terrain | ecology | civilization |
|------|---------|---------|--------------|
| 地质 | 0.80 | 0.05 | 0.00 |
| 生态 | 0.15 | 0.45 | 0.05 |
| 文明 | 0.05 | 0.25 | 0.50 |
| 稳定 | 0.00 | 0.10 | 0.85 |

`apply_patch.py` 使用这些权重限制每个时代允许的修改范围。

---

## 纹理评估时机总览

| 时机 | 评估文件 | 阈值 | 阻断流程 |
|------|---------|------|---------|
| 地质时代主评估通过后 | texture_terrain_eval_prompt.md | ≥ 65 | 否，记录问题 |
| 生态时代主评估通过后 | texture_terrain_eval_prompt.md | ≥ 70 | 否，记录问题 |
| 文明时代主评估通过后 | texture_special_eval_prompt.md | ≥ 60 | 否（< 40 询问用户） |

---

## 文件结构

```
y3-terrain-evolution/
├── SKILL.md
├── config/
│   ├── world_config.json
│   ├── era_weights.json
│   └── texture_profiles.json       ← 纹理预配置（用户填写 Y3 资产 ID）
├── prompts/
│   ├── terrain_era_eval_prompt.md
│   ├── ecology_era_eval_prompt.md
│   ├── civilization_era_eval_prompt.md
│   ├── texture_terrain_eval_prompt.md  ← 地形纹理评估
│   ├── texture_special_eval_prompt.md  ← 特殊纹理评估
│   └── patch_plan_format.md
├── scripts/
│   ├── check_deps.py
│   ├── generate_terrain.py
│   ├── analyze_terrain.py
│   ├── apply_patch.py
│   ├── generate_ecology.py
│   ├── generate_civilization.py
│   ├── validate_world.py
│   └── mcp_writer.py
└── output/                          ← 运行时产出（gitignore）
    ├── texture_assignments.json
    └── texture_issues.json
```
