#!/usr/bin/env python3
"""
Y3 Terrain Evolution - Procedural Terrain Generator

生成流程：
1. FBM 噪声 → 连续高度图 (hill_map)
2. 高度阈值切割 → 悬崖台阶 (cliff_map)
3. 低洼填水 → 水域类型 (water_map)
4. 梯度流 → 河流 (river paths)
5. 随机断层 → 裂隙 (crack_map)
6. 悬崖边缘检测 → 斜坡 (slope_map)
7. 高度+水域距离 → 生物群系 (biome_map)
"""

import numpy as np
import json
import argparse
from pathlib import Path
from collections import deque


# ---------------------------------------------------------------------------
# FBM Noise
# ---------------------------------------------------------------------------

def generate_fbm(width, height, seed, octaves=6, base_scale=8):
    """分形布朗运动噪声，仅依赖 numpy。"""
    rng = np.random.RandomState(seed)
    result = np.zeros((height, width), dtype=np.float64)
    total_amplitude = 0.0
    amplitude = 1.0

    y_norm = np.arange(height, dtype=np.float64) / (height - 1)
    x_norm = np.arange(width,  dtype=np.float64) / (width  - 1)

    for i in range(octaves):
        freq = 2 ** i
        gh = max(2, height * freq // base_scale + 2)
        gw = max(2, width  * freq // base_scale + 2)
        grid = rng.rand(gh, gw).astype(np.float64)

        gy = y_norm * (gh - 1)
        gx = x_norm * (gw  - 1)

        gy0 = np.clip(gy.astype(int), 0, gh - 2)
        gx0 = np.clip(gx.astype(int), 0, gw - 2)
        gy1, gx1 = gy0 + 1, gx0 + 1

        fy = (gy - gy0)[:, np.newaxis]   # (H, 1)
        fx = (gx - gx0)[np.newaxis, :]   # (1, W)

        v = (grid[gy0[:, np.newaxis], gx0[np.newaxis, :]] * (1 - fy) * (1 - fx)
           + grid[gy0[:, np.newaxis], gx1[np.newaxis, :]] * (1 - fy) * fx
           + grid[gy1[:, np.newaxis], gx0[np.newaxis, :]] * fy       * (1 - fx)
           + grid[gy1[:, np.newaxis], gx1[np.newaxis, :]] * fy       * fx)

        result += amplitude * v
        total_amplitude += amplitude
        amplitude *= 0.5

    result /= total_amplitude
    mn, mx = result.min(), result.max()
    if mx > mn:
        result = (result - mn) / (mx - mn)
    return result


def apply_shaping(height_map, gen_cfg):
    """地形塑形：岛屿模式 / 大陆模式。"""
    h, w = height_map.shape
    if gen_cfg.get("island_mode", False):
        cy, cx = h / 2.0, w / 2.0
        Y, X = np.mgrid[0:h, 0:w].astype(np.float64)
        dist = np.sqrt(((Y - cy) / cy) ** 2 + ((X - cx) / cx) ** 2)
        falloff = np.clip(1.0 - dist * 1.3, 0, 1) ** 1.5
        height_map = height_map * falloff

    mn, mx = height_map.min(), height_map.max()
    if mx > mn:
        height_map = (height_map - mn) / (mx - mn)
    return height_map


# ---------------------------------------------------------------------------
# Cliff Map
# ---------------------------------------------------------------------------

def build_cliff_map(height_map, gen_cfg):
    """连续高度 → 离散悬崖台阶 (0 = 无台阶)。"""
    water_level  = gen_cfg.get("water_level", 0.32)
    max_level    = gen_cfg.get("max_cliff_level", 5)

    cliff_map = np.zeros(height_map.shape, dtype=np.int32)
    land_mask = height_map > water_level

    if land_mask.any():
        lh = height_map[land_mask]
        lo, hi = lh.min(), lh.max()
        normed = (lh - lo) / (hi - lo + 1e-8)
        # 指数分布：低台阶多，高台阶少
        levels = np.floor(normed ** 1.6 * max_level).astype(np.int32)
        cliff_map[land_mask] = levels

    return cliff_map


# ---------------------------------------------------------------------------
# Water Map
# ---------------------------------------------------------------------------

def _label_connected(binary_map):
    """BFS 连通区域标注，返回标签矩阵 (0=背景)。"""
    h, w = binary_map.shape
    labels = np.zeros((h, w), dtype=np.int32)
    cur = 0
    for sy in range(h):
        for sx in range(w):
            if binary_map[sy, sx] and labels[sy, sx] == 0:
                cur += 1
                q = deque([(sy, sx)])
                labels[sy, sx] = cur
                while q:
                    y, x = q.popleft()
                    for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
                        ny, nx = y+dy, x+dx
                        if 0 <= ny < h and 0 <= nx < w and binary_map[ny,nx] and labels[ny,nx] == 0:
                            labels[ny,nx] = cur
                            q.append((ny, nx))
    return labels


def _touches_edge(mask, h, w):
    return bool(mask[0,:].any() or mask[-1,:].any() or mask[:,0].any() or mask[:,-1].any())


def build_water_map(height_map, gen_cfg):
    """高度图 → 水域类型数组 ('none'/'deep'/'shallow'/'plain')。"""
    water_level = gen_cfg.get("water_level", 0.32)
    shallow_thr = gen_cfg.get("shallow_threshold", 0.06)

    h, w = height_map.shape
    water_map = np.full((h, w), "none", dtype=object)

    deep_mask    = height_map < (water_level - shallow_thr)
    shallow_mask = (height_map >= (water_level - shallow_thr)) & (height_map < water_level)
    water_map[deep_mask]    = "deep"
    water_map[shallow_mask] = "shallow"

    # 大面积深水 → plain（湖面/海面）
    labeled = _label_connected(deep_mask)
    if labeled.max() > 0:
        total = h * w
        unique, counts = np.unique(labeled[labeled > 0], return_counts=True)
        for lbl, cnt in zip(unique, counts):
            if cnt > total * 0.018:          # 超过 1.8% 的大水体
                water_map[labeled == lbl] = "plain"

    return water_map


# ---------------------------------------------------------------------------
# Rivers
# ---------------------------------------------------------------------------

def generate_rivers(height_map, water_map, gen_cfg, seed):
    """梯度流河流生成，返回 (river_mask, 更新后的 water_map)。"""
    rng = np.random.RandomState(seed + 200)
    h, w = height_map.shape
    river_mask = np.zeros((h, w), dtype=bool)

    river_count = gen_cfg.get("river_count", 3)
    high_land = (height_map > 0.65) & (water_map == "none")
    sources = np.argwhere(high_land)

    if len(sources) == 0:
        return river_mask, water_map

    n = min(river_count, len(sources))
    chosen = rng.choice(len(sources), n, replace=False)

    for idx in chosen:
        sy, sx = sources[idx]
        cy, cx = int(sy), int(sx)

        for _ in range(300):
            river_mask[cy, cx] = True
            if water_map[cy, cx] != "none":
                break

            # 找最低邻居（含对角线，加小随机扰动）
            best_h = height_map[cy, cx]
            best_y, best_x = cy, cx

            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = cy + dy, cx + dx
                    if not (0 <= ny < h and 0 <= nx < w):
                        continue
                    nh = height_map[ny, nx] + rng.uniform(0, 0.03)
                    if nh < best_h:
                        best_h = nh
                        best_y, best_x = ny, nx

            if best_y == cy and best_x == cx:
                break          # 陷入局部最低点
            cy, cx = best_y, best_x

    # 将河流格子设为 shallow water（如果当前是陆地）
    wm = water_map.copy()
    wm[river_mask & (water_map == "none")] = "shallow"
    return river_mask, wm


# ---------------------------------------------------------------------------
# Cracks
# ---------------------------------------------------------------------------

def generate_cracks(height_map, water_map, gen_cfg, seed):
    """随机断层线生成裂隙（Bresenham 直线 + 随机游走）。"""
    rng = np.random.RandomState(seed + 300)
    h, w = height_map.shape
    crack_map = np.zeros((h, w), dtype=bool)

    if not gen_cfg.get("allow_cracks", True):
        return crack_map

    count  = gen_cfg.get("crack_count",  4)
    length = gen_cfg.get("crack_length", 25)

    for _ in range(count):
        # 随机起点（避开水域和地图边缘）
        for _ in range(100):
            sy = rng.randint(h // 5, 4 * h // 5)
            sx = rng.randint(w // 5, 4 * w // 5)
            if water_map[sy, sx] == "none":
                break
        else:
            continue

        angle = rng.uniform(0, 2 * np.pi)
        cy, cx = float(sy), float(sx)

        for _ in range(length):
            iy, ix = int(round(cy)), int(round(cx))
            if not (0 <= iy < h and 0 <= ix < w):
                break
            if water_map[iy, ix] != "none":
                break
            crack_map[iy, ix] = True

            angle += rng.uniform(-0.4, 0.4)    # 轻微随机游走
            cy += np.sin(angle) * 1.2
            cx += np.cos(angle) * 1.2

    return crack_map


# ---------------------------------------------------------------------------
# Slope Map
# ---------------------------------------------------------------------------

def build_slope_map(cliff_map, water_map, gen_cfg):
    """悬崖边缘检测 → 斜坡 flat 值（'none'/'1'/'2'/'3'）。

    Y3 斜坡系统（y3-terrain-basics.md §斜坡体系）：
      flat='1'：X 轴横向斜坡（E/W 方向相邻高差 = 1 个内部 level = API height 差 2）
      flat='2'：Z 轴纵向斜坡（N/S 方向相邻高差 = 1 个内部 level）
      flat='3'：角落斜坡（X 轴和 Z 轴均满足）
    激活条件：cliff_map 相邻格差值 >= 1（对应 API terrain_height 差 2，Y3 斜坡触发条件）
    斜坡需主动写入（terrain_set_road_block），不依赖引擎自动生成。
    """
    if not gen_cfg.get("allow_slopes", True):
        h, w = cliff_map.shape
        return np.full((h, w), "none", dtype=object)

    h, w = cliff_map.shape
    land = (water_map == "none")

    # (axis, dy, dx)：axis='x' → flat=1（横向），axis='z' → flat=2（纵向）
    dirs = [("z", -1, 0), ("z", 1, 0), ("x", 0, 1), ("x", 0, -1)]

    has_x = np.zeros((h, w), dtype=bool)
    has_z = np.zeros((h, w), dtype=bool)

    for axis, dy, dx in dirs:
        if dy == -1:
            nbr   = np.pad(cliff_map,            ((0,1),(0,0)), mode='edge'    )[1:,  :]
            nbr_l = np.pad(land.astype(np.int8), ((0,1),(0,0)), mode='constant')[1:,  :]
        elif dy == 1:
            nbr   = np.pad(cliff_map,            ((1,0),(0,0)), mode='edge'    )[:-1, :]
            nbr_l = np.pad(land.astype(np.int8), ((1,0),(0,0)), mode='constant')[:-1, :]
        elif dx == -1:
            nbr   = np.pad(cliff_map,            ((0,0),(0,1)), mode='edge'    )[:,  1:]
            nbr_l = np.pad(land.astype(np.int8), ((0,0),(0,1)), mode='constant')[:,  1:]
        else:
            nbr   = np.pad(cliff_map,            ((0,0),(1,0)), mode='edge'    )[:, :-1]
            nbr_l = np.pad(land.astype(np.int8), ((0,0),(1,0)), mode='constant')[:, :-1]

        cond = land & (nbr_l == 1) & ((cliff_map - nbr) >= 1)
        if axis == "x":
            has_x |= cond
        else:
            has_z |= cond

    slope_map = np.full((h, w), "none", dtype=object)
    slope_map[has_x & ~has_z] = "1"   # X 轴横向
    slope_map[~has_x & has_z] = "2"   # Z 轴纵向
    slope_map[has_x & has_z]  = "3"   # 角落

    return slope_map


# ---------------------------------------------------------------------------
# Biome Classification
# ---------------------------------------------------------------------------

def _distance_transform_bfs(mask, h, w):
    """BFS 距离变换，返回每格到最近 True 格子的格子数。"""
    dist = np.full((h, w), np.inf, dtype=np.float64)
    q = deque()
    ys, xs = np.where(mask)
    for y, x in zip(ys, xs):
        dist[y, x] = 0.0
        q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
            ny, nx = y+dy, x+dx
            if 0 <= ny < h and 0 <= nx < w and dist[ny,nx] == np.inf:
                dist[ny,nx] = dist[y,x] + 1.0
                q.append((ny, nx))
    return dist


def classify_biomes(height_map, water_map, cliff_map, gen_cfg):
    """height + water_distance + cliff → 生物群系标签。"""
    h, w = height_map.shape
    water_mask = (water_map != "none")
    land_mask  = ~water_mask
    dist_water = _distance_transform_bfs(water_mask, h, w)

    biome_map = np.full((h, w), "plain", dtype=object)

    # 从低优先级到高优先级覆盖写
    biome_map[land_mask & (dist_water < 10)] = "wetland"
    biome_map[land_mask & (dist_water < 4)]  = "coastal"
    biome_map[land_mask & (height_map > 0.48)] = "forest"
    biome_map[land_mask & (height_map > 0.60)] = "hill"
    biome_map[land_mask & (height_map > 0.60) & (cliff_map >= 2)] = "cliff"
    biome_map[land_mask & (height_map > 0.78)] = "mountain"
    biome_map[water_mask] = "water"

    return biome_map


# ---------------------------------------------------------------------------
# Save / Load
# ---------------------------------------------------------------------------

def save_world_state(output_dir, state_dict):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = Path(output_dir) / "world_state.json"

    def _cvt(v):
        if isinstance(v, np.ndarray):
            return v.tolist()
        return v

    serializable = {k: _cvt(v) for k, v in state_dict.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False)
    print(f"[generate_terrain] World state saved → {path}")
    return str(path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",        required=True, help="world_config.json 路径")
    parser.add_argument("--output-dir",    required=True, help="输出目录")
    parser.add_argument("--seed-override", type=int,      help="覆盖配置中的 seed")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    seed   = args.seed_override if args.seed_override is not None else config.get("seed", 42)
    W      = config["map_width"]
    H      = config["map_height"]
    gen    = config.get("generation_rules", {})

    print(f"[generate_terrain] {W}x{H} seed={seed}")

    print("  [1/7] FBM 高度图...")
    hill_map = generate_fbm(W, H, seed, octaves=gen.get("fbm_octaves", 6))
    hill_map = apply_shaping(hill_map, gen)

    print("  [2/7] 悬崖台阶...")
    cliff_map = build_cliff_map(hill_map, gen)

    print("  [3/7] 水域...")
    water_map = build_water_map(hill_map, gen)

    print("  [4/7] 河流...")
    river_mask, water_map = generate_rivers(hill_map, water_map, gen, seed)

    print("  [5/7] 裂隙...")
    crack_map = generate_cracks(hill_map, water_map, gen, seed)

    print("  [6/7] 斜坡检测...")
    slope_map = build_slope_map(cliff_map, water_map, gen)

    print("  [7/7] 生物群系...")
    biome_map = classify_biomes(hill_map, water_map, cliff_map, gen)

    world_state = {
        "width":      W,
        "height":     H,
        "seed":       seed,
        "era":        "terrain",
        "iteration":  0,
        "hill_map":   hill_map,
        "cliff_map":  cliff_map,
        "water_map":  water_map,
        "slope_map":  slope_map,
        "crack_map":  crack_map,
        "river_map":  river_mask,
        "biome_map":  biome_map,
    }

    save_world_state(args.output_dir, world_state)
    print("[generate_terrain] 完成")


if __name__ == "__main__":
    main()
