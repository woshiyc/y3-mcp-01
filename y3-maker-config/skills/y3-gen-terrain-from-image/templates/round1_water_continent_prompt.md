# Round 1 AI Prompt：水域识别 + 大陆纹理分配

> **本轮目标**：从 CV 聚类结果中识别水域簇，完成大陆连通区域分割，为每个大陆分配主纹理。
> **本轮产出**：terrain_grid.csv (v1) + texture_grid.csv (v1)

---

## AI 输入

AI 在本轮收到以下文件：

1. **cluster_preview.png** — 像素分辨率预览图（cv_cluster.py 输出）
2. **cluster_preview_labeled.png** — 🔴 **带簇 ID 数字标注的预览图**（每个簇的最大区域中心标有簇 ID 数字，用于对照确认）
3. **palette_enhanced.json** — 每个簇的 RGB/HSV 值、像素占比 + **内部纹理复杂度**、颜色统计、空间形态、边界邻居（**使用 `rgb` 字段判断颜色，使用 `internal_complexity` / `color_stats` / `spatial_shape` 辅助判断水域**）
4. **原始地图图片** — 用于参考
5. **references/texture-color-map.md** — 🔴 **纹理颜色映射表**（Step 1.4 纹理分配时必须参考，包含所有纹理的实际渲染主色调 RGB、颜色描述和材质特征）

> ⚠️ AI 和用户都应参考 `cluster_preview_labeled.png` 来确认每个簇 ID 对应图上的哪个区域。

### palette_enhanced.json 新增字段说明

| 字段路径 | 含义 | 水域典型值 | 陆地典型值 |
|----------|------|-----------|-----------|
| `internal_complexity.fine_cluster_count` | 该粗簇区域内包含的显著细簇数量（占比>1%才计入） | ≤ 5（颜色纯净） | ≥ 8（颜色丰富） |
| `internal_complexity.fine_cluster_entropy` | 细簇分布的 Shannon 熵（bit）— 越高越杂 | < 1.0 | > 1.5 |
| `internal_complexity.dominant_fine_ratio` | 最大细簇的占比 — 越高越纯色 | > 0.6（一种色主导） | < 0.45（无主导色） |
| `internal_complexity.fine_clusters` | Top-5 细簇明细（fine_id, rgb, pct） | 全是同色系 | 包含多种不同颜色 |
| `color_stats.rgb_std_mean` | RGB 三通道标准差均值 — 越高颜色越杂 | < 15 | > 25 |
| `color_stats.rgb_range_mean` | RGB 三通道极差均值 — 越高颜色跨度越大 | < 60 | > 80 |
| `color_stats.laplacian_var` | Laplacian 方差 — 越高纹理越丰富 | < 30（平滑） | > 80（有纹理） |
| `spatial_shape.compactness` | 面积/凸包面积 — 越高越紧凑 | < 0.3（蜿蜒） | > 0.5（团块） |
| `spatial_shape.elongation` | 等效椭圆长宽比 — 越高越细长 | > 3.0（河道） | < 2.5（块状） |
| `border_neighbors` | 边界接触的其他簇 ID 列表 | 辅助参考 | 辅助参考 |

---

## Step 1.2: 水域簇识别 + 水体类型分类

### 颜色协议参考（来自 y3-optimize-terrain-image-prompt）

如果地形图由 y3-optimize-terrain-image-prompt 生成，水体颜色遵循以下固定协议：

| 水体类型 | Y3 类型 | 目标 RGB | 色相范围 | 特征 |
|---------|---------|---------|---------|------|
| **深水**（不可通行） | `deep_water` | RGB(25, 55, 135) | H≈215°, S≈80%, V≈40% | 深海蓝，大面积 |
| **浅水**（可通行） | `shallow_water` | RGB(70, 165, 205) | H≈200°, S≈60%, V≈70% | 青蓝，窄河道 |
| **平面水**（积水/沼泽） | `plain_water` | RGB(45, 100, 90) | H≈170°, S≈55%, V≈35% | 暗蓝绿，散布 |

对照 `palette_enhanced.json` 中每个水域簇的 `rgb` 字段，优先按上表 RGB 接近度判断类型。

> ⚠️ 文生图模型不保证精确还原 RGB，允许 ±30 的色差。类型判断以语义+颜色综合判断为准，不强制精确匹配。

---

### 判断标准（按优先级排序）

1. 🔴 **原图语义优先**：逐个簇对照原图位置判断，不要仅凭数值

2. 🔴 **内部纹理复杂度（最强判据）**：
   - `fine_cluster_count ≤ 5` 且 `dominant_fine_ratio > 0.6` → 倾向水域（内部颜色纯净）
   - `fine_cluster_count ≥ 8` 且 `rgb_std_mean > 25` → 几乎确定是陆地

3. 🔴 **亮色微簇否定水域**：`fine_clusters` 中出现 V>70% 的亮/白色微簇 → 该簇极不可能是水域

4. **空间形态辅助**：`elongation > 3.0` 且 `compactness < 0.3` → 倾向河道形水域

5. **色相辅助**：H≈180°~240° + S<40% + `fine_count≥6` → 几乎确定是蓝灰色陆地（岩石/山地），不是水域

6. 🔴 **空间拓扑**：被水域包围的封闭区域是岛屿，不是水域

---

### 水体类型分类（新增）

确认是水域后，进一步判断类型：

| 判断依据 | 深水 | 浅水 | 平面水 |
|---------|------|------|--------|
| RGB 接近协议值 | RGB≈(25,55,135) | RGB≈(70,165,205) | RGB≈(45,100,90) |
| 色相 | H≈210°~230° | H≈190°~210° | H≈160°~185° |
| 面积/形态 | 大面积，湖泊/主干河 | 窄长河道，1~3格宽 | 小块散布，沼泽感 |
| 有无桥梁跨越 | 通常有桥 | 无桥但可通行 | 无桥 |
| 默认 | 无法判断时默认深水 | — | — |

---

### 输出格式

展示水域簇判断表格，新增"水体类型"列（**无需用户确认，直接继续**）：

| 簇 ID | RGB | 占比 | fine_count | dom_ratio | 水域？ | 水体类型 |
|--------|-----|------|-----------|-----------|--------|---------|
| 2 | [25,55,130] | 14.6% | 3 | 0.72 | ✅ | **深水**（深蓝，大面积） |
| 13 | [68,162,200] | 4.2% | 2 | 0.81 | ✅ | **浅水**（青蓝，窄河道） |
| 9 | [43,98,88] | 2.1% | 4 | 0.65 | ✅ | **平面水**（暗蓝绿，沼泽散布） |
| 5 | [100,110,120] | 12.3% | 12 | 0.35 | ❌ | 陆地 |

输出分类结果 JSON（保存为 `<dir>/water_type_clusters.json`）：

```json
{
  "deep_water_clusters":    [2],
  "shallow_water_clusters": [13],
  "plain_water_clusters":   [9],
  "all_water_clusters":     [2, 13, 9]
}
```

将 `all_water_clusters` 传给 `cv_continent_split.py --water-clusters 2,13,9`。

---

## Step 1.3: 运行 cv_continent_split.py

水域簇确认后，执行：

```bash
python cv_continent_split.py labels.npy \
  --water-clusters <水域簇ID列表> \
  --width <W> --height <H> \
  --output-dir <dir>
```

产出：
- `water_mask_full/grid.npy` — 水域标记
- `continent_map_full/grid.npy` — 大陆编号
- `continent_summary.json` — 大陆摘要
- `continent_preview.png` — 大陆分割预览图

---

## Step 1.4: 大陆纹理分配

### 任务

查看 continent_preview.png + continent_summary.json（含 `avg_rgb` 字段），参考 `references/texture-color-map.md` 纹理颜色映射表，为每个大陆连通区域分配主纹理。

### 🔴 三阶段匹配流程（必须严格执行）

#### Phase A: 颜色分组

读取 `continent_summary.json` 中每个大陆的 `avg_rgb` 字段，**按颜色相似度对大陆分组**：

1. 对每对大陆计算 Lab 色差 ΔE（将 RGB 转 Lab 后算欧氏距离）
2. ΔE < 20 的大陆归为同一组
3. **同组大陆必须分配相同的纹理 ID**

> 💡 **人眼感知参考**：ΔE < 5 看不出差异, 5~15 微小差异, 15~30 明显不同, > 30 完全不同

#### Phase B: 为每组选择纹理

对每个颜色组的平均 RGB：

1. 查 `references/texture-color-map.md`，找 RGB 距离最近的 **5 个候选纹理**
2. 从候选中**排除材质语义不匹配的**：
   - 🔴 自然地形地图 → **禁选**：金属地面(215)、水泥地(160)、砖块类、符文类
   - 🔴 白色/浅色 → 区分雪地(90) vs 白沙(181) vs 浅色路面(182)：看材质语义
   - 🔴 深绿色 → 区分草地(6/68) vs 地底砖(74) vs 腐化地(225)：看场景适配
3. 选择**颜色最近 + 材质最匹配**的纹理 ID

#### Phase C: 输出分配表

### 判断规则

1. **每个大陆默认 1 种主纹理**（99% 情况）
2. **主动询问用户**：每个大陆是否只有一种纹理？如果有多种（如一部分是草地、一部分是沙地），需要用户指出
3. **🔴 颜色匹配优先**：以 `avg_rgb` 和 `texture-color-map.md` 的 RGB 数据做数值匹配，**不要凭名字猜**
4. **材质语义次之**：颜色相近时，选材质名称最匹配的
5. **不同大陆可以有相同的纹理**（同色组必须相同）
6. **纹理 ID 参考 `references/texture-color-map.md`**（包含实际 RGB）和 `references/texture-ids.md`（包含全量 ID）

### 输出格式

展示纹理分配表格（仅展示，**无需询问用户确认，直接继续**）：

| 大陆 ID | 面积(格) | avg_rgb | 分组 | 分配纹理 | 纹理 RGB | 纹理 ID |
|---------|----------|---------|------|----------|----------|---------|
| 1 | 850 | (100,105,85) | A | 碎石地面 | (100,95,85) | 171 |
| 4 | 350 | (95,100,80) | A | 碎石地面 | (100,95,85) | 171 |
| 2 | 620 | (155,140,100) | B | 沙地 | (160,145,105) | 165 |
| 3 | 480 | (110,90,65) | C | 泥土 | (110,90,65) | 2 |

> 🔴 **关键规则：同组（Phase A）大陆必须分配相同的纹理 ID。**
> 大陆分割只是空间隔离（被河流分开），不代表纹理不同。
> 例如上表中大陆 #1 和 #4 的 avg_rgb 接近（ΔE < 20），所以归为同组 A，都分配 `171`（碎石地面）。


---

## Step 1.4b: 纹理面板确保（自动）

纹理分配完成后，**必须**调用 MCP 接口 `ensure_terrain_textures` 将所有分配的纹理 ID 添加到编辑器面板：

```
调用 ensure_terrain_textures(texture_ids=[147, 170, 3, ...])  // 所有分配的纹理 ID
```

**根据返回结果处理**：

| 返回字段 | 处理 |
|----------|------|
| `added` 非空 | ✅ 纹理已自动添加到面板，继续 |
| `failed` 非空 | ⚠️ 面板已满（32个上限），将 failed 中的纹理替换为 `current` 列表中最接近的已有纹理，更新纹理分配表 |
| `not_downloaded` 非空 | ⚠️ 提示用户："纹理 #XXX 未下载，请在编辑器中手动下载或选择替代纹理" |
| 所有字段正常 | ✅ 直接继续生成 CSV |

> ⚠️ **必须在 Step 1.5 生成 CSV 之前完成此步骤**，否则 MCP 写入纹理时可能静默失败。

---

## Step 1.5: 生成 CSV (v1)

用户确认纹理分配后，**调用脚本**生成两张 CSV：

```bash
python scripts/gen_round1_csv.py \
  --water-mask <dir>/water_mask_grid.npy \
  --continent-map <dir>/continent_map_grid.npy \
  --texture-config '{"1": 147, "2": 170, "3": 165}' \
  --output-dir <dir>
```

其中 `--texture-config` 是 Step 1.4 中 AI 确定的大陆→纹理 ID 映射（JSON 格式）。

脚本自动完成：
- 未配置纹理的小碎片大陆 → 自动继承最近大陆的纹理
- 生成 **terrain_grid.csv(v1)**：水域格→`deep_water,0,0`，陆地格→`ground,0,0`
- 生成 **texture_grid.csv(v1)**：水域格→`0`，陆地格→对应纹理 ID

> ⛔ **禁止 AI 自行编写脚本生成 CSV**，必须调用 `scripts/gen_round1_csv.py`

---

## ⛔ AI 禁令

| # | 禁止 | 正确做法 |
|---|------|----------|
| 1 | ⛔ 禁止使用 bgr 字段判断颜色 | 使用 palette.json 的 `rgb` 字段 |
| 2 | ⛔ 禁止手写大面积 CSV 数据 | 使用脚本或基于 mask/map 生成 |
| 3 | ⛔ 禁止为大陆分配 cliff_tex_id | 统一使用默认值 0（无悬崖） |
