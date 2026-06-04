# Round 3 Decoration Entity Layer - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Round 3 to `y3-gen-terrain-from-image`, generating decoration entities (forests, rocks, buildings, game nodes, roads, bridges) from an AI-painted grayscale overlay image, with a user-editable manifest and MCP batch write.

**Architecture:** `gen_gray_context.py` converts height/water grids to a grayscale PNG; GPT Image 2 paints decorations using the color semantic protocol onto that image; `cv_decoration_extract.py` extracts spatial clusters by color and writes `decoration_manifest.json`; `mcp_round3_writer.py` reads the manifest and batch-writes entities to Y3 via MCP.

**Tech Stack:** Python 3, OpenCV (`cv2`), NumPy, scikit-learn (`sklearn.cluster.DBSCAN`), scikit-image (`skimage.morphology.skeletonize`), Pillow (`PIL`), pytest

---

## File Structure

```
y3-gen-terrain-from-image/
├── scripts/
│   ├── gen_gray_context.py          CREATE  灰度上下文图生成
│   ├── cv_decoration_extract.py     CREATE  CV装饰元素提取 → decoration_manifest.json
│   └── mcp_round3_writer.py         CREATE  Round 3 MCP实体批量写入
├── references/
│   ├── color_protocol_v1.json       CREATE  颜色语义协议机器可读版
│   └── decoration_model_catalog.json CREATE  元素类型→模型池映射
└── tests/
    ├── test_gen_gray_context.py     CREATE
    ├── test_cv_decoration_extract.py CREATE
    └── test_mcp_round3_writer.py    CREATE
```

**Existing files not modified:**
- `mcp_entity_writer.py` — Round 2 装饰写入，保持不变
- `cv_vegetation_fill.py` — Round 2 植被规则，不再调用（按设计文档禁用）

**Base path** (所有相对路径基于此): `E:\pycode\y3-map\y3-maker-config\skills\y3-gen-terrain-from-image`

---

## Task 1: 依赖检查 + 创建 references 文件

**Files:**
- Create: `references\color_protocol_v1.json`
- Create: `references\decoration_model_catalog.json`

- [ ] **Step 1: 检查 scikit-learn 和 scikit-image 是否已安装**

```bash
python -c "import sklearn; import skimage; print('OK')"
```

若报错，安装：
```bash
pip install scikit-learn scikit-image
```

- [ ] **Step 2: 创建 color_protocol_v1.json**

内容为颜色语义协议的机器可读版，供 `cv_decoration_extract.py` 导入，避免硬编码：

```json
{
  "version": "1.0",
  "gray_threshold": 25,
  "unknown_distance_threshold": 60,
  "elements": {
    "forest_sparse":     {"rgb": [100, 210,  50], "shape": "area",  "min_pixels": 16},
    "forest_medium":     {"rgb": [ 20, 160,  20], "shape": "area",  "min_pixels": 16},
    "forest_dense":      {"rgb": [  0,  90,   0], "shape": "area",  "min_pixels": 16},
    "rock_cluster":      {"rgb": [  0, 200, 200], "shape": "area",  "min_pixels": 16},
    "building_common":   {"rgb": [220, 160,  20], "shape": "point", "min_pixels":  4},
    "building_landmark": {"rgb": [200,  20, 120], "shape": "point", "min_pixels":  4},
    "resource_point":    {"rgb": [255, 210,   0], "shape": "point", "min_pixels":  4},
    "monster_lair":      {"rgb": [150,   0, 200], "shape": "point", "min_pixels":  4},
    "dungeon_entrance":  {"rgb": [ 70,   0, 150], "shape": "point", "min_pixels":  4},
    "road_main":         {"rgb": [220,  50,  20], "shape": "path",  "min_pixels": 10},
    "bridge":            {"rgb": [  0,  60, 220], "shape": "point", "min_pixels":  4}
  }
}
```

- [ ] **Step 3: 创建 decoration_model_catalog.json**

按地图主题组织的模型池。`default` 是无纹理匹配时的兜底：

```json
{
  "version": "1.0",
  "themes": {
    "grassland": {
      "forest_sparse":     {"trees": [200009, 103050, 103051], "rocks": [201707, 201708]},
      "forest_medium":     {"trees": [200009, 103050, 201627, 200572], "rocks": [201707]},
      "forest_dense":      {"trees": [200009, 103050, 103051, 201627, 200572], "rocks": []},
      "rock_cluster":      {"rocks": [201707, 201708, 201710]},
      "building_common":   {"models": [103261]},
      "building_landmark": {"models": [200009]},
      "bridge":            {"models": [100463, 100942, 200895]}
    },
    "autumn": {
      "forest_sparse":     {"trees": [40007, 40008, 103026], "rocks": [202954]},
      "forest_medium":     {"trees": [40007, 40008, 103026, 201626, 200566], "rocks": []},
      "forest_dense":      {"trees": [40007, 40008, 103026, 201626, 200566], "rocks": []},
      "rock_cluster":      {"rocks": [202954, 202955, 202962]},
      "building_common":   {"models": [103261]},
      "building_landmark": {"models": [200009]},
      "bridge":            {"models": [100463]}
    },
    "desert": {
      "forest_sparse":     {"trees": [103261, 103262, 103263], "rocks": [202952]},
      "forest_medium":     {"trees": [103261, 103262, 103265, 100001], "rocks": []},
      "forest_dense":      {"trees": [103261, 103262, 103263, 103265], "rocks": []},
      "rock_cluster":      {"rocks": [202952, 202955, 202961]},
      "building_common":   {"models": [103261]},
      "building_landmark": {"models": [103261]},
      "bridge":            {"models": [100463]}
    },
    "ice_snow": {
      "forest_sparse":     {"trees": [40001, 40002, 200574], "rocks": [202941]},
      "forest_medium":     {"trees": [40001, 40002, 200574, 200575, 200576], "rocks": []},
      "forest_dense":      {"trees": [40001, 40002, 200574, 200575, 200576], "rocks": []},
      "rock_cluster":      {"rocks": [202941, 202946, 202956]},
      "building_common":   {"models": [103261]},
      "building_landmark": {"models": [200009]},
      "bridge":            {"models": [100463]}
    },
    "default": {
      "forest_sparse":     {"trees": [200009, 103050], "rocks": [201707]},
      "forest_medium":     {"trees": [200009, 103050, 201627], "rocks": []},
      "forest_dense":      {"trees": [200009, 103050, 103051, 201627], "rocks": []},
      "rock_cluster":      {"rocks": [201707, 201708, 201710]},
      "building_common":   {"models": [103261]},
      "building_landmark": {"models": [200009]},
      "bridge":            {"models": [100463]}
    }
  },
  "road_model_id": 205148,
  "density_factors": {"sparse": 0.15, "medium": 0.30, "dense": 0.50},
  "poisson_min_spacing": 1.5
}
```

- [ ] **Step 4: 验证 JSON 格式合法**

```bash
python -c "import json; json.load(open('references/color_protocol_v1.json')); json.load(open('references/decoration_model_catalog.json')); print('JSON OK')"
```

期望输出：`JSON OK`

---

## Task 2: gen_gray_context.py — 亮度编码核心函数

**Files:**
- Create: `scripts\gen_gray_context.py`
- Create: `tests\test_gen_gray_context.py`

- [ ] **Step 1: 创建测试文件，写亮度编码测试**

```python
# tests/test_gen_gray_context.py
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from gen_gray_context import compute_brightness_grid

def test_deep_water_brightness():
    H, W = 4, 4
    height_grid = np.zeros((H, W), dtype=np.int32)
    water_mask  = np.ones((H, W), dtype=np.uint8)   # all water
    water_type  = np.ones((H, W), dtype=np.int8)    # 1 = deep_water
    result = compute_brightness_grid(height_grid, water_mask, water_type)
    assert result.shape == (H, W)
    assert np.all(result == 20), f"Expected 20, got {result}"

def test_ground_heights():
    H, W = 1, 4
    heights = np.array([[0, 2, 4, 6]], dtype=np.int32)
    water_mask = np.zeros((H, W), dtype=np.uint8)   # no water
    water_type = np.zeros((H, W), dtype=np.int8)
    result = compute_brightness_grid(heights, water_mask, water_type)
    assert result[0, 0] == 120  # h=0
    assert result[0, 1] == 155  # h=2
    assert result[0, 2] == 190  # h=4
    assert result[0, 3] == 230  # h=6

def test_water_overrides_height():
    H, W = 1, 3
    heights = np.array([[4, 4, 4]], dtype=np.int32)   # all high
    water_mask = np.array([[0, 1, 1]], dtype=np.uint8)
    water_type = np.array([[0, 2, 3]], dtype=np.int8)  # 2=shallow, 3=plain
    result = compute_brightness_grid(heights, water_mask, water_type)
    assert result[0, 0] == 190  # ground h=4
    assert result[0, 1] == 60   # shallow_water
    assert result[0, 2] == 80   # plain_water
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd E:\pycode\y3-map\y3-maker-config\skills\y3-gen-terrain-from-image
python -m pytest tests/test_gen_gray_context.py -v
```

期望：`ImportError: No module named gen_gray_context` 或 `ModuleNotFoundError`

- [ ] **Step 3: 实现 compute_brightness_grid**

```python
# scripts/gen_gray_context.py
import numpy as np

# water_type 编码（与 cv_water_classify.py 一致）
# 0=land, 1=deep_water, 2=shallow_water, 3=plain_water
_WATER_BRIGHTNESS = {1: 20, 2: 60, 3: 80}
_HEIGHT_BRIGHTNESS = {0: 120, 2: 155, 4: 190, 6: 230}


def compute_brightness_grid(height_grid: np.ndarray,
                             water_mask: np.ndarray,
                             water_type: np.ndarray) -> np.ndarray:
    """
    Returns uint8 brightness grid (H x W).
    Water cells override height. Unknown heights clamp to nearest defined value.
    """
    H, W = height_grid.shape
    result = np.zeros((H, W), dtype=np.uint8)

    for r in range(H):
        for c in range(W):
            if water_mask[r, c]:
                wt = int(water_type[r, c])
                result[r, c] = _WATER_BRIGHTNESS.get(wt, 80)
            else:
                h = int(height_grid[r, c])
                # clamp to nearest defined height
                defined = sorted(_HEIGHT_BRIGHTNESS.keys())
                closest = min(defined, key=lambda x: abs(x - h))
                result[r, c] = _HEIGHT_BRIGHTNESS[closest]

    return result
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
python -m pytest tests/test_gen_gray_context.py -v
```

期望：3 passed

---

## Task 3: gen_gray_context.py — 候选位置叠加 + 主入口

**Files:**
- Modify: `scripts\gen_gray_context.py`
- Modify: `tests\test_gen_gray_context.py`

- [ ] **Step 1: 补充候选位置叠加测试**

追加到 `tests/test_gen_gray_context.py`：

```python
import json, tempfile, pathlib
from PIL import Image
from gen_gray_context import overlay_candidates, brightness_to_png

def test_overlay_candidates_draws_dot():
    # 8x8 grayscale image, overlay a 3x3 dot at (4,4)
    gray = np.full((8, 8), 120, dtype=np.uint8)
    img = Image.fromarray(gray).convert('RGB')
    candidates = [{"x": 4, "z": 4}]
    color = (255, 210, 0)  # resource_point gold
    result = overlay_candidates(img, candidates, color, dot_radius=1)
    arr = np.array(result)
    # center pixel should match color
    assert tuple(arr[4, 4]) == color

def test_main_produces_png():
    H, W = 10, 10
    height_grid = np.zeros((H, W), dtype=np.int32)
    water_mask  = np.zeros((H, W), dtype=np.uint8)
    water_type  = np.zeros((H, W), dtype=np.int8)
    spatial = {"resource_points": [{"x": 5, "z": 5}],
               "monster_lairs": [], "dungeon_entrances": [], "bridge_candidates": []}
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "gray_context.png"
        brightness_to_png(height_grid, water_mask, water_type, spatial, str(out))
        assert out.exists()
        img = Image.open(str(out))
        assert img.size == (W, H)
```

- [ ] **Step 2: 运行测试，确认新测试失败**

```bash
python -m pytest tests/test_gen_gray_context.py::test_overlay_candidates_draws_dot -v
```

期望：`ImportError` 或 `AttributeError`

- [ ] **Step 3: 实现 overlay_candidates + brightness_to_png + main()**

追加到 `scripts/gen_gray_context.py`：

```python
import argparse, json, pathlib, sys
from PIL import Image, ImageDraw

# 候选位置对应的协议颜色（RGB）
_CANDIDATE_COLORS = {
    'resource_points':    (255, 210,   0),
    'monster_lairs':      (150,   0, 200),
    'dungeon_entrances':  ( 70,   0, 150),
    'bridge_candidates':  (  0,  60, 220),
}


def overlay_candidates(img: Image.Image, candidates: list,
                        color: tuple, dot_radius: int = 1) -> Image.Image:
    """Draw filled square dots for candidate positions onto img (in-place copy)."""
    draw = ImageDraw.Draw(img)
    for c in candidates:
        x, z = int(c['x']), int(c['z'])
        draw.rectangle(
            [x - dot_radius, z - dot_radius, x + dot_radius, z + dot_radius],
            fill=color
        )
    return img


def brightness_to_png(height_grid, water_mask, water_type, spatial_analysis, out_path):
    """Full pipeline: grids → grayscale PNG with candidate overlays."""
    brightness = compute_brightness_grid(height_grid, water_mask, water_type)
    img = Image.fromarray(brightness, mode='L').convert('RGB')

    for key, color in _CANDIDATE_COLORS.items():
        candidates = spatial_analysis.get(key, [])
        if candidates:
            overlay_candidates(img, candidates, color, dot_radius=1)

    img.save(out_path)
    print(f"✓ gray_context.png saved → {out_path}  ({img.size[0]}×{img.size[1]}px)")


def main():
    parser = argparse.ArgumentParser(description='Generate grayscale context image for Round 3')
    parser.add_argument('run_dir', help='Path to output/{run_id}/ directory')
    args = parser.parse_args()

    run = pathlib.Path(args.run_dir)
    height_grid  = __import__('numpy').load(str(run / 'height_grid.npy'))
    water_mask   = __import__('numpy').load(str(run / 'water_mask_grid.npy'))
    water_type   = __import__('numpy').load(str(run / 'water_type_grid.npy'))
    spatial      = json.loads((run / 'spatial_analysis.json').read_text(encoding='utf-8'))

    brightness_to_png(height_grid, water_mask, water_type, spatial,
                       str(run / 'gray_context.png'))


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: 运行全部测试，确认通过**

```bash
python -m pytest tests/test_gen_gray_context.py -v
```

期望：5 passed

---

## Task 4: cv_decoration_extract.py — 预处理 + 灰色过滤 + 颜色分类

**Files:**
- Create: `scripts\cv_decoration_extract.py`
- Create: `tests\test_cv_decoration_extract.py`

- [ ] **Step 1: 写预处理和颜色分类测试**

```python
# tests/test_cv_decoration_extract.py
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

PROTOCOL_PATH = os.path.join(os.path.dirname(__file__), '..', 'references', 'color_protocol_v1.json')

from cv_decoration_extract import load_protocol, is_gray, classify_pixel, preprocess_image
import cv2, tempfile
from PIL import Image

def _make_png(arr_rgb: np.ndarray, path: str):
    """Save RGB numpy array as PNG."""
    Image.fromarray(arr_rgb.astype(np.uint8)).save(path)

def test_load_protocol():
    proto = load_protocol(PROTOCOL_PATH)
    assert 'elements' in proto
    assert 'forest_medium' in proto['elements']
    assert proto['elements']['forest_medium']['shape'] == 'area'

def test_is_gray():
    assert is_gray(128, 128, 128, threshold=25)   # pure gray
    assert is_gray(130, 128, 129, threshold=25)   # near gray
    assert not is_gray(20, 160, 20, threshold=25) # green

def test_classify_pixel_exact():
    proto = load_protocol(PROTOCOL_PATH)
    elem_type, dist = classify_pixel(20, 160, 20, proto)
    assert elem_type == 'forest_medium'
    assert dist < 5

def test_classify_pixel_unknown():
    proto = load_protocol(PROTOCOL_PATH)
    elem_type, dist = classify_pixel(128, 128, 40, proto)  # olive-ish
    # may match something or be marked unknown
    assert dist > 0  # distance is always positive

def test_preprocess_resizes():
    # Create 20x20 image, request 10x10
    arr = np.zeros((20, 20, 3), dtype=np.uint8)
    arr[0:10, 0:10] = [20, 160, 20]  # green patch
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        _make_png(arr, f.name)
        result = preprocess_image(f.name, target_w=10, target_h=10)
    assert result.shape == (10, 10, 3)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python -m pytest tests/test_cv_decoration_extract.py -v
```

期望：ImportError

- [ ] **Step 3: 实现 load_protocol + is_gray + classify_pixel + preprocess_image**

```python
# scripts/cv_decoration_extract.py
import cv2, json, math, pathlib, sys
import numpy as np

# ---------------------------------------------------------------------------
# 协议加载
# ---------------------------------------------------------------------------

def load_protocol(protocol_path: str) -> dict:
    return json.loads(pathlib.Path(protocol_path).read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# 像素分类
# ---------------------------------------------------------------------------

def is_gray(r: int, g: int, b: int, threshold: int = 25) -> bool:
    return max(abs(r - g), abs(g - b), abs(r - b)) < threshold


def classify_pixel(r: int, g: int, b: int, protocol: dict) -> tuple:
    """Returns (element_type, distance). Ignores gray background (caller filters first)."""
    best_type, best_dist = None, float('inf')
    for elem_type, info in protocol['elements'].items():
        pr, pg, pb = info['rgb']
        dist = math.sqrt((r - pr)**2 + (g - pg)**2 + (b - pb)**2)
        if dist < best_dist:
            best_dist, best_type = dist, elem_type
    return best_type, best_dist


# ---------------------------------------------------------------------------
# 图像预处理 (Step [0])
# ---------------------------------------------------------------------------

def preprocess_image(img_path: str, target_w: int, target_h: int) -> np.ndarray:
    """Load image and resize to exact grid dimensions using nearest-neighbor."""
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {img_path}")
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    if img_rgb.shape[1] != target_w or img_rgb.shape[0] != target_h:
        img_rgb = cv2.resize(img_rgb, (target_w, target_h),
                             interpolation=cv2.INTER_NEAREST)
    return img_rgb
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
python -m pytest tests/test_cv_decoration_extract.py -v
```

期望：5 passed

---

## Task 5: cv_decoration_extract.py — 面状元素 DBSCAN 聚类

**Files:**
- Modify: `scripts\cv_decoration_extract.py`
- Modify: `tests\test_cv_decoration_extract.py`

- [ ] **Step 1: 补充 DBSCAN 聚类测试**

追加到 `tests/test_cv_decoration_extract.py`：

```python
from cv_decoration_extract import extract_area_clusters

def test_area_cluster_finds_patch():
    # 30x30 image, paint a 10x10 green patch at (5,5)
    coords = [(r, c) for r in range(5, 15) for c in range(5, 15)]  # 100 pixels
    clusters = extract_area_clusters(coords, eps=4, min_samples=6, min_cluster_pixels=16)
    assert len(clusters) == 1
    cx, cz, radius = clusters[0]
    assert 5 <= cx <= 15
    assert 5 <= cz <= 15
    assert radius > 0

def test_area_cluster_rejects_small():
    # Only 9 pixels — below min_cluster_pixels=16
    coords = [(r, c) for r in range(3) for c in range(3)]
    clusters = extract_area_clusters(coords, eps=4, min_samples=6, min_cluster_pixels=16)
    assert len(clusters) == 0

def test_area_cluster_two_separate_patches():
    # Two 10x10 patches far apart
    coords  = [(r, c) for r in range(0,  10) for c in range(0,  10)]
    coords += [(r, c) for r in range(20, 30) for c in range(20, 30)]
    clusters = extract_area_clusters(coords, eps=4, min_samples=6, min_cluster_pixels=16)
    assert len(clusters) == 2
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python -m pytest tests/test_cv_decoration_extract.py::test_area_cluster_finds_patch -v
```

期望：ImportError 或 AttributeError

- [ ] **Step 3: 实现 extract_area_clusters**

追加到 `scripts/cv_decoration_extract.py`：

```python
from sklearn.cluster import DBSCAN

def extract_area_clusters(coords: list, eps: float = 4, min_samples: int = 6,
                           min_cluster_pixels: int = 16) -> list:
    """
    coords: list of (row, col) tuples for pixels of one element type.
    Returns list of (center_x, center_z, radius) in grid coords.
    Skips clusters with pixel count < min_cluster_pixels.
    """
    if len(coords) < min_samples:
        return []

    pts = np.array(coords, dtype=np.float32)  # (row=z, col=x)
    labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(pts)

    clusters = []
    for label in set(labels):
        if label == -1:
            continue  # noise
        mask = labels == label
        if mask.sum() < min_cluster_pixels:
            continue  # too small
        cluster_pts = pts[mask]
        center_z = float(np.mean(cluster_pts[:, 0]))
        center_x = float(np.mean(cluster_pts[:, 1]))
        # radius = max distance from center to any point
        dists = np.sqrt((cluster_pts[:, 0] - center_z)**2 +
                        (cluster_pts[:, 1] - center_x)**2)
        radius = float(np.max(dists))
        clusters.append((center_x, center_z, max(radius, 1.0)))

    return clusters
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
python -m pytest tests/test_cv_decoration_extract.py -v
```

期望：8 passed

---

## Task 6: cv_decoration_extract.py — 点状元素连通域 + 线状骨架化

**Files:**
- Modify: `scripts\cv_decoration_extract.py`
- Modify: `tests\test_cv_decoration_extract.py`

- [ ] **Step 1: 补充点状和线状检测测试**

追加到 `tests/test_cv_decoration_extract.py`：

```python
from cv_decoration_extract import extract_point_elements, extract_path_elements

def test_point_finds_single_blob():
    # 3x3 patch in a 20x20 grid → single point
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[5:8, 5:8] = 1  # 9 pixels
    points = extract_point_elements(mask, min_pixels=4)
    assert len(points) == 1
    cx, cz = points[0]
    assert 5 <= cx <= 8
    assert 5 <= cz <= 8

def test_point_rejects_tiny():
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[5, 5] = 1  # single pixel, min_pixels=4
    points = extract_point_elements(mask, min_pixels=4)
    assert len(points) == 0

def test_path_finds_horizontal_line():
    mask = np.zeros((20, 30), dtype=np.uint8)
    mask[10, 5:25] = 1  # 20px horizontal line
    waypoints = extract_path_elements(mask, min_pixels=10)
    assert len(waypoints) >= 2
    # all waypoints should be near row 10
    for (px, pz) in waypoints:
        assert abs(pz - 10) <= 1

def test_path_rejects_short():
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[10, 5:9] = 1  # only 4 pixels
    waypoints = extract_path_elements(mask, min_pixels=10)
    assert len(waypoints) == 0
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python -m pytest tests/test_cv_decoration_extract.py::test_point_finds_single_blob -v
```

期望：ImportError

- [ ] **Step 3: 实现 extract_point_elements + extract_path_elements**

追加到 `scripts/cv_decoration_extract.py`：

```python
from skimage.morphology import skeletonize


def extract_point_elements(mask: np.ndarray, min_pixels: int = 4) -> list:
    """
    mask: 2D uint8 array where 1 = decoration pixel.
    Returns list of (center_x, center_z) in grid coords.
    Skips connected components smaller than min_pixels.
    """
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    points = []
    for i in range(1, num_labels):  # skip background label 0
        pixel_count = stats[i, cv2.CC_STAT_AREA]
        if pixel_count < min_pixels:
            continue
        cx = float(centroids[i, 0])  # col → x
        cz = float(centroids[i, 1])  # row → z
        points.append((cx, cz))
    return points


def extract_path_elements(mask: np.ndarray, min_pixels: int = 10,
                           sample_step: int = 3) -> list:
    """
    mask: 2D uint8 array where 1 = road pixel.
    Returns ordered list of (x, z) waypoints along skeleton.
    Skips if skeleton pixel count < min_pixels.
    """
    bool_mask = mask.astype(bool)
    skeleton = skeletonize(bool_mask)
    skel_coords = np.argwhere(skeleton)  # (row, col)

    if len(skel_coords) < min_pixels:
        return []

    # Sample waypoints along skeleton at regular intervals
    # Sort by row then col for consistent ordering (approximate path order)
    skel_coords = skel_coords[np.lexsort((skel_coords[:, 1], skel_coords[:, 0]))]
    sampled = skel_coords[::sample_step]
    waypoints = [(int(c[1]), int(c[0])) for c in sampled]  # (x, z)
    return waypoints
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
python -m pytest tests/test_cv_decoration_extract.py -v
```

期望：12 passed

---

## Task 7: cv_decoration_extract.py — 模型分配 + manifest 输出 + 主入口

**Files:**
- Modify: `scripts\cv_decoration_extract.py`
- Modify: `tests\test_cv_decoration_extract.py`

- [ ] **Step 1: 补充端到端提取测试**

追加到 `tests/test_cv_decoration_extract.py`：

```python
import json, tempfile, pathlib
from cv_decoration_extract import run_extraction

def test_end_to_end_extracts_forest():
    # 40x40 image: 12x12 green patch (rows 2-13, cols 2-13) = forest_medium
    arr = np.full((40, 40, 3), 128, dtype=np.uint8)  # gray background
    arr[2:14, 2:14] = [20, 160, 20]  # forest_medium 12x12 (144 pixels, well above min=16)

    with tempfile.TemporaryDirectory() as tmp:
        img_path  = str(pathlib.Path(tmp) / 'deco.png')
        out_path  = str(pathlib.Path(tmp) / 'manifest.json')
        proto_path = PROTOCOL_PATH
        catalog_path = os.path.join(os.path.dirname(__file__), '..', 'references',
                                    'decoration_model_catalog.json')
        Image.fromarray(arr).save(img_path)

        run_extraction(
            img_path=img_path,
            texture_grid=np.zeros((40, 40), dtype=np.int32),
            protocol_path=proto_path,
            catalog_path=catalog_path,
            output_path=out_path,
            grid_w=40, grid_h=40,
            theme='default'
        )

        manifest = json.loads(pathlib.Path(out_path).read_text())
        assert manifest['meta']['total_elements'] >= 1
        types = [e['type'] for e in manifest['elements']]
        assert 'forest_medium' in types
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python -m pytest tests/test_cv_decoration_extract.py::test_end_to_end_extracts_forest -v
```

期望：ImportError 或 AttributeError

- [ ] **Step 3: 实现 assign_models + build_element + run_extraction**

追加到 `scripts/cv_decoration_extract.py`：

```python
import datetime, random, warnings


def assign_models(elem_type: str, catalog: dict, theme: str = 'default') -> tuple:
    """Returns (model_group, model_ids) for given element type and theme."""
    theme_data = catalog['themes'].get(theme, catalog['themes']['default'])
    elem_data  = theme_data.get(elem_type, {})
    trees  = elem_data.get('trees',  [])
    rocks  = elem_data.get('rocks',  [])
    models = elem_data.get('models', [])
    all_models = trees + rocks + models
    model_group = theme if elem_type in theme_data else 'default'
    return model_group, all_models


def _world_pos(gx: float, gz: float, grid_w: int, grid_h: int) -> dict:
    return {'x': round(gx * 2 - (grid_w - 1), 2),
            'y': 0.0,
            'z': round(gz * 2 - (grid_h - 1), 2)}


def run_extraction(img_path, texture_grid, protocol_path, catalog_path,
                   output_path, grid_w, grid_h, theme='default'):
    """Full Round 3.3 pipeline. Writes decoration_manifest.json."""
    protocol = load_protocol(protocol_path)
    catalog  = json.loads(pathlib.Path(catalog_path).read_text(encoding='utf-8'))
    threshold = protocol.get('gray_threshold', 25)
    unk_thresh = protocol.get('unknown_distance_threshold', 60)

    img = preprocess_image(img_path, grid_w, grid_h)  # (H, W, 3) RGB

    # Per-type pixel lists
    type_pixels: dict = {k: [] for k in protocol['elements']}
    unknown_log = []

    for r in range(grid_h):
        for c in range(grid_w):
            R, G, B = int(img[r, c, 0]), int(img[r, c, 1]), int(img[r, c, 2])
            if is_gray(R, G, B, threshold):
                continue
            elem_type, dist = classify_pixel(R, G, B, protocol)
            if dist > unk_thresh:
                unknown_log.append(f"({c},{r}) RGB=({R},{G},{B}) dist={dist:.1f}")
                continue
            type_pixels[elem_type].append((r, c))

    # Write unknown log
    log_dir = pathlib.Path(output_path).parent
    if unknown_log:
        (log_dir / 'unknown_pixels.log').write_text('\n'.join(unknown_log), encoding='utf-8')

    elements = []
    shape_warnings = []
    elem_id = 0

    for elem_type, info in protocol['elements'].items():
        shape = info['shape']
        min_pix = info['min_pixels']
        coords = type_pixels[elem_type]
        if not coords:
            continue

        model_group, model_ids = assign_models(elem_type, catalog, theme)

        if shape == 'area':
            clusters = extract_area_clusters(coords, min_cluster_pixels=min_pix)
            for cx, cz, radius in clusters:
                density = 'medium'
                elem = {
                    'id': f'e_{elem_id:04d}',
                    'type': elem_type, 'shape': 'area',
                    'grid_pos': {'x': round(cx, 1), 'z': round(cz, 1)},
                    'radius': round(radius, 1), 'density': density,
                    'model_group': model_group, 'model_ids': model_ids,
                    'world_pos': _world_pos(cx, cz, grid_w, grid_h),
                    'source_color': info['rgb'], 'status': 'pending',
                    'modified': False, 'modify_history': []
                }
                elements.append(elem); elem_id += 1
            # warn if raw pixels existed but no valid cluster
            if coords and not clusters:
                shape_warnings.append(
                    f"{elem_type}: {len(coords)} pixels found but no cluster met min_pixels={min_pix}")

        elif shape == 'point':
            H_img, W_img = grid_h, grid_w
            mask = np.zeros((H_img, W_img), dtype=np.uint8)
            for (r, c) in coords:
                mask[r, c] = 1
            points = extract_point_elements(mask, min_pixels=min_pix)
            for cx, cz in points:
                elem = {
                    'id': f'e_{elem_id:04d}',
                    'type': elem_type, 'shape': 'point',
                    'grid_pos': {'x': round(cx, 1), 'z': round(cz, 1)},
                    'model_group': model_group, 'model_ids': model_ids,
                    'world_pos': _world_pos(cx, cz, grid_w, grid_h),
                    'source_color': info['rgb'], 'status': 'pending',
                    'modified': False, 'modify_history': []
                }
                elements.append(elem); elem_id += 1

        elif shape == 'path':
            mask = np.zeros((grid_h, grid_w), dtype=np.uint8)
            for (r, c) in coords:
                mask[r, c] = 1
            waypoints = extract_path_elements(mask, min_pixels=min_pix)
            if waypoints:
                elem = {
                    'id': f'e_{elem_id:04d}',
                    'type': elem_type, 'shape': 'path',
                    'waypoints': [{'x': wx, 'z': wz} for wx, wz in waypoints],
                    'width': 2,
                    'model_ids': [catalog.get('road_model_id', 205148)],
                    'source_color': info['rgb'], 'status': 'pending',
                    'modified': False, 'modify_history': []
                }
                elements.append(elem); elem_id += 1
            elif coords:
                shape_warnings.append(
                    f"{elem_type}: {len(coords)} pixels found but skeleton too short")

    if shape_warnings:
        (log_dir / 'shape_warnings.log').write_text('\n'.join(shape_warnings), encoding='utf-8')
        print(f"⚠️  {len(shape_warnings)} 个元素因尺寸不足被跳过，详见 shape_warnings.log")

    summary = {}
    for e in elements:
        summary[e['type']] = summary.get(e['type'], 0) + 1

    manifest = {
        'meta': {
            'generated_at': datetime.datetime.now().isoformat(),
            'grid_size': {'w': grid_w, 'h': grid_h},
            'total_elements': len(elements),
            'color_protocol_version': protocol.get('version', '1.0'),
            'theme': theme
        },
        'elements': elements,
        'summary': summary
    }

    pathlib.Path(output_path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f"✓ decoration_manifest.json → {len(elements)} 个元素")
    return manifest


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Round 3.3 - Extract decoration elements')
    parser.add_argument('run_dir',        help='output/{run_id}/ directory')
    parser.add_argument('--texture-grid', default=None, help='texture_grid.csv path')
    parser.add_argument('--theme',        default='default', help='decoration theme')
    args = parser.parse_args()

    run   = pathlib.Path(args.run_dir)
    skill = pathlib.Path(__file__).parent.parent
    proto   = str(skill / 'references' / 'color_protocol_v1.json')
    catalog = str(skill / 'references' / 'decoration_model_catalog.json')

    if args.texture_grid:
        texture_grid = np.genfromtxt(args.texture_grid, delimiter=',', dtype=np.int32)
    else:
        texture_grid = np.zeros((1, 1), dtype=np.int32)

    import json as _json
    spatial = _json.loads((run / 'spatial_analysis.json').read_text(encoding='utf-8'))
    # Infer grid size from spatial_analysis or height_grid
    hg = np.load(str(run / 'height_grid.npy'))
    grid_h, grid_w = hg.shape

    run_extraction(
        img_path    = str(run / 'decoration_design.png'),
        texture_grid= texture_grid,
        protocol_path = proto,
        catalog_path  = catalog,
        output_path   = str(run / 'decoration_manifest.json'),
        grid_w=grid_w, grid_h=grid_h,
        theme=args.theme
    )


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: 运行全部测试，确认通过**

```bash
python -m pytest tests/test_cv_decoration_extract.py -v
```

期望：13 passed

---

## Task 8: mcp_round3_writer.py — Poisson Disk 展开 + 批量写入

**Files:**
- Create: `scripts\mcp_round3_writer.py`
- Create: `tests\test_mcp_round3_writer.py`

- [ ] **Step 1: 写 Poisson Disk 展开测试**

```python
# tests/test_mcp_round3_writer.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from mcp_round3_writer import poisson_disk_positions, interpolate_path

def test_poisson_positions_count():
    import math
    positions = poisson_disk_positions(center_x=50, center_z=50,
                                        radius=8, density='medium', min_spacing=1.5)
    expected_n = int(math.pi * 8**2 * 0.30)
    # Allow ±30% due to Poisson packing randomness
    assert len(positions) > expected_n * 0.5
    assert len(positions) < expected_n * 2.0

def test_poisson_min_spacing():
    positions = poisson_disk_positions(50, 50, radius=5, density='dense', min_spacing=1.5)
    for i, (x1, z1) in enumerate(positions):
        for j, (x2, z2) in enumerate(positions):
            if i != j:
                dist = ((x1-x2)**2 + (z1-z2)**2) ** 0.5
                assert dist >= 1.3, f"Positions too close: {dist:.2f}"

def test_interpolate_path_spacing():
    waypoints = [{'x': 0, 'z': 0}, {'x': 10, 'z': 0}, {'x': 20, 'z': 0}]
    tiles = interpolate_path(waypoints, width=2, tile_spacing=1)
    xs = [t['x'] for t in tiles]
    # Should have tiles along x=0..20
    assert min(xs) == 0
    assert max(xs) == 20

def test_interpolate_path_empty():
    assert interpolate_path([], width=2, tile_spacing=1) == []
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python -m pytest tests/test_mcp_round3_writer.py -v
```

期望：ImportError

- [ ] **Step 3: 实现 poisson_disk_positions + interpolate_path**

```python
# scripts/mcp_round3_writer.py
import json, math, random, pathlib, time
import argparse

DENSITY_FACTORS = {'sparse': 0.15, 'medium': 0.30, 'dense': 0.50}


def poisson_disk_positions(center_x: float, center_z: float,
                            radius: float, density: str,
                            min_spacing: float = 1.5,
                            max_attempts: int = 30) -> list:
    """
    Generate N positions within circle using Poisson Disk Sampling.
    Returns list of (x, z) tuples.
    """
    factor = DENSITY_FACTORS.get(density, 0.30)
    target_n = max(1, int(math.pi * radius**2 * factor))
    placed = []

    for _ in range(target_n * max_attempts):
        if len(placed) >= target_n:
            break
        angle = random.uniform(0, 2 * math.pi)
        r = random.uniform(0, radius)
        x = center_x + r * math.cos(angle)
        z = center_z + r * math.sin(angle)
        # Check min spacing against all placed positions
        too_close = any(
            math.sqrt((x - px)**2 + (z - pz)**2) < min_spacing
            for px, pz in placed
        )
        if not too_close:
            placed.append((x, z))

    return placed


def interpolate_path(waypoints: list, width: int = 2,
                     tile_spacing: float = 1.0) -> list:
    """
    Interpolate road tile positions along waypoints.
    Returns list of {'x': int, 'z': int} dicts.
    """
    if len(waypoints) < 2:
        return []

    tiles = set()
    for i in range(len(waypoints) - 1):
        x0, z0 = waypoints[i]['x'], waypoints[i]['z']
        x1, z1 = waypoints[i+1]['x'], waypoints[i+1]['z']
        length = math.sqrt((x1-x0)**2 + (z1-z0)**2)
        if length == 0:
            continue
        steps = max(1, int(length / tile_spacing))
        for s in range(steps + 1):
            t = s / steps
            cx = round(x0 + t * (x1 - x0))
            cz = round(z0 + t * (z1 - z0))
            for dw in range(-(width//2), width//2 + 1):
                tiles.add((cx + dw, cz))

    return [{'x': x, 'z': z} for x, z in sorted(tiles)]
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
python -m pytest tests/test_mcp_round3_writer.py -v
```

期望：4 passed

---

## Task 9: mcp_round3_writer.py — MCP写入 + 批量主入口

**Files:**
- Modify: `scripts\mcp_round3_writer.py`

- [ ] **Step 1: 实现 write_batch_entities + write_manifest**

追加到 `scripts/mcp_round3_writer.py`：

```python
try:
    import requests
except ImportError:
    requests = None


def _load_mcp_url(run_dir: str) -> str:
    """Read MCP URL from mcp_settings.json (same convention as mcp_batch_writer.py)."""
    settings_paths = [
        pathlib.Path(run_dir).parent.parent / 'mcp_settings.json',
        pathlib.Path(__file__).parent.parent / 'mcp_settings.json',
    ]
    for p in settings_paths:
        if p.exists():
            return json.loads(p.read_text())['url']
    return 'http://localhost:3000'


def _mcp_call(url: str, method: str, params: dict, timeout: int = 60) -> dict:
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
    resp = requests.post(url, json=payload, timeout=timeout,
                         headers={'Content-Type': 'application/json',
                                  'Accept': 'application/json, text/event-stream'})
    resp.raise_for_status()
    text = resp.text.strip()
    if text.startswith('data: '):
        return json.loads(text[6:])
    return resp.json()


def write_batch_entities(url: str, entity_list: list, batch_size: int = 50,
                          dry_run: bool = False) -> tuple:
    """
    entity_list: list of entity dicts with {model_id, x, y, z, ...}
    Returns (success_count, fail_list).
    """
    success, failures = 0, []
    for i in range(0, len(entity_list), batch_size):
        batch = entity_list[i:i+batch_size]
        if dry_run:
            print(f"  [dry-run] batch {i//batch_size+1}: {len(batch)} entities")
            success += len(batch)
            continue
        try:
            _mcp_call(url, 'entity_create_block',
                      {'entities': batch}, timeout=120)
            success += len(batch)
        except Exception as e:
            print(f"  ✗ batch {i//batch_size+1} failed: {e}")
            failures.extend(batch)
        time.sleep(0.2)  # rate limit

    return success, failures


BATCH_SIZES = {
    'road_main':         100,  # spec 9.2: 100/批
    'resource_point':     20,  # spec 9.2: 20/批（物编接口待确认，保守值）
    'monster_lair':       20,
    'dungeon_entrance':   20,
    'default':            50,  # all other types
}


def write_manifest(manifest_path: str, mcp_url: str,
                   batch_size: int = None, dry_run: bool = False) -> dict:
    """
    Main Round 3.5 writer. Reads decoration_manifest.json, writes all entities.
    batch_size: override per-type defaults if provided. Returns summary dict.
    """
    manifest = json.loads(pathlib.Path(manifest_path).read_text(encoding='utf-8'))
    elements = manifest['elements']

    # Write order: roads → bridges → game_nodes → buildings → rocks → forests
    ORDER = ['road_main', 'bridge',
             'resource_point', 'monster_lair', 'dungeon_entrance',
             'building_common', 'building_landmark',
             'rock_cluster',
             'forest_sparse', 'forest_medium', 'forest_dense']

    total_ok, total_fail = 0, []

    for elem_type in ORDER:
        batch_elems = [e for e in elements
                       if e['type'] == elem_type and e['status'] in ('pending', 'modified')]
        if not batch_elems:
            continue

        # Per-type batch size (spec Section 9.2)
        effective_batch = batch_size or BATCH_SIZES.get(elem_type, BATCH_SIZES['default'])

        print(f"\n→ 写入 {elem_type} ({len(batch_elems)} 个, batch={effective_batch})...")

        # Build entity list per element, track elem→entity mapping for status update
        elem_entity_ranges = []  # list of (elem, start_idx, end_idx)
        entity_list = []

        for elem in batch_elems:
            shape = elem['shape']
            model_ids = elem.get('model_ids', [])
            if not model_ids:
                elem['status'] = 'skipped'
                continue

            start = len(entity_list)

            if shape == 'area':
                cx, cz = elem['grid_pos']['x'], elem['grid_pos']['z']
                radius  = elem.get('radius', 5)
                density = elem.get('density', 'medium')
                positions = poisson_disk_positions(cx, cz, radius, density)
                for px, pz in positions:
                    mid = random.choice(model_ids)
                    wx = px * 2 - (manifest['meta']['grid_size']['w'] - 1)
                    wz = pz * 2 - (manifest['meta']['grid_size']['h'] - 1)
                    entity_list.append({'model_id': mid, 'x': wx, 'y': 0, 'z': wz})

            elif shape == 'point':
                wp = elem['world_pos']
                mid = random.choice(model_ids)
                entity_list.append({'model_id': mid, 'x': wp['x'], 'y': 0, 'z': wp['z']})

            elif shape == 'path':
                tiles = interpolate_path(elem.get('waypoints', []),
                                         width=elem.get('width', 2))
                gw = manifest['meta']['grid_size']['w']
                gh = manifest['meta']['grid_size']['h']
                for t in tiles:
                    mid = model_ids[0]
                    wx = t['x'] * 2 - (gw - 1)
                    wz = t['z'] * 2 - (gh - 1)
                    entity_list.append({'model_id': mid, 'x': wx, 'y': 0, 'z': wz})

            elem_entity_ranges.append((elem, start, len(entity_list)))

        ok, fail = write_batch_entities(mcp_url, entity_list,
                                         batch_size=effective_batch, dry_run=dry_run)
        total_ok += ok
        total_fail.extend(fail)

        # Update status per element based on whether its entity range overlaps failures
        failed_indices = set()
        for i, fe in enumerate(fail):
            # fail list contains entity dicts in order; map back to indices
            failed_indices.add(entity_list.index(fe) if fe in entity_list else -1)

        for elem, start, end in elem_entity_ranges:
            elem_range = set(range(start, end))
            if elem_range & failed_indices:
                elem['status'] = 'failed'
            else:
                elem['status'] = 'written'

    # Save updated manifest
    pathlib.Path(manifest_path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    # Save failed report
    if total_fail:
        fail_path = str(pathlib.Path(manifest_path).parent / 'failed_entities.json')
        pathlib.Path(fail_path).write_text(
            json.dumps({'failed': total_fail}, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    print(f"\n=== Round 3.5 写入完成 ===")
    print(f"  ✓ 成功: {total_ok}")
    print(f"  ✗ 失败: {len(total_fail)}")
    return {'success': total_ok, 'fail': len(total_fail)}


def main():
    parser = argparse.ArgumentParser(description='Round 3.5 - MCP entity batch write')
    parser.add_argument('manifest', help='Path to decoration_manifest.json')
    parser.add_argument('--url',        default=None)
    parser.add_argument('--batch-size', type=int, default=50)
    parser.add_argument('--dry-run',    action='store_true')
    args = parser.parse_args()

    run_dir = str(pathlib.Path(args.manifest).parent)
    url = args.url or _load_mcp_url(run_dir)
    write_manifest(args.manifest, url, args.batch_size, args.dry_run)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 验证脚本语法正确**

```bash
python -c "import scripts.mcp_round3_writer; print('syntax OK')"
```

或直接：

```bash
python scripts/mcp_round3_writer.py --help
```

期望：显示 usage 帮助，无报错

- [ ] **Step 3: 运行全部测试**

```bash
python -m pytest tests/ -v
```

期望：所有测试通过

---

## Task 10: 冒烟测试 — 端到端 dry-run

**Files:** 无新文件，验证三个脚本串联运行

- [ ] **Step 1: 准备最小测试数据**

在 `output/test_r3/` 目录创建最小测试数据：

```python
# 在项目根目录运行此代码块（一次性手工执行）
import numpy as np, json, pathlib
out = pathlib.Path('output/test_r3')
out.mkdir(parents=True, exist_ok=True)

H, W = 20, 20
np.save(str(out / 'height_grid.npy'),    np.zeros((H, W), dtype=np.int32))
np.save(str(out / 'water_mask_grid.npy'), np.zeros((H, W), dtype=np.uint8))
np.save(str(out / 'water_type_grid.npy'), np.zeros((H, W), dtype=np.int8))
(out / 'spatial_analysis.json').write_text(json.dumps({
    "resource_points": [{"x": 10, "z": 10}],
    "monster_lairs": [], "dungeon_entrances": [], "bridge_candidates": []
}), encoding='utf-8')
print("测试数据已创建")
```

- [ ] **Step 2: 运行 gen_gray_context.py**

```bash
python scripts/gen_gray_context.py output/test_r3
```

期望：`✓ gray_context.png saved → output/test_r3/gray_context.png  (20×20px)`

验证文件存在：

```bash
python -c "from PIL import Image; img=Image.open('output/test_r3/gray_context.png'); print(img.size, img.mode)"
```

期望：`(20, 20) RGB`

- [ ] **Step 3: 创建合成装饰设计图（代替 GPT Image 2 输出）**

```python
# 手工创建合成测试图
import numpy as np
from PIL import Image
import pathlib

arr = np.full((20, 20, 3), 128, dtype=np.uint8)   # gray background
arr[1:11, 1:11] = [20, 160, 20]                    # forest_medium 10x10 (rows 1-10, cols 1-10)
arr[14:17, 14:17] = [220, 160, 20]                 # building_common 3x3 (rows 14-16)
arr[13, 2:18] = [220, 50, 20]                      # road_main row 13（不与森林重叠）

pathlib.Path('output/test_r3/decoration_design.png').parent.mkdir(exist_ok=True)
Image.fromarray(arr).save('output/test_r3/decoration_design.png')
print("合成装饰图已创建")
```

- [ ] **Step 4: 运行 cv_decoration_extract.py**

```bash
python scripts/cv_decoration_extract.py output/test_r3 --theme default
```

期望：
```
✓ decoration_manifest.json → N 个元素
```

验证 manifest 内容：

```bash
python -c "
import json
m = json.load(open('output/test_r3/decoration_manifest.json', encoding='utf-8'))
print('元素总数:', m['meta']['total_elements'])
print('类型分布:', m['summary'])
"
```

期望：包含 `forest_medium`、`building_common`、`road_main`

- [ ] **Step 5: 运行 mcp_round3_writer.py dry-run**

```bash
python scripts/mcp_round3_writer.py output/test_r3/decoration_manifest.json --dry-run
```

期望：
```
→ 写入 road_main ...
  [dry-run] batch 1: N entities
→ 写入 building_common ...
...
=== Round 3.5 写入完成 ===
  ✓ 成功: N
  ✗ 失败: 0
```

---

## Task 11: SKILL.md — 补充 Round 3 说明

**Files:**
- Modify: `SKILL.md`

- [ ] **Step 1: 在 SKILL.md 中找到 Round 2 结尾处，追加 Round 3 章节**

在 `SKILL.md` 的 Round 2 说明后追加以下内容（保留原有格式风格）：

```markdown
## Round 3：装饰实体层

> **前置条件：** Round 1 和 Round 2 必须已完成（需要 height_grid.npy、water_mask_grid.npy、water_type_grid.npy、spatial_analysis.json）

### Step 3.1：生成灰度上下文图

```bash
python scripts/gen_gray_context.py output/{run_id}
```

输出：`output/{run_id}/gray_context.png`

### Step 3.2：AI 装饰设计图（GPT Image 2）

使用 `gray_context.png` 作为底图，通过 GPT Image 2 inpainting 生成装饰设计图。

**严格遵守颜色语义协议（references/color_protocol_v1.json）：**

| 元素类型 | RGB | 形状 | 最小尺寸 |
|---------|-----|------|---------|
| forest_sparse | (100, 210, 50) | 实心色块 | 6×6格 |
| forest_medium | (20, 160, 20) | 实心色块 | 8×8格 |
| forest_dense | (0, 90, 0) | 实心色块 | 10×10格 |
| rock_cluster | (0, 200, 200) | 实心色块 | 4×4格 |
| building_common | (220, 160, 20) | 3×3方块 | 3×3格 |
| building_landmark | (200, 20, 120) | 3×3方块 | 3×3格 |
| resource_point | (255, 210, 0) | 3×3方块 | 3×3格 |
| monster_lair | (150, 0, 200) | 3×3方块 | 3×3格 |
| dungeon_entrance | (70, 0, 150) | 3×3方块 | 3×3格 |
| road_main | (220, 50, 20) | 细线 2-3格宽 | 长≥10格 |
| bridge | (0, 60, 220) | 3×3方块 | 3×3格 |

保存输出为 `output/{run_id}/decoration_design.png`

**注意：** Step 3.2 完成后，运行以下命令强制重绘游戏节点位置（防止 AI 忽略坐标约束）：

```python
# scripts/gen_gray_context.py 中已有 overlay_candidates 函数，直接复用：
import json, pathlib
from PIL import Image
from gen_gray_context import overlay_candidates

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
print("✓ 游戏节点位置已强制覆盖")
```

### Step 3.3：CV 元素提取

```bash
python scripts/cv_decoration_extract.py output/{run_id} --theme {theme}
```

可选主题：`grassland`、`autumn`、`desert`、`ice_snow`、`default`

输出：`output/{run_id}/decoration_manifest.json`

检查警告日志：
- `unknown_pixels.log` — 未识别颜色（距离 > 60）
- `shape_warnings.log` — 尺寸不足被跳过的元素

### Step 3.4：查看并修改元素清单

读取 `decoration_manifest.json`，按需修改元素：

**查看清单：**
```python
import json
m = json.load(open('output/{run_id}/decoration_manifest.json', encoding='utf-8'))
print(m['summary'])
for e in m['elements']:
    print(e['id'], e['type'], e['grid_pos'])
```

**修改元素（直接编辑 JSON 或通过 AI 指令）：**
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
- `--batch-size N`：每批实体数（默认 50）
- `--url URL`：MCP Server 地址（默认从 mcp_settings.json 读取）

输出：更新后的 `decoration_manifest.json`（status 字段变为 written/failed）

### ⚠️ 注意事项

- Round 2 的 `cv_vegetation_fill.py` 在 Round 3 流程中**不再调用**
- 游戏节点（resource_point、monster_lair、dungeon_entrance）的物编实体 ID 待确认；当前版本以 `entity_create_block` + 占位模型写入
- 超大地图（>512×512格）的装饰设计图需分块生成后手动拼合，再运行 cv_decoration_extract.py
```

- [ ] **Step 2: 验证 SKILL.md 格式正确**

```bash
python -c "
with open('SKILL.md', encoding='utf-8') as f:
    content = f.read()
assert 'Round 3' in content
assert 'gen_gray_context' in content
assert 'cv_decoration_extract' in content
assert 'mcp_round3_writer' in content
print('SKILL.md 验证通过')
"
```

期望：`SKILL.md 验证通过`

---

## 完成验收标准

- [ ] `python -m pytest tests/ -v` 全部通过
- [ ] `python scripts/gen_gray_context.py output/test_r3` 输出合法 PNG
- [ ] `python scripts/cv_decoration_extract.py output/test_r3` 输出包含正确元素类型的 manifest
- [ ] `python scripts/mcp_round3_writer.py output/test_r3/decoration_manifest.json --dry-run` 无报错
- [ ] `shape_warnings.log` 和 `unknown_pixels.log` 在有问题时正确生成
- [ ] SKILL.md 包含完整 Round 3 章节
