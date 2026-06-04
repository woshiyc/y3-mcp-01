# scripts/mcp_round3_writer.py
import json, math, random, pathlib, time
import argparse

DENSITY_FACTORS = {'sparse': 0.15, 'medium': 0.30, 'dense': 0.50}


MAX_ENTITIES_PER_ELEMENT = 400   # 单个元素最多展开实体数，防止超大色块爆量

def poisson_disk_positions(center_x: float, center_z: float,
                            radius: float, density: str,
                            min_spacing: float = 1.5,
                            max_attempts: int = 20) -> list:
    """
    Generate N positions within circle using Poisson Disk Sampling.
    Returns list of (x, z) tuples. Capped at MAX_ENTITIES_PER_ELEMENT.
    """
    factor = DENSITY_FACTORS.get(density, 0.30)
    target_n = min(
        max(1, int(math.pi * radius**2 * factor)),
        MAX_ENTITIES_PER_ELEMENT
    )
    placed = []

    for _ in range(target_n * max_attempts):
        if len(placed) >= target_n:
            break
        angle = random.uniform(0, 2 * math.pi)
        r = random.uniform(0, radius)
        x = center_x + r * math.cos(angle)
        z = center_z + r * math.sin(angle)
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

    tiles = []
    seen = set()
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
                key = (cx, cz + dw)
                if key not in seen:
                    seen.add(key)
                    tiles.append({'x': cx, 'z': cz + dw})

    return tiles


try:
    import requests
except ImportError:
    requests = None


# Per-type batch sizes (spec Section 9.2)
BATCH_SIZES = {
    'road_main':        100,
    'resource_point':    20,
    'monster_lair':      20,
    'dungeon_entrance':  20,
    'default':           50,
}


def _load_mcp_url(run_dir: str) -> str:
    """Read MCP URL from mcp_settings.json."""
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
    entity_list: list of entity dicts with {model_id, x, y, z}
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
            print(f"  Batch {i//batch_size+1} failed: {e}")
            failures.extend(batch)
        time.sleep(0.2)

    return success, failures


def _load_terrain_grids(manifest_path: str):
    """加载高度网格和水域掩码，并预计算水域距离图（加速位置验证）。"""
    run_dir = pathlib.Path(manifest_path).parent
    height_grid = water_mask = water_dist = None
    try:
        import numpy as _np
        from scipy.ndimage import distance_transform_edt as _dte
        hp = run_dir / 'height_grid.npy'
        wp = run_dir / 'water_mask_grid.npy'
        if hp.exists(): height_grid = _np.load(str(hp)).astype(int)
        if wp.exists():
            water_mask = _np.load(str(wp)).astype(bool)
            # 预计算每个陆地格到最近水域的距离（格数），O(N)
            water_dist = _dte(~water_mask)
    except Exception:
        pass
    return height_grid, water_mask, water_dist


def _pos_valid(px, pz, elem_type, height_grid, water_mask, water_dist=None):
    """检查 Poisson 位置是否符合地形逻辑，使用预计算距离图加速。"""
    if height_grid is None:
        return True
    H, W = height_grid.shape
    r, c = int(round(pz)), int(round(px))
    if not (0 <= r < H and 0 <= c < W):
        return False
    if water_mask is not None and water_mask[r, c]:
        return False
    h = int(height_grid[r, c])
    if elem_type in ('forest_dense', 'forest_medium') and h > 2:
        return False
    if elem_type == 'forest_sparse' and h > 4:
        return False
    if elem_type == 'rock_cluster' and h == 0:
        # 利用预计算距离图：到水域距离>3格则跳过
        dist = float(water_dist[r, c]) if water_dist is not None else 0
        if dist > 3:
            return False
    return True


def write_manifest(manifest_path: str, mcp_url: str,
                   batch_size: int = None, dry_run: bool = False) -> dict:
    """
    Main Round 3.5 writer. Reads decoration_manifest.json, writes all entities.
    Returns summary dict.
    """
    manifest = json.loads(pathlib.Path(manifest_path).read_text(encoding='utf-8'))
    elements = manifest['elements']
    height_grid, water_mask, water_dist = _load_terrain_grids(manifest_path)

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

        effective_batch = batch_size or BATCH_SIZES.get(elem_type, BATCH_SIZES['default'])
        print(f"\n Writing {elem_type} ({len(batch_elems)} elements, batch={effective_batch})...")

        elem_entity_ranges = []
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
                # 过滤不符合地形逻辑的采样点
                positions = [
                    (px, pz) for px, pz in positions
                    if _pos_valid(px, pz, elem_type, height_grid, water_mask, water_dist)
                ]
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

        # Per-element status update
        fail_set = set(id(fe) for fe in fail)
        for elem, start, end in elem_entity_ranges:
            elem_entities = entity_list[start:end]
            if any(id(fe) in fail_set for fe in elem_entities):
                elem['status'] = 'failed'
            else:
                elem['status'] = 'written'

    # Save updated manifest
    pathlib.Path(manifest_path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    if total_fail:
        fail_path = str(pathlib.Path(manifest_path).parent / 'failed_entities.json')
        pathlib.Path(fail_path).write_text(
            json.dumps({'failed': total_fail}, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    print(f"\n=== Round 3.5 Complete ===")
    print(f"  OK:   {total_ok}")
    print(f"  Fail: {len(total_fail)}")
    return {'success': total_ok, 'fail': len(total_fail)}


def main():
    parser = argparse.ArgumentParser(description='Round 3.5 - MCP entity batch write')
    parser.add_argument('manifest', help='Path to decoration_manifest.json')
    parser.add_argument('--url',        default=None)
    parser.add_argument('--batch-size', type=int, default=None)
    parser.add_argument('--dry-run',    action='store_true')
    args = parser.parse_args()

    run_dir = str(pathlib.Path(args.manifest).parent)
    url = args.url or _load_mcp_url(run_dir)
    write_manifest(args.manifest, url, args.batch_size, args.dry_run)


if __name__ == '__main__':
    main()
