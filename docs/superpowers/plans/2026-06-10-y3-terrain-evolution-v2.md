# Y3 地形演化 v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 `y3-terrain-evolution` Skill 升级为 v2，新增 Voronoi 主题布局、fBm+Ridged+Domain Warping 噪声、A* 4-connectivity 道路（含 cliff cost）、生态时代 Three.js 视觉评分、分步 MCP 写入（Pass A/B/C）。

**Architecture:** 三层分离——数据层（Python 脚本生成 JSON）、预览层（Three.js 本地服务 + Claude vision）、写入层（MCP 分步 Pass）。现有脚本在原文件上修改，新增 `preview_server.py`、`visual_eval.py`、`static/viewer.html`。

**Tech Stack:** Python 3 (numpy, http.server, urllib), Three.js r160 (CDN), Claude API (anthropic SDK 或 urllib), pytest

**Spec:** `docs/superpowers/specs/2026-06-10-y3-terrain-evolution-v2-design.md`

**Base path:** `skills/y3-maker-config/skills/y3-terrain-evolution/`

---

## File Map

| 文件 | 操作 | 说明 |
|---|---|---|
| `config/world_config.json` | Modify | 256×256, theme, max_visual_iterations |
| `scripts/generate_terrain.py` | Modify | Voronoi + Ridged + Domain Warping；删除错误注释 |
| `scripts/analyze_terrain.py` | Modify | 新增 4 个摘要字段 |
| `scripts/generate_civilization.py` | Modify | A* 改 4-connectivity，加 cliff cost |
| `scripts/mcp_writer.py` | Modify | 新增 `--pass A\|B\|C`，分进度文件 |
| `scripts/check_deps.py` | Modify | 新增 anthropic 依赖检查 |
| `scripts/preview_server.py` | Create | Three.js HTTP 服务器 + /screenshot |
| `scripts/visual_eval.py` | Create | 截图 + Claude API 视觉评分 |
| `static/viewer.html` | Create | Three.js 俯视渲染页面 |
| `prompts/terrain_era_eval_prompt.md` | Modify | 新增 3 评分维度 |
| `prompts/civilization_era_eval_prompt.md` | Modify | 新增 3 评分维度 |
| `SKILL.md` | Modify | 更新至 v2 完整流程 |
| `tests/test_terrain_v2.py` | Create | 核心逻辑单元测试 |

---

## Task 1: 配置更新 + 删除错误注释

**Files:**
- Modify: `config/world_config.json`
- Modify: `scripts/generate_terrain.py:417` (删除 2 行注释)

- [ ] **Step 1: 更新 world_config.json**

将以下内容替换到 `config/world_config.json`：

```json
{
  "_comment": "Y3 地形演化配置文件 - 修改此文件后重新运行 Skill",

  "seed": 42,
  "map_width": 256,
  "map_height": 256,
  "theme": "forest_valley",

  "generation_rules": {
    "fbm_octaves": 6,
    "water_level": 0.32,
    "shallow_threshold": 0.06,
    "max_cliff_level": 5,
    "island_mode": false,

    "river_count": 3,
    "crack_count": 4,
    "crack_length": 25,

    "allow_cracks": true,
    "allow_slopes": true,

    "target_water_ratio": 0.25,
    "target_mountain_ratio": 0.20
  },

  "era_thresholds": {
    "terrain_advance_score": 70,
    "ecology_advance_score": 65,
    "civilization_advance_score": 60,
    "max_iterations_per_era": 8,
    "max_visual_iterations": 3
  },

  "mcp": {
    "server_url": "http://localhost:8765",
    "timeout_seconds": 300,
    "batch_size": 100
  }
}
```

- [ ] **Step 2: 删除 generate_terrain.py 中的错误注释**

在 `scripts/generate_terrain.py` 中找到并删除这两行（约第 417-418 行）：
```python
    # slope_map 标注出 cliff_map 中相邻高差=2的格子（引擎会在这些位置自动生成斜坡）
    # 仅作参考和评估输出，不参与 MCP 写入（terrain-adjacency-rules.md §5.2）
```
同时将函数调用从 `build_slope_map(cliff_map, water_map, gen)` 改为 `build_slope_map(cliff_map, water_map, gen_cfg)`（如参数名不一致则统一）。

- [ ] **Step 3: 验证配置可被读取**

```bash
cd skills/y3-maker-config/skills/y3-terrain-evolution
python -c "import json; c=json.load(open('config/world_config.json')); assert c['map_width']==256; assert c['theme']=='forest_valley'; assert c['era_thresholds']['max_visual_iterations']==3; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add skills/y3-maker-config/skills/y3-terrain-evolution/config/world_config.json \
        skills/y3-maker-config/skills/y3-terrain-evolution/scripts/generate_terrain.py
git commit -m "config: update world_config to 256x256 + theme + visual iterations; remove stale slope comment"
```

---

## Task 2: generate_terrain.py — Voronoi + 噪声升级

**Files:**
- Modify: `scripts/generate_terrain.py`
- Create: `tests/test_terrain_v2.py` (先写测试)

### 2A: 写测试（先失败）

- [ ] **Step 1: 创建测试文件**

创建 `tests/test_terrain_v2.py`：

```python
"""Tests for generate_terrain.py v2 additions."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import numpy as np
import pytest
from generate_terrain import (
    generate_voronoi_layout,
    generate_ridged_noise,
    apply_domain_warping,
    generate_fbm,
)


def test_voronoi_layout_returns_correct_shape():
    mask = generate_voronoi_layout("forest_valley", seed=42, W=64, H=64)
    assert mask.shape == (64, 64)
    assert mask.dtype == np.float64


def test_voronoi_layout_values_in_range():
    mask = generate_voronoi_layout("lake_plain", seed=1, W=32, H=32)
    assert mask.min() >= -1.0
    assert mask.max() <= 1.0


def test_voronoi_forest_valley_center_lower():
    """forest_valley: 中心比四周低（低地在中心）"""
    mask = generate_voronoi_layout("forest_valley", seed=42, W=64, H=64)
    center = mask[28:36, 28:36].mean()
    edge_top = mask[:5, :].mean()
    edge_bot = mask[-5:, :].mean()
    assert center < (edge_top + edge_bot) / 2


def test_ridged_noise_shape_and_range():
    noise = generate_ridged_noise(W=64, H=64, seed=42, octaves=4)
    assert noise.shape == (64, 64)
    assert noise.min() >= 0.0
    assert noise.max() <= 1.0


def test_domain_warping_changes_map():
    base = generate_fbm(64, 64, seed=42)
    warped = apply_domain_warping(64, 64, seed=42, octaves=4, base_scale=8)
    assert warped.shape == (64, 64)
    # Warped map must differ from base FBM by at least 1% of cells
    diff = np.abs(base - warped)
    assert diff.mean() > 0.01


def test_world_state_has_theme_and_layout_map(tmp_path):
    """End-to-end: generate_terrain writes theme + layout_map fields."""
    import json, subprocess
    config = {
        "seed": 1, "map_width": 32, "map_height": 32, "theme": "lake_plain",
        "generation_rules": {
            "fbm_octaves": 3, "water_level": 0.32, "shallow_threshold": 0.06,
            "max_cliff_level": 3, "island_mode": False,
            "river_count": 1, "crack_count": 1, "crack_length": 5,
            "allow_cracks": True, "allow_slopes": True,
            "target_water_ratio": 0.25, "target_mountain_ratio": 0.20,
        },
        "era_thresholds": {"terrain_advance_score": 70, "ecology_advance_score": 65,
                           "civilization_advance_score": 60, "max_iterations_per_era": 8,
                           "max_visual_iterations": 3},
        "mcp": {"server_url": "http://localhost:8765", "timeout_seconds": 300, "batch_size": 100}
    }
    cfg_path = tmp_path / "world_config.json"
    cfg_path.write_text(json.dumps(config))
    result = subprocess.run(
        [sys.executable, "scripts/generate_terrain.py",
         "--config", str(cfg_path), "--output-dir", str(tmp_path)],
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), '..')
    )
    assert result.returncode == 0, result.stderr
    ws = json.loads((tmp_path / "world_state.json").read_text())
    assert "theme" in ws
    assert ws["theme"] == "lake_plain"
    assert "layout_map" in ws
    assert len(ws["layout_map"]) == 32
```

- [ ] **Step 2: 运行测试，确认全部失败**

```bash
cd skills/y3-maker-config/skills/y3-terrain-evolution
python -m pytest tests/test_terrain_v2.py -v 2>&1 | head -40
```

Expected: `ImportError` 或 `FAILED`（函数不存在）

### 2B: 实现

- [ ] **Step 3: 在 generate_terrain.py 中新增 generate_voronoi_layout**

在 `generate_fbm` 函数之后插入：

```python
# ---------------------------------------------------------------------------
# Voronoi Macro Layout
# ---------------------------------------------------------------------------

_THEME_CONFIGS = {
    "forest_valley": {
        "mountain_weight": 0.8,   # 四周高
        "center_bias":    -0.4,   # 中心低地
        "water_weight":    0.3,
    },
    "lake_plain": {
        "mountain_weight": 0.2,
        "center_bias":     0.0,
        "water_weight":    0.6,
    },
    "mountain_village": {
        "mountain_weight": 0.9,
        "center_bias":     0.1,
        "water_weight":    0.2,
    },
    "swamp_ruins": {
        "mountain_weight": 0.1,
        "center_bias":    -0.3,
        "water_weight":    0.7,
    },
    "arctic_peak": {
        "mountain_weight": 1.0,
        "center_bias":     0.2,
        "water_weight":    0.15,
    },
}


def generate_voronoi_layout(theme: str, seed: int, W: int, H: int) -> np.ndarray:
    """生成 Voronoi 宏观布局 bias map，值域 [-1, 1]。
    正值 → 抬高该区域；负值 → 降低该区域。
    """
    cfg = _THEME_CONFIGS.get(theme, _THEME_CONFIGS["forest_valley"])
    rng = np.random.RandomState(seed + 1000)

    # 撒若干关键点：山脉点 + 低地点
    n_mountain = max(2, int(6 * cfg["mountain_weight"]))
    n_valley   = max(1, int(4 * (1 - cfg["mountain_weight"])))

    mountain_pts = [(rng.randint(0, H), rng.randint(0, W)) for _ in range(n_mountain)]
    valley_pts   = [(rng.randint(0, H), rng.randint(0, W)) for _ in range(n_valley)]

    Y, X = np.mgrid[0:H, 0:W].astype(np.float64)

    def min_dist(pts):
        if not pts:
            return np.full((H, W), np.inf)
        dists = np.stack([np.sqrt((Y - py)**2 + (X - px)**2) for py, px in pts])
        return dists.min(axis=0)

    d_mountain = min_dist(mountain_pts)
    d_valley   = min_dist(valley_pts)

    # 归一化
    def norm(arr):
        mn, mx = arr.min(), arr.max()
        return (arr - mn) / (mx - mn + 1e-8) if mx > mn else arr * 0

    # 靠近山脉点 → 正 bias，靠近低地点 → 负 bias
    mountain_bias = (1.0 - norm(d_mountain))      # 靠近山脉 → 高
    valley_bias   = -(1.0 - norm(d_valley))       # 靠近低地 → 低

    # 主题的中心 bias（部分主题中心低、部分中心高）
    cy, cx = H / 2.0, W / 2.0
    dist_center = np.sqrt(((Y - cy) / cy)**2 + ((X - cx) / cx)**2)
    center_bias = -norm(dist_center) * abs(cfg["center_bias"])
    if cfg["center_bias"] > 0:
        center_bias = -center_bias

    layout = (mountain_bias * 0.5 + valley_bias * 0.3 + center_bias * 0.2)

    # 归一化到 [-1, 1]
    mx = max(abs(layout.min()), abs(layout.max()), 1e-8)
    return (layout / mx).astype(np.float64)
```

- [ ] **Step 4: 新增 generate_ridged_noise**

```python
def generate_ridged_noise(W: int, H: int, seed: int, octaves: int = 4, base_scale: int = 8) -> np.ndarray:
    """Ridged Noise = 1 - |fBm|，生成锋利山脊。值域 [0, 1]。"""
    raw = generate_fbm(W, H, seed + 500, octaves=octaves, base_scale=base_scale)
    # 先将 raw 映射到 [-1, 1]
    raw2 = raw * 2.0 - 1.0
    ridged = 1.0 - np.abs(raw2)
    mn, mx = ridged.min(), ridged.max()
    if mx > mn:
        ridged = (ridged - mn) / (mx - mn)
    return ridged
```

- [ ] **Step 5: 新增 apply_domain_warping**

```python
def apply_domain_warping(W: int, H: int, seed: int, octaves: int = 4, base_scale: int = 8) -> np.ndarray:
    """Domain Warping：用两个 fBm 扰动采样坐标，再采样第三个 fBm。
    使山脉自然蜿蜒，避免规则方块感。值域 [0, 1]。
    """
    # 扰动向量场
    warp_x = generate_fbm(W, H, seed + 600, octaves=octaves, base_scale=base_scale)
    warp_y = generate_fbm(W, H, seed + 700, octaves=octaves, base_scale=base_scale)

    # 扰动强度（格子数）
    warp_strength = max(W, H) * 0.12
    warp_x = (warp_x - 0.5) * 2.0 * warp_strength
    warp_y = (warp_y - 0.5) * 2.0 * warp_strength

    # 扰动后的坐标
    Y, X = np.mgrid[0:H, 0:W].astype(np.float64)
    new_y = np.clip(Y + warp_y, 0, H - 1)
    new_x = np.clip(X + warp_x, 0, W - 1)

    # 从基础 fBm 采双线性插值
    base = generate_fbm(W, H, seed + 800, octaves=octaves, base_scale=base_scale)

    y0 = new_y.astype(int)
    x0 = new_x.astype(int)
    y1 = np.minimum(y0 + 1, H - 1)
    x1 = np.minimum(x0 + 1, W - 1)
    fy = new_y - y0
    fx = new_x - x0

    result = (base[y0, x0] * (1 - fy) * (1 - fx)
            + base[y0, x1] * (1 - fy) * fx
            + base[y1, x0] * fy * (1 - fx)
            + base[y1, x1] * fy * fx)

    mn, mx = result.min(), result.max()
    if mx > mn:
        result = (result - mn) / (mx - mn)
    return result
```

- [ ] **Step 6: 修改 main() 中的 hill_map 生成**

在 `main()` 中替换原来的 `hill_map = generate_fbm(...)` 那段：

```python
    theme = config.get("theme", "forest_valley")
    print(f"  [0/7] Voronoi 宏观布局（主题: {theme}）...")
    layout_mask = generate_voronoi_layout(theme, seed, W, H)

    print("  [1/7] fBm + Ridged + Domain Warping 高度图...")
    fbm_map    = generate_fbm(W, H, seed, octaves=gen.get("fbm_octaves", 6))
    ridged_map = generate_ridged_noise(W, H, seed, octaves=gen.get("fbm_octaves", 6))
    warped_map = apply_domain_warping(W, H, seed, octaves=gen.get("fbm_octaves", 6))
    # 叠加：fBm 主体 + Ridged 山脊 + Domain Warping 自然扭曲 + Voronoi 宏观偏置
    # 注意：spec 原公式为 fBm*0.5 + Ridged*0.3 + layout_bias*0.2，本实现将 Domain Warping
    # 作为独立第三项（权重 0.2），layout_mask 权重调整为 0.15，使总和接近 1.15（归一化由 apply_shaping 处理）
    hill_map = fbm_map * 0.5 + ridged_map * 0.3 + warped_map * 0.2
    # layout_bias 叠加（[-1,1] → 加权到 hill_map）
    hill_map = hill_map + layout_mask * 0.15
    hill_map = apply_shaping(hill_map, gen)
```

在 `world_state` dict 中新增 `"theme"` 和 `"layout_map"` 字段：

```python
    world_state = {
        ...（原有字段）...
        "theme":      theme,
        "layout_map": layout_mask,
    }
```

- [ ] **Step 7: 运行测试，确认全部通过**

```bash
cd skills/y3-maker-config/skills/y3-terrain-evolution
python -m pytest tests/test_terrain_v2.py -v
```

Expected: 全部 PASSED

- [ ] **Step 8: 快速烟雾测试（实际运行）**

```bash
python scripts/generate_terrain.py \
  --config config/world_config.json \
  --output-dir output/
python -c "import json; ws=json.load(open('output/world_state.json')); print('theme:', ws['theme']); print('width:', ws['width']); print('biomes:', list(set(sum(ws['biome_map'],[])))[:5])"
```

Expected: `theme: forest_valley`, `width: 256`

- [ ] **Step 9: Commit**

```bash
git add skills/y3-maker-config/skills/y3-terrain-evolution/scripts/generate_terrain.py \
        skills/y3-maker-config/skills/y3-terrain-evolution/tests/
git commit -m "feat(terrain): add Voronoi layout + Ridged Noise + Domain Warping"
```

---

## Task 3: analyze_terrain.py — 新增 4 个摘要字段

**Files:**
- Modify: `scripts/analyze_terrain.py`
- Modify: `tests/test_terrain_v2.py` (追加测试)

- [ ] **Step 1: 追加测试到 test_terrain_v2.py**

```python
from analyze_terrain import analyze_terrain_layer


def _make_ws(H=32, W=32, seed=42):
    """构造一个 minimal world_state dict 用于测试。"""
    from generate_terrain import generate_fbm, build_cliff_map, build_water_map, generate_rivers, generate_cracks, build_slope_map, classify_biomes
    gen = {"fbm_octaves": 3, "water_level": 0.32, "shallow_threshold": 0.06,
           "max_cliff_level": 3, "island_mode": False,
           "river_count": 1, "crack_count": 1, "crack_length": 5,
           "allow_cracks": True, "allow_slopes": True,
           "target_water_ratio": 0.25, "target_mountain_ratio": 0.20}
    hill = generate_fbm(W, H, seed)
    from generate_terrain import apply_shaping
    hill = apply_shaping(hill, gen)
    cliff = build_cliff_map(hill, gen)
    water = build_water_map(hill, gen)
    _, water = generate_rivers(hill, water, gen, seed)
    crack = generate_cracks(hill, water, gen, seed)
    slope = build_slope_map(cliff, water, gen)
    biome = classify_biomes(hill, water, cliff, gen)
    return {
        "width": W, "height": H, "seed": seed, "era": "terrain", "iteration": 0,
        "hill_map": hill.tolist(), "cliff_map": cliff.tolist(),
        "water_map": water.tolist(), "slope_map": slope.tolist(),
        "crack_map": crack.tolist(), "biome_map": biome.tolist(),
    }


def test_analyze_has_mountain_chain_count():
    ws = _make_ws()
    summary = analyze_terrain_layer(ws)
    assert "mountain_chain_count" in summary
    assert isinstance(summary["mountain_chain_count"], int)
    assert summary["mountain_chain_count"] >= 0


def test_analyze_has_mountain_chain_avg_length():
    ws = _make_ws()
    summary = analyze_terrain_layer(ws)
    assert "mountain_chain_avg_length" in summary
    assert summary["mountain_chain_avg_length"] >= 0.0


def test_analyze_has_river_validity_ratio():
    ws = _make_ws()
    summary = analyze_terrain_layer(ws)
    assert "river_validity_ratio" in summary
    r = summary["river_validity_ratio"]
    assert 0.0 <= r <= 1.0


def test_analyze_has_coastal_avg_width():
    ws = _make_ws()
    summary = analyze_terrain_layer(ws)
    assert "coastal_avg_width" in summary
    assert summary["coastal_avg_width"] >= 0.0
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python -m pytest tests/test_terrain_v2.py::test_analyze_has_mountain_chain_count -v
```

Expected: FAILED (KeyError)

- [ ] **Step 3: 在 analyze_terrain.py 的 analyze_terrain_layer 函数中新增 4 个字段**

在 `return {...}` 之前添加（在 `issues` 列表计算之后）：

```python
    # ----- 新增字段：山脉连通链 -----
    mountain_mask = (biome_map == "mountain") | (biome_map == "hill")
    if mountain_mask.any():
        labeled_m = _label_connected(mountain_mask)
        unique_m, counts_m = np.unique(labeled_m[labeled_m > 0], return_counts=True)
        # 只统计长度 >= 3 的链（过滤单点噪声）
        chains = counts_m[counts_m >= 3]
        mountain_chain_count   = int(len(chains))
        mountain_chain_avg_len = float(chains.mean()) if len(chains) > 0 else 0.0
    else:
        mountain_chain_count   = 0
        mountain_chain_avg_len = 0.0

    # ----- 新增字段：河流合法性（river_validity_ratio）-----
    # river_map 格子（shallow water 且在高度 > water_level 的区域）是否从高到低流
    # 近似：检查 shallow_water 格子中，hill_map 值是否低于邻居均值（下坡方向）
    river_mask = (water_map == "shallow")
    if river_mask.sum() > 0:
        valid_river = 0
        total_river = 0
        for ry in range(h):
            for rx in range(w):
                if not river_mask[ry, rx]:
                    continue
                total_river += 1
                neighbors = []
                for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
                    ny, nx = ry+dy, rx+dx
                    if 0 <= ny < h and 0 <= nx < w:
                        neighbors.append(hill_map[ny, nx])
                if neighbors and hill_map[ry, rx] <= max(neighbors):
                    valid_river += 1
        river_validity_ratio = valid_river / total_river if total_river > 0 else 1.0
    else:
        river_validity_ratio = 1.0

    # ----- 新增字段：水岸平均宽度（coastal_avg_width）-----
    # coastal biome 的连通区域平均大小（格子数），代表水岸过渡带宽度
    coastal_mask = (biome_map == "coastal")
    if coastal_mask.any():
        labeled_c = _label_connected(coastal_mask)
        _, counts_c = np.unique(labeled_c[labeled_c > 0], return_counts=True)
        coastal_avg_width = float(counts_c.mean()) if len(counts_c) > 0 else 0.0
    else:
        coastal_avg_width = 0.0
```

在 `return {` 中追加字段：

```python
        "mountain_chain_count":    mountain_chain_count,
        "mountain_chain_avg_length": mountain_chain_avg_len,
        "river_validity_ratio":    round(river_validity_ratio, 3),
        "coastal_avg_width":       round(coastal_avg_width, 1),
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
python -m pytest tests/test_terrain_v2.py -k "analyze" -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add skills/y3-maker-config/skills/y3-terrain-evolution/scripts/analyze_terrain.py \
        skills/y3-maker-config/skills/y3-terrain-evolution/tests/test_terrain_v2.py
git commit -m "feat(analyze): add mountain_chain, river_validity, coastal_width metrics"
```

---

## Task 4: generate_civilization.py — A* 改 4-connectivity + cliff cost

**Files:**
- Modify: `scripts/generate_civilization.py`
- Modify: `tests/test_terrain_v2.py` (追加测试)

- [ ] **Step 1: 追加测试**

```python
from generate_civilization import astar_road


def test_astar_4connectivity_no_diagonal():
    """A* 不走对角线——路径中相邻两格的行或列差必须为 0。"""
    H, W = 20, 20
    passable = np.ones((H, W), dtype=bool)
    cost_map = np.ones((H, W), dtype=np.float64)
    path = astar_road((0, 0), (5, 5), passable, cost_map, H, W)
    assert path is not None
    for (y1, x1), (y2, x2) in zip(path[:-1], path[1:]):
        # 4-connectivity: 行差 + 列差必须等于 1（不能同时非零）
        assert abs(y2 - y1) + abs(x2 - x1) == 1, f"Diagonal move: ({y1},{x1})->({y2},{x2})"


def test_astar_avoids_high_cliff_cost():
    """A* 应绕过 cliff 差值 ≥ 2 的格子（高 cost）。"""
    H, W = 10, 10
    passable = np.ones((H, W), dtype=bool)
    cost_map = np.ones((H, W), dtype=np.float64)
    # 在直线路径上放高 cost 墙（列 5，全行）
    cost_map[:, 5] = 1000.0
    path = astar_road((0, 0), (0, 9), passable, cost_map, H, W)
    assert path is not None
    # 路径不应包含 col=5（太贵，应绕行）
    cols_in_path = [x for _, x in path]
    assert 5 not in cols_in_path
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python -m pytest tests/test_terrain_v2.py::test_astar_4connectivity_no_diagonal -v
```

Expected: FAILED（当前 A* 使用 8 方向）

- [ ] **Step 3: 修改 astar_road 函数签名和内部实现**

将 `generate_civilization.py` 中的 `astar_road` 替换为：

```python
def astar_road(start, goal, passable, cost_map, H, W):
    """A* 寻路（4-connectivity），使用 cost_map 确定移动代价。

    Args:
        start: (y, x) 起点
        goal:  (y, x) 终点
        passable: bool 矩阵，False = 不可通行（water = inf cost）
        cost_map: float 矩阵，移动进入该格的代价（cliff 差值越大越高）
        H, W: 地图尺寸
    Returns:
        [(y,x), ...] 路径，或 None（无法到达）
    """
    if not passable[start[0], start[1]] or not passable[goal[0], goal[1]]:
        return None

    def h(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    open_set = [(h(start, goal), 0.0, start)]
    came_from = {}
    g = {start: 0.0}

    # 严格 4-connectivity（上下左右），不允许对角线
    DIRS = ((-1, 0), (1, 0), (0, -1), (0, 1))

    while open_set:
        _, cost, cur = heapq.heappop(open_set)
        if cur == goal:
            path = []
            while cur in came_from:
                path.append(cur)
                cur = came_from[cur]
            path.append(start)
            return path[::-1]
        for dy, dx in DIRS:
            ny, nx = cur[0] + dy, cur[1] + dx
            nb = (ny, nx)
            if not (0 <= ny < H and 0 <= nx < W):
                continue
            if not passable[ny, nx]:
                continue
            move_cost = cost_map[ny, nx]
            ng = g[cur] + move_cost
            if ng < g.get(nb, 1e18):
                came_from[nb] = cur
                g[nb] = ng
                heapq.heappush(open_set, (ng + h(nb, goal), ng, nb))
    return None
```

- [ ] **Step 4: 修改 generate_roads，传入 cliff cost map**

将 `generate_roads` 函数替换为：

```python
def generate_roads(settlements, ws):
    H, W = ws["height"], ws["width"]
    water = np.array(ws["water_map"], dtype=object)
    cliff = np.array(ws["cliff_map"], dtype=np.int32)

    # 可行走矩阵（所有水域不可通行，含 deep/shallow/plain）
    passable = (water == "none")

    # cliff cost map：相邻格差值越大代价越高
    # 我们用格子自身 cliff level 作为进入代价的代理
    # 实际道路评分中，跨 cliff diff ≥ 2 会被标记为 traversability 问题
    cost_map = np.ones((H, W), dtype=np.float64)
    for y in range(H):
        for x in range(W):
            max_diff = 0
            for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
                ny, nx = y+dy, x+dx
                if 0 <= ny < H and 0 <= nx < W:
                    diff = abs(int(cliff[y, x]) - int(cliff[ny, nx]))
                    max_diff = max(max_diff, diff)
            if max_diff >= 2:
                cost_map[y, x] = 100.0   # 极高代价（悬崖边界，不可通行）
            elif max_diff == 1:
                cost_map[y, x] = 5.0     # 中等代价（斜坡区）
            # else: 1.0（平地）
        # 水域不可通行
        for x in range(W):
            if water[y, x] != "none":
                cost_map[y, x] = 1e9

    roads = []
    road_cells = set()
    unconnected = 0

    pairs = []
    for i, s1 in enumerate(settlements):
        for j, s2 in enumerate(settlements):
            if i >= j: continue
            dist = abs(s1["grid_y"]-s2["grid_y"]) + abs(s1["grid_x"]-s2["grid_x"])
            pairs.append((dist, i, j))
    pairs.sort()

    connected = {i: False for i in range(len(settlements))}
    if settlements:
        connected[0] = True

    for dist, i, j in pairs:
        if connected[i] and connected[j]:
            continue
        s1, s2 = settlements[i], settlements[j]
        # 已有道路的格子 cost 减半（鼓励共线）
        cm = cost_map.copy()
        for ry, rx in road_cells:
            cm[ry, rx] = max(0.5, cm[ry, rx] * 0.5)

        path = astar_road(
            (s1["grid_y"], s1["grid_x"]),
            (s2["grid_y"], s2["grid_x"]),
            passable, cm, H, W
        )
        if path:
            roads.append({
                "from":     i,
                "to":       j,
                "length":   len(path),
                "passable": True,
                "cells":    [(y, x) for y, x in path],
            })
            for y, x in path:
                road_cells.add((y, x))
            connected[i] = True
            connected[j] = True
        else:
            unconnected += 1

    return roads, unconnected, road_cells
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
python -m pytest tests/test_terrain_v2.py -k "astar" -v
```

Expected: 2 PASSED

- [ ] **Step 6: Commit**

```bash
git add skills/y3-maker-config/skills/y3-terrain-evolution/scripts/generate_civilization.py \
        skills/y3-maker-config/skills/y3-terrain-evolution/tests/test_terrain_v2.py
git commit -m "feat(civilization): A* 4-connectivity + cliff cost map for road generation"
```

---

## Task 5: mcp_writer.py — --pass A/B/C

**Files:**
- Modify: `scripts/mcp_writer.py`
- Modify: `tests/test_terrain_v2.py` (追加测试)

- [ ] **Step 1: 追加测试**

```python
# 测试 Pass 分组是否正确（不需要真正写 MCP）
def test_pass_a_contains_only_terrain_passes():
    """Pass A: hill_lift, cliff_height, crack, deep_water, shallow_water, plain_water"""
    from mcp_writer import PASS_A, PASS_B, PASS_C, PASS_NAMES
    assert set(PASS_A) == {"hill_lift", "cliff_height", "crack", "deep_water", "shallow_water", "plain_water"}
    assert set(PASS_B) == {"textures"}
    assert set(PASS_C) == {"vegetation", "slopes", "entities"}
    # 顺序：vegetation → slopes → entities（Y3 约束：斜坡必须在植被之后写入）
    assert PASS_C.index("vegetation") < PASS_C.index("slopes")
    assert PASS_C.index("slopes") < PASS_C.index("entities")
    # 总覆盖所有 PASS_NAMES
    assert set(PASS_A) | set(PASS_B) | set(PASS_C) == set(PASS_NAMES)


def test_pass_progress_files_are_independent(tmp_path):
    """每个 Pass 的进度文件互相独立。"""
    from mcp_writer import get_progress_file
    assert "A" in get_progress_file("A", str(tmp_path))
    assert "B" in get_progress_file("B", str(tmp_path))
    assert get_progress_file("A", str(tmp_path)) != get_progress_file("B", str(tmp_path))
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python -m pytest tests/test_terrain_v2.py::test_pass_a_contains_only_terrain_passes -v
```

Expected: FAILED (ImportError)

- [ ] **Step 3: 在 mcp_writer.py 顶部新增 Pass 分组常量和 get_progress_file 函数**

在 `PASS_NAMES` 列表之后插入：

```python
# ---------------------------------------------------------------------------
# Pass A/B/C 分组（用于 --pass 参数分步写入）
# ---------------------------------------------------------------------------
PASS_A = [
    "hill_lift",     # terrain_hill_lift_block
    "cliff_height",  # terrain_set_height_block
    "crack",         # terrain_set_crack_block
    "deep_water",    # terrain_set_deep_water_block
    "shallow_water", # terrain_set_shallow_water_block
    "plain_water",   # terrain_set_plain_water_block
]
PASS_B = [
    "textures",      # terrain_cover_draw_block
]
PASS_C = [
    "vegetation",    # terrain_vegetation_draw_block
    "slopes",        # terrain_set_road_block（必须在 vegetation 之后，entity 之前）
    "entities",      # entity_create_block
]
PASS_GROUP = {"A": PASS_A, "B": PASS_B, "C": PASS_C}


def get_progress_file(pass_letter: str, output_dir: str) -> str:
    """每个 Pass 独立进度文件，--restart 只清当前 Pass 进度。"""
    return str(Path(output_dir) / f".mcp_progress_{pass_letter}.json")
```

将原来的 `PROGRESS_FILE = "output/.mcp_progress.json"` 保留（全量模式兼容），新增的 `get_progress_file` 用于 `--pass` 模式。

- [ ] **Step 4: 在 main() 的 argparse 中新增 --pass 参数**

```python
parser.add_argument("--pass", dest="pass_letter", choices=["A", "B", "C"],
                    default=None,
                    help="分步写入模式：A=地形骨架, B=纹理, C=装饰物+斜坡")
```

在 main() 执行逻辑中，在 load passes 之前插入：

```python
    # 确定要执行的 pass 列表
    if args.pass_letter:
        active_passes = PASS_GROUP[args.pass_letter]
        progress_file = get_progress_file(args.pass_letter, output_dir)
    else:
        active_passes = PASS_NAMES  # 全量模式（无 --pass）
        progress_file = PROGRESS_FILE
```

将原来代码中对 `PROGRESS_FILE` 的引用替换为 `progress_file`，对 `PASS_NAMES` 的迭代替换为 `active_passes`。

- [ ] **Step 5: 运行测试，确认通过**

```bash
python -m pytest tests/test_terrain_v2.py -k "pass" -v
```

Expected: 2 PASSED

- [ ] **Step 6: Commit**

```bash
git add skills/y3-maker-config/skills/y3-terrain-evolution/scripts/mcp_writer.py \
        skills/y3-maker-config/skills/y3-terrain-evolution/tests/test_terrain_v2.py
git commit -m "feat(mcp_writer): add --pass A/B/C split mode with independent progress files"
```

---

## Task 6: preview_server.py + static/viewer.html

**Files:**
- Create: `scripts/preview_server.py`
- Create: `static/viewer.html`

- [ ] **Step 1: 创建 static/viewer.html**

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Y3 地形预览</title>
<style>
  body { margin: 0; background: #111; color: #eee; font-family: monospace; }
  #info { position: absolute; top: 10px; left: 10px; z-index: 10; font-size: 12px; }
  #era-select { margin: 4px 0; }
  canvas { display: block; }
</style>
</head>
<body>
<div id="info">
  <div>Y3 地形预览</div>
  <select id="era-select">
    <option value="terrain">地质时代</option>
    <option value="ecology" selected>生态时代</option>
    <option value="civilization">文明时代</option>
  </select>
  <div id="stats"></div>
  <button id="screenshot-btn" style="margin-top:6px">截图（/screenshot）</button>
</div>
<script type="importmap">
  {"imports": {"three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"}}
</script>
<script type="module">
import * as THREE from 'three';

// biome 颜色映射
const BIOME_COLOR = {
  mountain: 0x888888,
  cliff:    0x666655,
  hill:     0x4a7a30,
  forest:   0x2d6a1f,
  plain:    0x7ab648,
  wetland:  0x5a7a3a,
  coastal:  0xc8a86a,
  water:    0x2255aa,
};

const W_DEFAULT = 256, H_DEFAULT = 256;
let scene, camera, renderer, mesh;

function init() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x111111);
  renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  document.body.appendChild(renderer.domElement);

  // 俯视摄像机（45° 斜视）
  camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 10000);
  camera.position.set(0, 400, 300);
  camera.lookAt(0, 0, 0);

  const ambient = new THREE.AmbientLight(0xffffff, 0.8);
  scene.add(ambient);
  const sun = new THREE.DirectionalLight(0xffffff, 1.2);
  sun.position.set(200, 400, 200);
  scene.add(sun);

  loadAndRender();
  renderer.setAnimationLoop(() => renderer.render(scene, camera));
}

async function loadAndRender() {
  const [ws, eco, civ] = await Promise.all([
    fetch('/world_state').then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/ecology').then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/civilization').then(r => r.ok ? r.json() : null).catch(() => null),
  ]);
  if (!ws) { document.getElementById('stats').textContent = '⚠️ 无数据，先运行 generate_terrain.py'; return; }

  const H = ws.height, W = ws.width;
  document.getElementById('stats').textContent = `${W}×${H} | theme: ${ws.theme || '?'}`;

  const hill  = ws.hill_map;
  const biome = ws.biome_map;

  // 构建 PlaneGeometry（X=列, Z=行）
  if (mesh) scene.remove(mesh);
  const geo = new THREE.PlaneGeometry(W * 2, H * 2, W - 1, H - 1);
  geo.rotateX(-Math.PI / 2);
  const pos = geo.attributes.position;
  const colors = [];

  for (let row = 0; row < H; row++) {
    for (let col = 0; col < W; col++) {
      const idx = row * W + col;
      const h = hill[row][col];
      pos.setY(idx, h * 80);  // 高度放大系数

      const bm = biome[row][col];
      const c = new THREE.Color(BIOME_COLOR[bm] || 0x888888);
      colors.push(c.r, c.g, c.b);
    }
  }
  geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  geo.computeVertexNormals();

  const mat = new THREE.MeshLambertMaterial({ vertexColors: true });
  mesh = new THREE.Mesh(geo, mat);
  scene.add(mesh);

  // 文明层：道路（黄色线）和聚落（红点）
  if (civ && civ.road_cells) {
    const roadGeo = new THREE.BufferGeometry();
    const roadPts = [];
    for (const [row, col] of civ.road_cells) {
      const h = hill[row][col];
      roadPts.push(col * 2 - W, h * 80 + 2, row * 2 - H);
    }
    roadGeo.setAttribute('position', new THREE.Float32BufferAttribute(roadPts, 3));
    const roadMat = new THREE.PointsMaterial({ color: 0xffdd00, size: 3 });
    scene.add(new THREE.Points(roadGeo, roadMat));
  }
  if (civ && civ.settlements) {
    for (const s of civ.settlements) {
      const h = hill[s.grid_y][s.grid_x];
      const sGeo = new THREE.SphereGeometry(4, 8, 8);
      const sMat = new THREE.MeshBasicMaterial({ color: 0xff4422 });
      const sMesh = new THREE.Mesh(sGeo, sMat);
      sMesh.position.set(s.grid_x * 2 - W, h * 80 + 6, s.grid_y * 2 - H);
      scene.add(sMesh);
    }
  }
}

// 截图接口
document.getElementById('screenshot-btn').addEventListener('click', async () => {
  const data = renderer.domElement.toDataURL('image/png');
  await fetch('/screenshot', { method: 'POST', body: JSON.stringify({ image: data }),
    headers: { 'Content-Type': 'application/json' }});
  alert('截图已保存到服务器');
});

// 窗口 resize
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

init();
</script>
</body>
</html>
```

- [ ] **Step 2: 创建 scripts/preview_server.py**

```python
#!/usr/bin/env python3
"""
Y3 地形预览服务器

提供 Three.js 俯视渲染页面 + /screenshot 截图接口。
生命周期：
  - 首次启动记录 PID 到 output/preview_server.pid
  - visual_eval.py 调用前检查端口是否已占用（已占用则复用）
  - Skill 运行结束后不主动关闭（供用户在浏览器预览）

用法：
  python scripts/preview_server.py [--port 9876] [--output-dir output/]
  python scripts/preview_server.py --background --port 9876  # 后台运行
"""

import argparse
import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


SCRIPT_DIR   = Path(__file__).parent
SKILL_DIR    = SCRIPT_DIR.parent
STATIC_DIR   = SKILL_DIR / "static"
DEFAULT_PORT = 9876


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


class TerrainHandler(BaseHTTPRequestHandler):
    output_dir: Path = Path("output")
    _last_screenshot_b64: str = ""

    def log_message(self, fmt, *args):
        pass  # 静默日志

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_file(STATIC_DIR / "viewer.html", "text/html")
        elif self.path == "/world_state":
            self._serve_json(TerrainHandler.output_dir / "world_state.json")
        elif self.path == "/ecology":
            self._serve_json(TerrainHandler.output_dir / "ecology_layer.json")
        elif self.path == "/civilization":
            self._serve_json(TerrainHandler.output_dir / "civilization_layer.json")
        elif self.path == "/last_screenshot":
            # visual_eval.py 通过此端点获取浏览器最新截图
            resp = json.dumps({"image": TerrainHandler._last_screenshot_b64}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/screenshot":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            data   = json.loads(body)
            # data["image"] = "data:image/png;base64,..."
            b64 = data.get("image", "")
            TerrainHandler._last_screenshot_b64 = b64
            # 保存到文件
            if b64.startswith("data:image/png;base64,"):
                import base64
                raw = base64.b64decode(b64.split(",", 1)[1])
                out_path = TerrainHandler.output_dir / "preview_screenshot.png"
                out_path.write_bytes(raw)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_file(self, path: Path, content_type: str):
        if not path.exists():
            self.send_response(404)
            self.end_headers()
            return
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_json(self, path: Path):
        if not path.exists():
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'null')
            return
        self._serve_file(path, "application/json")


def run_server(port: int, output_dir: Path):
    TerrainHandler.output_dir = output_dir
    httpd = HTTPServer(("localhost", port), TerrainHandler)
    print(f"[preview_server] 启动 http://localhost:{port}  (output: {output_dir})", flush=True)
    httpd.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",       type=int, default=DEFAULT_PORT)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--background", action="store_true", help="后台线程运行（仅供测试，生产用 & 或 nohup）")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 记录 PID
    pid_file = output_dir / "preview_server.pid"
    pid_file.write_text(str(os.getpid()))

    if args.background:
        t = threading.Thread(target=run_server, args=(args.port, output_dir), daemon=True)
        t.start()
        print(f"[preview_server] 后台运行 PID={os.getpid()}", flush=True)
        # 阻塞主线程（daemon 线程会随主线程退出）
        try:
            t.join()
        except KeyboardInterrupt:
            pass
    else:
        run_server(args.port, output_dir)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 冒烟测试（手动，不自动化）**

```bash
cd skills/y3-maker-config/skills/y3-terrain-evolution
# 先生成数据
python scripts/generate_terrain.py --config config/world_config.json --output-dir output/
# 启动服务（前台，另开终端）
python scripts/preview_server.py --port 9876
# 浏览器访问 http://localhost:9876 应显示 Three.js 地形
```

- [ ] **Step 4: Commit**

```bash
git add skills/y3-maker-config/skills/y3-terrain-evolution/scripts/preview_server.py \
        skills/y3-maker-config/skills/y3-terrain-evolution/static/viewer.html
git commit -m "feat(preview): add Three.js preview server + biome-colored terrain viewer"
```

---

## Task 7: visual_eval.py + check_deps.py 更新

**Files:**
- Create: `scripts/visual_eval.py`
- Modify: `scripts/check_deps.py`
- Modify: `tests/test_terrain_v2.py` (追加测试)

- [ ] **Step 1: 更新 check_deps.py，新增 anthropic 依赖检查**

```python
REQUIRED = {"numpy": "numpy", "anthropic": "anthropic"}
```

- [ ] **Step 2: 追加测试（mock Claude API）**

```python
def test_visual_eval_output_schema(tmp_path, monkeypatch):
    """visual_eval.py 输出必须包含 overall, dimensions, issues, suggestions, ready_to_advance。"""
    import json, importlib

    # mock: 不启动真实服务器，不调用真实 Claude API
    def fake_take_screenshot(port):
        return "data:image/png;base64,iVBORw0KGgo="  # 1px png

    def fake_call_claude_vision(image_b64, prompt, api_key):
        return json.dumps({
            "era": "ecology",
            "overall": 75,
            "dimensions": {
                "composition": 78, "biome_contrast": 72,
                "biome_transition": 71, "density_rhythm": 76, "naturalness": 78
            },
            "issues": [],
            "suggestions": [],
            "ready_to_advance": True
        })

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
    import visual_eval
    monkeypatch.setattr(visual_eval, "take_screenshot", fake_take_screenshot)
    monkeypatch.setattr(visual_eval, "call_claude_vision", fake_call_claude_vision)

    output_file = tmp_path / "visual_eval_ecology.json"
    visual_eval.run_visual_eval(
        era="ecology",
        world_state_path=None,
        ecology_path=None,
        output_path=str(output_file),
        port=9876,
        api_key="test"
    )
    result = json.loads(output_file.read_text())
    assert "overall" in result
    assert "dimensions" in result
    assert "issues" in result
    assert "suggestions" in result
    assert "ready_to_advance" in result
    assert isinstance(result["overall"], (int, float))
```

- [ ] **Step 3: 创建 scripts/visual_eval.py**

```python
#!/usr/bin/env python3
"""
Y3 视觉评分器

流程：
1. 检查 preview_server 是否运行（端口 9876），未运行则启动
2. POST /screenshot → base64 PNG
3. 调用 Claude API (claude-sonnet-4-6, vision)
4. 保存评分结果到 output/visual_eval_ecology.json

用法：
  python scripts/visual_eval.py \
    --era ecology \
    --world-state output/world_state.json \
    --ecology output/ecology_layer.json \
    --output output/visual_eval_ecology.json \
    [--port 9876] \
    [--api-key <ANTHROPIC_API_KEY>]
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR  = SCRIPT_DIR.parent


# ---------------------------------------------------------------------------
# 截图
# ---------------------------------------------------------------------------

def is_server_running(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def ensure_server(port: int, output_dir: str):
    if is_server_running(port):
        print(f"[visual_eval] 复用已有预览服务器 (port={port})")
        return
    print(f"[visual_eval] 启动预览服务器 (port={port})...")
    subprocess.Popen(
        [sys.executable, str(SCRIPT_DIR / "preview_server.py"),
         "--port", str(port), "--output-dir", output_dir],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    # 等待服务器就绪（最多 5 秒）
    for _ in range(10):
        time.sleep(0.5)
        if is_server_running(port):
            break
    else:
        raise RuntimeError(f"预览服务器未能在 5 秒内启动（port={port}）")


def take_screenshot(port: int) -> str:
    """触发浏览器端截图并返回 base64 PNG 字符串。
    注意：这里采用服务器端轮询方式——等待浏览器 POST /screenshot。
    如无浏览器打开，改为生成一个纯色占位图。
    """
    # 尝试从服务器获取上次截图（浏览器已截图的情况）
    try:
        req = urllib.request.Request(f"http://localhost:{port}/last_screenshot")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            if data.get("image"):
                return data["image"]
    except Exception:
        pass
    # 生成占位图（1×1 白色 PNG，base64）
    return (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI6QAAAABJRU5ErkJggg=="
    )


# ---------------------------------------------------------------------------
# Claude API 调用
# ---------------------------------------------------------------------------

EVAL_PROMPT_TEMPLATE = """你是专业的游戏地形美术评审专家。
请根据以下 Y3 游戏地图的俯视渲染图，从审美角度评估地形质量。

评估时代：{era}
关键统计数据（供参考）：
{stats_json}

请从以下 5 个维度评分（0-100），并给出问题列表和修改建议：
- composition：整体构图，是否有视觉焦点（高山/水域/特色区域）
- biome_contrast：生物群系颜色对比是否明确（不同区域颜色是否可辨识）
- biome_transition：群系过渡是否自然（无硬切边界，有渐变感）
- density_rhythm：植被/模型疏密是否有节奏感（疏密对比，避免均匀铺满）
- naturalness：整体是否看起来自然（非人工噪声感）

⚠️ 严格输出 JSON，不输出任何其他文字：
{{
  "era": "{era}",
  "overall": <加权平均，composition*0.25+biome_contrast*0.25+biome_transition*0.20+density_rhythm*0.15+naturalness*0.15>,
  "dimensions": {{
    "composition": 0-100,
    "biome_contrast": 0-100,
    "biome_transition": 0-100,
    "density_rhythm": 0-100,
    "naturalness": 0-100
  }},
  "issues": ["问题1", "问题2"],
  "suggestions": ["建议1", "建议2"],
  "ready_to_advance": true/false
}}
ready_to_advance = true 当且仅当 overall >= 65。
"""


def call_claude_vision(image_b64: str, prompt: str, api_key: str) -> str:
    """调用 Claude API（vision），返回 response text。"""
    if not api_key:
        raise ValueError("未提供 ANTHROPIC_API_KEY，无法调用 Claude API")

    import urllib.parse

    # 提取纯 base64（去掉 data:image/png;base64, 前缀）
    if image_b64.startswith("data:"):
        media_type = image_b64.split(";")[0].split(":")[1]  # image/png
        b64_data   = image_b64.split(",", 1)[1]
    else:
        media_type = "image/png"
        b64_data   = image_b64

    payload = {
        "model":      "claude-sonnet-4-6",
        "max_tokens": 1024,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type":   "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64_data},
                },
                {"type": "text", "text": prompt},
            ],
        }],
    }
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    return result["content"][0]["text"]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_visual_eval(era: str, world_state_path, ecology_path, output_path: str,
                    port: int = 9876, api_key: str = ""):
    # 构建统计摘要（供 prompt 参考）
    stats = {}
    if world_state_path and Path(world_state_path).exists():
        ws = json.loads(Path(world_state_path).read_text())
        stats["theme"]       = ws.get("theme", "?")
        stats["water_pct"]   = "~"  # 简化，实际可从 analyze_terrain 读
    if ecology_path and Path(ecology_path).exists():
        eco = json.loads(Path(ecology_path).read_text())
        stats["total_entities"] = eco.get("total_entities", "?")

    prompt = EVAL_PROMPT_TEMPLATE.format(
        era=era,
        stats_json=json.dumps(stats, ensure_ascii=False, indent=2)
    )

    # 截图
    print(f"[visual_eval] 获取截图...")
    image_b64 = take_screenshot(port)

    # 调用 Claude
    print(f"[visual_eval] 调用 Claude API 视觉评分...")
    response_text = call_claude_vision(image_b64, prompt, api_key)

    # 解析 JSON（Claude 可能在 JSON 外有额外文字，提取 {...}）
    start = response_text.find("{")
    end   = response_text.rfind("}") + 1
    result = json.loads(response_text[start:end]) if start >= 0 else {}

    # 保存
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[visual_eval] 评分完成 → {output_path}")
    print(f"  overall: {result.get('overall', '?')} | ready: {result.get('ready_to_advance', '?')}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--era",         default="ecology")
    parser.add_argument("--world-state", default="output/world_state.json")
    parser.add_argument("--ecology",     default="output/ecology_layer.json")
    parser.add_argument("--output",      default="output/visual_eval_ecology.json")
    parser.add_argument("--port",        type=int, default=9876)
    parser.add_argument("--output-dir",  default="output")
    parser.add_argument("--api-key",     default=os.environ.get("ANTHROPIC_API_KEY", ""))
    args = parser.parse_args()

    ensure_server(args.port, args.output_dir)
    run_visual_eval(
        era=args.era,
        world_state_path=args.world_state,
        ecology_path=args.ecology,
        output_path=args.output,
        port=args.port,
        api_key=args.api_key,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/test_terrain_v2.py::test_visual_eval_output_schema -v
```

Expected: PASSED

- [ ] **Step 5: Commit**

```bash
git add skills/y3-maker-config/skills/y3-terrain-evolution/scripts/visual_eval.py \
        skills/y3-maker-config/skills/y3-terrain-evolution/scripts/check_deps.py \
        skills/y3-maker-config/skills/y3-terrain-evolution/tests/test_terrain_v2.py
git commit -m "feat(visual_eval): add Claude vision scoring + preview server lifecycle management"
```

---

## Task 8: Prompt 更新（新增评分维度）

**Files:**
- Modify: `prompts/terrain_era_eval_prompt.md`
- Modify: `prompts/civilization_era_eval_prompt.md`

- [ ] **Step 1: 更新 terrain_era_eval_prompt.md**

在「输入格式」的 JSON 示例中，在 `"land_connectivity"` 之后添加新字段：

```json
  "mountain_chain_count": 3,
  "mountain_chain_avg_length": 28.5,
  "river_validity_ratio": 0.87,
  "coastal_avg_width": 4.2
```

在「评分标准」的 overall 加权公式之前，新增三个维度的评分说明：

```markdown
### mountain_linearity（山脉连绵走势）0-100

评估山体是否形成连绵走势，而非孤立噪声凸起。

| 条件 | 分值 |
|------|------|
| mountain_chain_count <= 3（山脉集中） | +30 |
| mountain_chain_avg_length >= 20（山脊足够长） | +40 |
| mountain_chain_count > 8（山脉碎裂成孤点） | -30 |
| mountain_chain_avg_length < 8（山脊过短，噪声感强） | -25 |

### river_validity（河流合法性）0-100

评估河流是否合理地从高处流向低处。

| 条件 | 分值 |
|------|------|
| river_validity_ratio >= 0.85（绝大多数河流格子下坡） | +60 |
| river_validity_ratio >= 0.70 | +30 |
| river_validity_ratio < 0.50（大量河流格子上坡，不自然） | -30 |

### water_bank_transition（水岸过渡自然度）0-100

评估水岸 coastal 区域是否足够宽，避免水域和陆地之间的硬切。

| 条件 | 分值 |
|------|------|
| coastal_avg_width >= 4（过渡带足够） | +50 |
| coastal_avg_width >= 2 | +25 |
| coastal_avg_width < 1（无明显过渡带） | -30 |
```

在 overall 加权公式中，新维度作为补充（不改变总权重，可以作为 issues 额外注释输出）：

在「输出格式」的 `scores` 中追加 3 个字段：

```json
    "mountain_linearity": 0-100,
    "river_validity": 0-100,
    "water_bank_transition": 0-100,
```

并更新 overall 公式（将原有 5 个维度 overall 保持不变，新 3 个作为 `terrain_quality` 参考分）：

```
overall（主评估用，推进阈值判断）= composition * 0.25 + terrain_rhythm * 0.25 + water_system * 0.20 + connectivity * 0.20 + boundary_design * 0.10

terrain_quality（参考，新增指标）= mountain_linearity * 0.4 + river_validity * 0.3 + water_bank_transition * 0.3
```

- [ ] **Step 2: 更新 civilization_era_eval_prompt.md**

在评分维度中新增 3 个：

```markdown
### traversability（道路坡度通行性）0-100

评估道路是否跨越 Y3 悬崖边界（cliff_map 差值 ≥ 2 的格子），此类格子实际不可通行。

| 条件 | 分值 |
|------|------|
| 所有道路格子 cliff 差值 < 2（完全可通行） | +60 |
| 道路中 cliff 差值 ≥ 2 的格子 < 5%（极少问题）| +30 |
| 道路中 cliff 差值 ≥ 2 的格子 > 15%（严重不可通行）| -40 |

### settlement_connectivity（聚落连通性）0-100

| 条件 | 分值 |
|------|------|
| unconnected_settlements = 0（全部聚落可达） | +60 |
| unconnected_settlements = 1 | +20 |
| unconnected_settlements ≥ 2 | 直接减分 -30/个 |

### path_ratio（主支路比例）0-100

评估是否有合理的主路和支路分布（避免全走捷径主路或支路蔓延失控）。

| 条件 | 分值 |
|------|------|
| 最长道路 / 平均道路长度 < 3（路网均衡） | +40 |
| road_segments 数量 >= settlements 数量（有支路） | +30 |
| 只有 1 条道路贯穿全图（无支路）| -20 |
```

在「推进条件」中新增：`settlement_connectivity >= 80`（即 unconnected_settlements = 0 对应此阈值）。

- [ ] **Step 3: 验证新维度已写入两个文件**

```bash
grep -c "mountain_linearity" skills/y3-maker-config/skills/y3-terrain-evolution/prompts/terrain_era_eval_prompt.md
grep -c "river_validity" skills/y3-maker-config/skills/y3-terrain-evolution/prompts/terrain_era_eval_prompt.md
grep -c "water_bank_transition" skills/y3-maker-config/skills/y3-terrain-evolution/prompts/terrain_era_eval_prompt.md
grep -c "traversability" skills/y3-maker-config/skills/y3-terrain-evolution/prompts/civilization_era_eval_prompt.md
grep -c "settlement_connectivity" skills/y3-maker-config/skills/y3-terrain-evolution/prompts/civilization_era_eval_prompt.md
grep -c "path_ratio" skills/y3-maker-config/skills/y3-terrain-evolution/prompts/civilization_era_eval_prompt.md
```

Expected: 每行输出 >= 1（维度已存在）

- [ ] **Step 4: Commit**

```bash
git add skills/y3-maker-config/skills/y3-terrain-evolution/prompts/
git commit -m "feat(prompts): add 6 new scoring dimensions to terrain + civilization eval prompts"
```

---

## Task 9: SKILL.md 更新

**Files:**
- Modify: `SKILL.md`

- [ ] **Step 1: 更新 SKILL.md 前置信息和全局禁令**

在文件顶部 `description` 字段更新为：
```
description: 通过 程序化生成（Voronoi+fBm+Ridged+Domain Warping）+ LLM 数据评分 + 生态时代 Three.js 视觉评分 + 迭代优化 Loop 生成 Y3 地形地图。支持 256×256 地图、A* 道路规划、分步 MCP 写入（Pass A/B/C）。不需要图片输入，不读取已有地形，全程数据变换，最终 MCP 批量写入。触发词：地形演化、生成地形地图、terrain evolution、程序化地图生成、生成Y3地图。
```

- [ ] **Step 2: 更新 Stage 0 — 前置准备（新增 theme 确认）**

在 0.2 配置读取确认中，新增显示 `主题: {theme}` 一行。

- [ ] **Step 3: 更新 Stage 1 — 地质时代**

- 1.1 的 generate_terrain.py 命令保持不变（已有 --config 参数读取 theme）
- 1.3 评分维度新增 mountain_linearity、river_validity、water_bank_transition 三行

- [ ] **Step 4: 更新 Stage 2 — 生态时代（新增视觉评分步骤）**

在 2.3 主评估通过后，新增 2.4 视觉评分：

```
### 2.4 视觉评分（生态时代专属）

if overall >= 65（数据评分通过）:
    AI 执行: python scripts/visual_eval.py \
      --era ecology \
      --world-state output/world_state.json \
      --ecology output/ecology_layer.json \
      --output output/visual_eval_ecology.json \
      --api-key $ANTHROPIC_API_KEY

    AI 提示用户: "预览服务器已启动，可访问 http://localhost:9876 查看地形"

    读取 output/visual_eval_ecology.json 中的 overall 值：
      visual_overall >= 65 → 进入 Stage 3
      visual_overall < 65 → 根据 suggestions 生成 patch_plan → apply_patch.py --era ecology → 回到 2.1
      连续 {max_visual_iterations} 轮未达标 → 询问用户
```

- [ ] **Step 5: 更新 Stage 3 — 文明时代（新增 3 个评分维度说明）**

在 3.2 中新增 traversability、settlement_connectivity、path_ratio 三个维度。

- [ ] **Step 6: 更新 Stage 5 — 分步 MCP 写入**

将原来的单命令写入替换为 Pass A/B/C 三步流程（包含暂停提示）。

- [ ] **Step 7: 验证 SKILL.md 关键关键词存在**

```bash
grep -c "Voronoi" skills/y3-maker-config/skills/y3-terrain-evolution/SKILL.md
grep -c "visual_eval.py" skills/y3-maker-config/skills/y3-terrain-evolution/SKILL.md
grep -c "Pass A" skills/y3-maker-config/skills/y3-terrain-evolution/SKILL.md
grep -c "Pass B" skills/y3-maker-config/skills/y3-terrain-evolution/SKILL.md
grep -c "Pass C" skills/y3-maker-config/skills/y3-terrain-evolution/SKILL.md
grep -c "max_visual_iterations" skills/y3-maker-config/skills/y3-terrain-evolution/SKILL.md
```

Expected: 每行输出 >= 1

- [ ] **Step 8: Commit**

```bash
git add skills/y3-maker-config/skills/y3-terrain-evolution/SKILL.md
git commit -m "feat(skill): update SKILL.md to v2 - Voronoi, visual eval, A* roads, Pass A/B/C write"
```

---

## Task 10: 全流程冒烟测试

- [ ] **Step 1: 运行全部单元测试**

```bash
cd skills/y3-maker-config/skills/y3-terrain-evolution
python -m pytest tests/ -v
```

Expected: 全部 PASSED（无 FAILED，SKIP 可接受）

- [ ] **Step 2: 地质时代端到端冒烟**

```bash
python scripts/check_deps.py
python scripts/generate_terrain.py --config config/world_config.json --output-dir output/
python scripts/analyze_terrain.py --world-state output/world_state.json --output output/terrain_summary.json
python -c "
import json
s = json.load(open('output/terrain_summary.json'))
assert 'mountain_chain_count' in s
assert 'river_validity_ratio' in s
assert 'coastal_avg_width' in s
print('terrain summary OK')
print('mountain_chain_count:', s['mountain_chain_count'])
print('river_validity_ratio:', s['river_validity_ratio'])
print('coastal_avg_width:', s['coastal_avg_width'])
"
```

Expected: `terrain summary OK` + 三个数值

- [ ] **Step 3: 文明时代道路冒烟**

```bash
python scripts/generate_civilization.py \
  --world-state output/world_state.json \
  --output output/civilization_layer.json
python -c "
import json
civ = json.load(open('output/civilization_layer.json'))
roads = civ['roads']
if roads:
    path0 = roads[0]['cells']
    for (y1,x1),(y2,x2) in zip(path0[:-1], path0[1:]):
        assert abs(y2-y1)+abs(x2-x1)==1, f'Diagonal found: ({y1},{x1})->({y2},{x2})'
print('A* 4-connectivity OK, settlements:', len(civ[\"settlements\"]), 'roads:', len(roads))
"
```

Expected: `A* 4-connectivity OK`

- [ ] **Step 4: mcp_writer --pass 参数冒烟（dry-run）**

```bash
python scripts/mcp_writer.py \
  --world-state output/world_state.json \
  --ecology output/ecology_layer.json \
  --civilization output/civilization_layer.json \
  --pass A --dry-run
```

Expected: 输出 Pass A 的格子统计（hill/cliff/crack/water），不尝试连接 MCP

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "test: verify v2 e2e smoke tests pass"
```

---

## 注意事项

### ANTHROPIC_API_KEY

`visual_eval.py` 需要 `ANTHROPIC_API_KEY` 环境变量或 `--api-key` 参数。在运行 Stage 2 视觉评分前确保已设置：

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### Y3 编辑器「允许地形修改」

MCP 写入前，在 Y3 编辑器「细节 → 地图设置 → 地形修改」中勾选「允许地形修改」，否则写入无效。

### 256×256 地图耗时

256×256 = 65536 格子，每批 100 格。Pass A（6 个写入类型）约 3900 次 MCP 调用，预计 Pass A 总时间 3-5 分钟。请耐心等待。

### preview_server 和浏览器

`visual_eval.py` 当前实现为：若浏览器未打开则返回占位图（1px PNG），这意味着 Claude 视觉评分基于占位图。实际使用时需在浏览器打开 `http://localhost:9876`，点击「截图」按钮后 server 保存截图，`visual_eval.py` 下次调用时读取该截图。如需完全自动化截图，可将 `take_screenshot` 改为调用 `playwright` 无头浏览器（不在本计划范围内）。
