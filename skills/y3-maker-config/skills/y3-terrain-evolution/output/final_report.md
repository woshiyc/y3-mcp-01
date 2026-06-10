# 地形演化最终报告
**主题**: forest_valley | **种子**: 42 | **尺寸**: 256×256 | **格子**: 200×200cm

---

## 地质层

| 指标 | 值 | 评分 |
|------|-----|------|
| 水域比例 | 13.2%（深 0.3% / 浅 6.5% / 平 6.5%） | — |
| 山地(mountain+hill) | 51.4% | — |
| 陆地连通 | ✅ 1 个连通区域 | — |
| 高度标准差 | 0.18 | — |
| 最大水体 | 7.1%（湖泊） | — |
| 海岸过渡宽度 | 6.5 格 | — |
| 河流合法性 | 100% | — |

**地质时代评分**: overall = **70.8** ≥ 70 ✅
- composition: 75 | terrain_rhythm: 70 | water_system: 75
- connectivity: **100** | boundary_design: 55 | mountain_linearity: 60
- river_validity: 40 | water_bank_transition: 40

**地形纹理评分**（地质后）: 79.3 ≥ 65 ✅

---

## 生态层

| 指标 | 值 |
|------|-----|
| 生物群系数 | 6种（mountain/cliff/hill/forest/wetland/coastal） |
| 模型总数 | 1650 个（decoration 1362 / vegetation 283 / building 5） |
| 最高密度区 | coastal（配置 0.20）|
| 最低密度区 | hill（配置 0.014）|
| 密度比 | 14:1 > 3:1 ✅ |
| 怪物区主分布 | mountain/cliff（分别 632/329 个区域）|

**生态时代评分**: overall = **69.0** ≥ 65 ✅
- biome_identity: 75 | vegetation_reasonability: 70
- density_rhythm: 80 | ecological_believability: 45

**生态纹理评分**（生态后）: 78 ≥ 70 ✅（基于 texture_profiles.json 预配置）

---

## 文明层

| 指标 | 值 |
|------|-----|
| 聚落数 | 4 个（hamlet / village / town / fortress）|
| 道路段数 | 3 条（main_road / village_road / hunter_path）|
| 未连通聚落 | 0 ✅ |
| 道路最大长度 | 130 格 |
| 地标总数 | 4 个 |

**聚落分布**:
- 0 hamlet @ (76,149) — 近水 ✅
- 1 village @ (87,233) — 近水 ✅
- 2 town @ (100,78) — 近水 ✅
- 3 fortress @ (138,189) — 近水 ✅

**地标**:
- boss_arena @ (34,135) 东北山地 — has_boundary ✅
- ruin @ (208,125) 西南偏远地带
- ruin @ (30,128) 北部山脉
- resource_site @ (128,64) 西部森林

**文明时代评分**: overall = **66.8** ≥ 60 ✅
- settlement_terrain_fit: 60 | road_design: 65 | gameplay_space: 75
- visual_readability: 65 | landmark_exploration: 70 | traversability: 85
- settlement_connectivity: 75 | path_ratio: 20

**特殊纹理评分**: 跳过（y3_decal_id 未填写）

---

## 纹理评估汇总

| 时机 | 评分 | 状态 |
|------|------|------|
| 地形纹理（地质后） | 79.3 | ✅ 通过 |
| 地形纹理（生态后） | 78.0 | ✅ 通过 |
| 特殊纹理（文明后） | 跳过 | — |

**待修正纹理问题**（2 项）:
1. generate_terrain.py 未传入 --texture-profiles，texture_plan 字段缺失
2. y3_decal_id 未填写，特殊纹理叙事感无法验证

---

## 已知问题（验证器警告，非阻断）

1. 悬崖格子 26.5% 缺少相邻斜坡（大量 cliff_map>0 是脚本将几乎所有陆地标记为有台阶层级所致）
2. 存在孤立小水体（1格×4个、21格×1个、271格×1个）——BFS 修复陆地连通时产生的孤立水湖
3. forest/plain 群系植被密度偏低（Poisson 采样 + 大 footprint_cells 物理限制，配置目标已达 0.80/0.30）

---

## MCP 写入状态

**未执行**（用户选择跳过 MCP 写入）

如需写入，执行顺序：
```
Pass A: 地形骨架（Hill/Cliff/Crack/Water）→ 每批 100 格
Pass B: 纹理（200×200cm 单元格）
Pass C: 植被/斜坡/实体
```
