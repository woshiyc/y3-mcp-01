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
    """Returns (element_type, distance). Caller must filter gray pixels first."""
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
    """Load image and resize to exact grid dimensions using nearest-neighbor interpolation."""
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {img_path}")
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    if img_rgb.shape[1] != target_w or img_rgb.shape[0] != target_h:
        img_rgb = cv2.resize(img_rgb, (target_w, target_h),
                             interpolation=cv2.INTER_NEAREST)
    return img_rgb


# ---------------------------------------------------------------------------
# Task 5: 面状元素 DBSCAN 聚类
# ---------------------------------------------------------------------------

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
        dists = np.sqrt((cluster_pts[:, 0] - center_z)**2 +
                        (cluster_pts[:, 1] - center_x)**2)
        radius = float(np.max(dists))
        clusters.append((center_x, center_z, max(radius, 1.0)))

    return clusters


# ---------------------------------------------------------------------------
# Task 6: 点状元素连通域 + 线状骨架化
# ---------------------------------------------------------------------------

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
        cx = float(centroids[i, 0])  # col -> x
        cz = float(centroids[i, 1])  # row -> z
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

    skel_coords = skel_coords[np.lexsort((skel_coords[:, 1], skel_coords[:, 0]))]
    sampled = skel_coords[::sample_step]
    waypoints = [(int(c[1]), int(c[0])) for c in sampled]  # (x, z)
    return waypoints


# ---------------------------------------------------------------------------
# Task 7: 模型分配 + manifest 输出 + 主入口
# ---------------------------------------------------------------------------

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

    # 加载水域掩码（如果存在），用于过滤水域内的装饰像素
    run_dir = pathlib.Path(output_path).parent
    water_mask = None
    water_mask_path = run_dir / 'water_mask_grid.npy'
    if water_mask_path.exists():
        raw = np.load(str(water_mask_path))
        # 如果水域掩码分辨率与图像不一致则跳过过滤
        if raw.shape == (grid_h, grid_w):
            water_mask = raw.astype(bool)

    # Per-type pixel lists（不在此处过滤水域，改为聚类后按中心点过滤）
    type_pixels: dict = {k: [] for k in protocol['elements']}
    unknown_log = []

    # 非面状元素（点状/路径）仍在像素级过滤水域（它们不存在"水边合理"问题）
    AREA_SHAPES = {'area'}

    for r in range(grid_h):
        for c in range(grid_w):
            R, G, B = int(img[r, c, 0]), int(img[r, c, 1]), int(img[r, c, 2])
            if is_gray(R, G, B, threshold):
                continue
            elem_type, dist = classify_pixel(R, G, B, protocol)
            if dist > unk_thresh:
                unknown_log.append(f"({c},{r}) RGB=({R},{G},{B}) dist={dist:.1f}")
                continue
            shape = protocol['elements'].get(elem_type, {}).get('shape', 'point')
            # 点状/路径元素：直接过滤水域像素
            if shape not in AREA_SHAPES:
                if water_mask is not None and water_mask[r, c]:
                    # 桥梁例外：允许在水域
                    if elem_type != 'bridge':
                        continue
            type_pixels[elem_type].append((r, c))

    print(f"  像素分类完成，面状元素保留水边像素参与聚类")

    # 加载高度网格，用于高度感知验证和密度分配
    height_grid = None
    height_path = run_dir / 'height_grid.npy'
    if height_path.exists():
        hg_raw = np.load(str(height_path))
        if hg_raw.shape == (grid_h, grid_w):
            height_grid = hg_raw.astype(np.int32)

    # Write unknown log
    log_dir = pathlib.Path(output_path).parent
    if unknown_log:
        (log_dir / 'unknown_pixels.log').write_text('\n'.join(unknown_log), encoding='utf-8')

    elements = []
    shape_warnings = []
    height_warnings = []
    elem_id = 0

    # 元素类型允许的最大高度（超出则跳过或降级）
    _MAX_H = {
        'forest_dense':  2,   # 密林只在平地/低丘
        'forest_medium': 2,   # 中密林只在平地/低丘
        'forest_sparse': 4,   # 稀疏林可到山腰
        'rock_cluster':  6,   # 山石可到山顶
    }
    # 元素类型要求的最低高度
    _MIN_H = {
        'rock_cluster': 2,    # 山石不出现在大片平地（h=0 仅水边例外）
    }

    def _center_height(cx, cz):
        """返回格子中心处的高度值，不在格内返回 0。"""
        r, c = int(round(cz)), int(round(cx))
        if height_grid is not None and 0 <= r < grid_h and 0 <= c < grid_w:
            return int(height_grid[r, c])
        return 0

    def _near_water(cx, cz, radius=4):
        """检查中心点 radius 格内是否有水域。"""
        if water_mask is None:
            return False
        r0, c0 = int(round(cz)), int(round(cx))
        for dr in range(-radius, radius+1):
            for dc in range(-radius, radius+1):
                nr, nc = r0+dr, c0+dc
                if 0 <= nr < grid_h and 0 <= nc < grid_w and water_mask[nr, nc]:
                    return True
        return False

    def _assign_density(elem_type, cx, cz):
        """根据地形位置分配密度：水边密、山腰稀、平地中。"""
        h = _center_height(cx, cz)
        near_w = _near_water(cx, cz, radius=3)
        if 'forest' in elem_type:
            if near_w:   return 'dense'   # 水边植被最茂盛
            if h == 0:   return 'medium'  # 平地中等
            if h == 2:   return 'sparse'  # 丘陵稀疏
            return 'sparse'
        if elem_type == 'rock_cluster':
            if h >= 4:   return 'dense'   # 高山岩石密集
            return 'medium'
        return 'medium'

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
                # 高度验证
                h = _center_height(cx, cz)
                max_h = _MAX_H.get(elem_type, 6)
                min_h = _MIN_H.get(elem_type, -1)

                if h > max_h:
                    height_warnings.append(
                        f"{elem_type} at ({cx:.0f},{cz:.0f}) h={h} > max_h={max_h}, skipped")
                    continue

                # rock_cluster 在 h=0 时必须靠近水域才保留
                if elem_type == 'rock_cluster' and h < min_h:
                    if not _near_water(cx, cz, radius=3):
                        height_warnings.append(
                            f"{elem_type} at ({cx:.0f},{cz:.0f}) h={h} on flat plain far from water, skipped")
                        continue

                density = _assign_density(elem_type, cx, cz)
                elem = {
                    'id': f'e_{elem_id:04d}',
                    'type': elem_type, 'shape': 'area',
                    'grid_pos': {'x': round(cx, 1), 'z': round(cz, 1)},
                    'radius': round(radius, 1), 'density': density,
                    'terrain_h': h,
                    'model_group': model_group, 'model_ids': model_ids,
                    'world_pos': _world_pos(cx, cz, grid_w, grid_h),
                    'source_color': info['rgb'], 'status': 'pending',
                    'modified': False, 'modify_history': []
                }
                elements.append(elem); elem_id += 1
            if coords and not clusters:
                shape_warnings.append(
                    f"{elem_type}: {len(coords)} pixels found but no cluster met min_pixels={min_pix}")

        elif shape == 'point':
            mask = np.zeros((grid_h, grid_w), dtype=np.uint8)
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
        print(f"  {len(shape_warnings)} elements skipped due to insufficient size, see shape_warnings.log")

    if height_warnings:
        (log_dir / 'height_warnings.log').write_text('\n'.join(height_warnings), encoding='utf-8')
        print(f"  {len(height_warnings)} elements skipped due to height mismatch, see height_warnings.log")

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
    print(f"decoration_manifest.json -> {len(elements)} elements")
    return manifest


def load_style_logic(style: str):
    """加载风格特化逻辑模块，返回 module 或 None（使用内置规则）。"""
    if not style or style == 'default':
        return None
    skill_dir = pathlib.Path(__file__).parent.parent
    logic_path = skill_dir / 'styles' / style / 'decoration_logic.py'
    if not logic_path.exists():
        print(f"  [style] {logic_path} not found, using built-in rules")
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location(f'style_{style}', str(logic_path))
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    print(f"  [style] loaded {style} decoration_logic.py")
    return mod


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Round 3.3 - Extract decoration elements')
    parser.add_argument('run_dir',        help='output/{run_id}/ directory')
    parser.add_argument('--texture-grid', default=None, help='texture_grid.csv path')
    parser.add_argument('--theme',        default='default', help='decoration theme (model catalog key)')
    parser.add_argument('--style',        default=None,
                        help='map style folder under styles/ (e.g. dark_fantasy). '
                             'Loads style-specific rules and logic.')
    args = parser.parse_args()

    run   = pathlib.Path(args.run_dir)
    skill = pathlib.Path(__file__).parent.parent
    proto = str(skill / 'references' / 'color_protocol_v1.json')

    # 风格特化模型目录：styles/{style}/model_catalog.json 优先，否则用共享
    if args.style:
        style_catalog = skill / 'styles' / args.style / 'model_catalog.json'
        catalog = str(style_catalog) if style_catalog.exists() else \
                  str(skill / 'references' / 'decoration_model_catalog.json')
    else:
        catalog = str(skill / 'references' / 'decoration_model_catalog.json')

    # 加载风格特化逻辑
    style_mod = load_style_logic(args.style)

    if args.texture_grid:
        texture_grid = np.genfromtxt(args.texture_grid, delimiter=',', dtype=np.int32)
    else:
        texture_grid = np.zeros((1, 1), dtype=np.int32)

    hg = np.load(str(run / 'height_grid.npy'))
    grid_h, grid_w = hg.shape

    # 若有风格模块，先执行程序化布局规则（在提取前写入确定性装饰）
    if style_mod and hasattr(style_mod, 'apply_programmatic_rules'):
        deco_img = str(run / 'decoration_design.png')
        wm  = np.load(str(run / 'water_mask_grid.npy')).astype(bool)
        wt  = np.load(str(run / 'water_type_grid.npy')).astype(np.int8) \
              if (run / 'water_type_grid.npy').exists() else np.zeros_like(hg, dtype=np.int8)
        spatial = json.loads((run / 'spatial_analysis.json').read_text(encoding='utf-8')) \
                  if (run / 'spatial_analysis.json').exists() else {}

        from PIL import Image as _PIL
        _img = _PIL.open(deco_img)
        img_w, img_h = _img.size
        _img.close()
        scale = img_w // grid_w  # 推断 scale（2048/256=8）

        added = style_mod.apply_programmatic_rules(
            deco_img, hg, wm, wt, spatial, scale=scale
        )
        print(f"  [style:{args.style}] 程序化规则写入 {added} 个格子")

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
