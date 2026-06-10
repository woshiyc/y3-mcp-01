#!/usr/bin/env python3
"""
Y3 Terrain Evolution - Patch Plan Executor

将 LLM 输出的 Patch Plan（区域级指令）翻译为格子级操作，
并按照当前时代权重限制修改范围。
"""

import numpy as np
import json
import argparse
from pathlib import Path
from collections import deque
import heapq


# ---------------------------------------------------------------------------
# 区域名称 → 格子切片
# ---------------------------------------------------------------------------

REGION_MAP = {
    "northwest": lambda H, W: (slice(0, H//2),      slice(0, W//2)),
    "northeast": lambda H, W: (slice(0, H//2),      slice(W//2, W)),
    "southwest": lambda H, W: (slice(H//2, H),      slice(0, W//2)),
    "southeast": lambda H, W: (slice(H//2, H),      slice(W//2, W)),
    "north":     lambda H, W: (slice(0, H//3),      slice(0, W)),
    "south":     lambda H, W: (slice(2*H//3, H),    slice(0, W)),
    "east":      lambda H, W: (slice(0, H),          slice(2*W//3, W)),
    "west":      lambda H, W: (slice(0, H),          slice(0, W//3)),
    "center":    lambda H, W: (slice(H//4, 3*H//4), slice(W//4, 3*W//4)),
    "interior":  lambda H, W: (slice(H//5, 4*H//5), slice(W//5, 4*W//5)),
    "edge":      lambda H, W: (slice(0, H),          slice(0, W)),  # 全图，后续用边缘掩码
    "all":       lambda H, W: (slice(0, H),          slice(0, W)),
}

def get_region_mask(region_name, H, W):
    """返回布尔掩码 (H,W)，True = 属于该区域。"""
    fn = REGION_MAP.get(region_name)
    if fn is None:
        # 未知区域名 → 全图
        return np.ones((H, W), dtype=bool)
    mask = np.zeros((H, W), dtype=bool)
    rs, cs = fn(H, W)
    mask[rs, cs] = True
    if region_name == "edge":
        # 仅保留外圈
        interior = np.zeros((H, W), dtype=bool)
        interior[2:-2, 2:-2] = True
        mask = mask & ~interior
    return mask


# ---------------------------------------------------------------------------
# 平滑工具
# ---------------------------------------------------------------------------

def gaussian_blur_2d(arr, sigma=2.0):
    """纯 numpy 高斯平滑（无 scipy 依赖）。"""
    ksize = max(3, int(sigma * 3) | 1)
    half = ksize // 2
    k1d = np.exp(-np.arange(-half, half+1)**2 / (2 * sigma**2))
    k1d /= k1d.sum()
    # 行方向卷积
    padded = np.pad(arr, half, mode='edge')
    tmp = np.zeros_like(arr, dtype=np.float64)
    for i, w in enumerate(k1d):
        tmp += w * padded[half:half+arr.shape[0], i:i+arr.shape[1]]
    # 列方向卷积
    padded2 = np.pad(tmp, half, mode='edge')
    out = np.zeros_like(arr, dtype=np.float64)
    for j, w in enumerate(k1d):
        out += w * padded2[j:j+arr.shape[0], half:half+arr.shape[1]]
    return out


# ---------------------------------------------------------------------------
# 路径查找（A*）
# ---------------------------------------------------------------------------

def astar(start, goal, passable):
    """A* 寻路，返回路径坐标列表或 None。"""
    H, W = passable.shape
    if not passable[start] or not passable[goal]:
        return None

    def h(a, b): return abs(a[0]-b[0]) + abs(a[1]-b[1])

    open_set = [(h(start, goal), 0, start)]
    came_from = {}
    g = {start: 0}

    while open_set:
        _, cost, cur = heapq.heappop(open_set)
        if cur == goal:
            path = []
            while cur in came_from:
                path.append(cur)
                cur = came_from[cur]
            path.append(start)
            return path[::-1]
        for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
            ny, nx = cur[0]+dy, cur[1]+dx
            nb = (ny, nx)
            if not (0 <= ny < H and 0 <= nx < W and passable[ny, nx]):
                continue
            ng = g[cur] + 1
            if ng < g.get(nb, 1e18):
                came_from[nb] = cur
                g[nb] = ng
                heapq.heappush(open_set, (ng + h(nb, goal), ng, nb))
    return None


# ---------------------------------------------------------------------------
# 地形操作
# ---------------------------------------------------------------------------

def op_raise_height(ws, action):
    intensity = float(action.get("intensity", 0.3))
    mask = get_region_mask(action.get("region","all"), ws["height"], ws["width"])
    hill = np.array(ws["hill_map"], dtype=np.float64)
    hill[mask] = np.clip(hill[mask] + intensity * 0.5, 0, 1)
    # 轻微平滑边界
    hill = gaussian_blur_2d(hill, sigma=1.5)
    mn, mx = hill.min(), hill.max()
    ws["hill_map"] = ((hill - mn) / (mx - mn + 1e-8)).tolist()
    print(f"  raise_height({action.get('region')}, intensity={intensity})")


def op_lower_height(ws, action):
    intensity = float(action.get("intensity", 0.3))
    mask = get_region_mask(action.get("region","all"), ws["height"], ws["width"])
    hill = np.array(ws["hill_map"], dtype=np.float64)
    hill[mask] = np.clip(hill[mask] - intensity * 0.5, 0, 1)
    hill = gaussian_blur_2d(hill, sigma=1.5)
    mn, mx = hill.min(), hill.max()
    ws["hill_map"] = ((hill - mn) / (mx - mn + 1e-8)).tolist()
    print(f"  lower_height({action.get('region')}, intensity={intensity})")


def op_smooth_terrain(ws, action):
    passes = int(action.get("passes", 2))
    mask = get_region_mask(action.get("region","all"), ws["height"], ws["width"])
    hill = np.array(ws["hill_map"], dtype=np.float64)
    smoothed = hill.copy()
    for _ in range(passes):
        smoothed = gaussian_blur_2d(smoothed, sigma=2.0)
    hill[mask] = smoothed[mask]
    mn, mx = hill.min(), hill.max()
    ws["hill_map"] = ((hill - mn) / (mx - mn + 1e-8)).tolist()
    print(f"  smooth_terrain({action.get('region')}, passes={passes})")


def op_steepen_terrain(ws, action):
    intensity = float(action.get("intensity", 0.3))
    mask = get_region_mask(action.get("region","all"), ws["height"], ws["width"])
    hill = np.array(ws["hill_map"], dtype=np.float64)
    region_hill = hill[mask]
    center = region_hill.mean()
    hill[mask] = np.clip(center + (region_hill - center) * (1 + intensity), 0, 1)
    mn, mx = hill.min(), hill.max()
    ws["hill_map"] = ((hill - mn) / (mx - mn + 1e-8)).tolist()
    print(f"  steepen_terrain({action.get('region')}, intensity={intensity})")


def op_add_water(ws, action):
    wtype = action.get("water_type", "plain")
    intensity = float(action.get("intensity", 0.3))
    mask = get_region_mask(action.get("region","all"), ws["height"], ws["width"])
    hill = np.array(ws["hill_map"], dtype=np.float64)
    water_map = np.array(ws["water_map"], dtype=object)
    # 在区域内最低的 intensity 比例格子填水
    region_heights = hill[mask]
    threshold = np.percentile(region_heights, intensity * 100)
    fill = mask & (hill <= threshold)
    water_map[fill] = wtype
    ws["water_map"] = water_map.tolist()
    print(f"  add_water({action.get('region')}, type={wtype}, intensity={intensity})")


def op_remove_water(ws, action):
    intensity = float(action.get("intensity", 0.3))
    mask = get_region_mask(action.get("region","all"), ws["height"], ws["width"])
    water_map = np.array(ws["water_map"], dtype=object)
    hill = np.array(ws["hill_map"], dtype=np.float64)
    water_in_region = mask & (water_map != "none")
    # 抬高该区域水域格子，使之变为陆地
    hill[water_in_region] = np.clip(hill[water_in_region] + intensity * 0.4, 0, 1)
    water_map[water_in_region] = "none"
    ws["hill_map"] = hill.tolist()
    ws["water_map"] = water_map.tolist()
    print(f"  remove_water({action.get('region')}, intensity={intensity})")


def op_add_cracks(ws, action):
    rng = np.random.RandomState(ws.get("seed", 0) + 999)
    count = int(action.get("count", 2))
    length = int(action.get("length", 20))
    mask = get_region_mask(action.get("region","all"), ws["height"], ws["width"])
    crack_map = np.array(ws["crack_map"], dtype=bool)
    water_map = np.array(ws["water_map"], dtype=object)
    H, W = ws["height"], ws["width"]

    candidates = np.argwhere(mask & (water_map == "none"))
    for _ in range(count):
        if len(candidates) == 0:
            break
        idx = rng.randint(len(candidates))
        sy, sx = candidates[idx]
        angle = rng.uniform(0, 2 * np.pi)
        cy, cx = float(sy), float(sx)
        for _ in range(length):
            iy, ix = int(round(cy)), int(round(cx))
            if not (0 <= iy < H and 0 <= ix < W):
                break
            if water_map[iy, ix] != "none":
                break
            crack_map[iy, ix] = True
            angle += rng.uniform(-0.4, 0.4)
            cy += np.sin(angle) * 1.2
            cx += np.cos(angle) * 1.2

    ws["crack_map"] = crack_map.tolist()
    print(f"  add_cracks({action.get('region')}, count={count}, length={length})")


def op_remove_cracks(ws, action):
    intensity = float(action.get("intensity", 0.5))
    mask = get_region_mask(action.get("region","all"), ws["height"], ws["width"])
    crack_map = np.array(ws["crack_map"], dtype=bool)
    rng = np.random.RandomState(ws.get("seed", 0) + 1001)
    # 随机移除 intensity 比例的裂隙
    to_remove = mask & crack_map
    indices = np.argwhere(to_remove)
    n_remove = int(len(indices) * intensity)
    if n_remove > 0:
        chosen = rng.choice(len(indices), n_remove, replace=False)
        for i in chosen:
            y, x = indices[i]
            crack_map[y, x] = False
    ws["crack_map"] = crack_map.tolist()
    print(f"  remove_cracks({action.get('region')}, intensity={intensity})")


def op_add_river(ws, action):
    """从 from 区域最高点向 to 区域最低点做梯度流。"""
    rng = np.random.RandomState(ws.get("seed", 0) + 777)
    H, W = ws["height"], ws["width"]
    hill = np.array(ws["hill_map"], dtype=np.float64)
    water_map = np.array(ws["water_map"], dtype=object)

    from_region = action.get("from", "north")
    to_region   = action.get("to",   "south")
    width       = int(action.get("width", 1))

    from_mask = get_region_mask(from_region, H, W)
    to_mask   = get_region_mask(to_region,   H, W)

    # 起点：from 区域内最高陆地格
    land_from = from_mask & (water_map == "none")
    if not land_from.any():
        print(f"  add_river: 起点区域无陆地，跳过")
        return
    ys, xs = np.where(land_from)
    heights = hill[ys, xs]
    idx = np.argmax(heights)
    cy, cx = int(ys[idx]), int(xs[idx])

    # 终点：to 区域内最低格（水域或低地）
    ys2, xs2 = np.where(to_mask)
    h2 = hill[ys2, xs2]
    idx2 = np.argmin(h2)
    goal_y, goal_x = int(ys2[idx2]), int(xs2[idx2])

    for _ in range(H * W):
        water_map[cy, cx] = "shallow"
        if abs(cy - goal_y) + abs(cx - goal_x) < 3:
            break

        best_h = hill[cy, cx]
        best_y, best_x = cy, cx
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = cy+dy, cx+dx
                if not (0 <= ny < H and 0 <= nx < W):
                    continue
                nh = hill[ny,nx] + rng.uniform(0, 0.02)
                if nh < best_h:
                    best_h, best_y, best_x = nh, ny, nx
        if best_y == cy and best_x == cx:
            break
        cy, cx = best_y, best_x

    ws["water_map"] = water_map.tolist()
    print(f"  add_river(from={from_region}, to={to_region}, width={width})")


def op_adjust_biome(ws, action):
    from_biome = action.get("from_biome", "plain")
    to_biome   = action.get("to_biome",   "forest")
    mask = get_region_mask(action.get("region","all"), ws["height"], ws["width"])
    biome_map = np.array(ws["biome_map"], dtype=object)
    change_mask = mask & (biome_map == from_biome)
    biome_map[change_mask] = to_biome
    ws["biome_map"] = biome_map.tolist()
    print(f"  adjust_biome({action.get('region')}, {from_biome} → {to_biome})")


# ---------------------------------------------------------------------------
# 操作分发
# ---------------------------------------------------------------------------

OP_HANDLERS = {
    "raise_height":   op_raise_height,
    "lower_height":   op_lower_height,
    "smooth_terrain": op_smooth_terrain,
    "steepen_terrain":op_steepen_terrain,
    "add_water":      op_add_water,
    "remove_water":   op_remove_water,
    "add_cracks":     op_add_cracks,
    "remove_cracks":  op_remove_cracks,
    "add_slopes":     lambda ws, a: print("  add_slopes: 由 rebuild_slope 后处理完成"),
    "add_river":      op_add_river,
    "remove_river":   op_remove_water,   # 复用：排干河流
    "adjust_biome":   op_adjust_biome,
    # 生态 / 文明操作由各自的生成脚本处理，这里记录但跳过
    "increase_vegetation": lambda ws, a: print(f"  [ecology op, 由 generate_ecology 处理]"),
    "reduce_vegetation":   lambda ws, a: print(f"  [ecology op, 由 generate_ecology 处理]"),
    "add_monster_zone":    lambda ws, a: print(f"  [ecology op, 由 generate_ecology 处理]"),
    "adjust_danger":       lambda ws, a: print(f"  [ecology/civ op, 跳过]"),
    "add_settlement":      lambda ws, a: print(f"  [civ op, 由 generate_civilization 处理]"),
    "add_road":            lambda ws, a: print(f"  [civ op, 由 generate_civilization 处理]"),
    "remove_settlement":   lambda ws, a: print(f"  [civ op, 由 generate_civilization 处理]"),
}


def check_era_permission(op, era, era_weights):
    """检查当前时代是否允许该操作。"""
    era_cfg = era_weights.get(f"era_{era}", {})
    forbidden = era_cfg.get("forbidden_patch_ops", [])
    if op in forbidden:
        return False, f"操作 '{op}' 在 {era} 时代被禁止"
    return True, ""


def rebuild_derived_maps(ws):
    """在修改 hill_map / water_map 后重建 cliff_map、slope_map、biome_map。"""
    from generate_terrain import (
        build_cliff_map, build_slope_map, classify_biomes
    )
    # 读取生成配置（默认值）
    gen = {
        "water_level": 0.32,
        "shallow_threshold": 0.06,
        "max_cliff_level": 5,
        "allow_slopes": True,
    }

    hill  = np.array(ws["hill_map"],  dtype=np.float64)
    water = np.array(ws["water_map"], dtype=object)
    cliff = build_cliff_map(hill, gen)
    slope = build_slope_map(cliff, water, gen)
    biome = classify_biomes(hill, water, cliff, gen)

    ws["cliff_map"] = cliff.tolist()
    ws["slope_map"] = slope.tolist()
    ws["biome_map"] = biome.tolist()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world-state",  required=True, help="world_state.json 路径")
    parser.add_argument("--patch",        required=True, help="Patch Plan JSON 字符串或文件路径")
    parser.add_argument("--era",          required=True, help="当前时代: terrain|ecology|civilization|stable")
    parser.add_argument("--era-weights",  default=None,  help="era_weights.json 路径")
    parser.add_argument("--output",       required=True, help="输出 world_state.json 路径")
    args = parser.parse_args()

    # 读取世界状态
    with open(args.world_state, "r", encoding="utf-8") as f:
        ws = json.load(f)

    # 读取 Patch Plan
    patch_input = args.patch.strip()
    if patch_input.endswith(".json") and Path(patch_input).exists():
        with open(patch_input, "r", encoding="utf-8") as f:
            patch = json.load(f)
    else:
        patch = json.loads(patch_input)

    # 读取时代权重
    era_weights = {}
    if args.era_weights and Path(args.era_weights).exists():
        with open(args.era_weights, "r", encoding="utf-8") as f:
            era_weights = json.load(f)

    print(f"[apply_patch] 时代={args.era}, 操作数={len(patch.get('actions', []))}")
    print(f"  原因: {patch.get('reason', '未说明')}")

    skipped = []
    for action in patch.get("actions", []):
        op = action.get("op", "")
        allowed, msg = check_era_permission(op, args.era, era_weights)
        if not allowed:
            print(f"  ⚠️  跳过 '{op}': {msg}")
            skipped.append(op)
            continue

        handler = OP_HANDLERS.get(op)
        if handler:
            handler(ws, action)
        else:
            print(f"  ⚠️  未知操作: {op}")

    # 重建派生地图（cliff / slope / biome）
    if any(op not in skipped for op in ["raise_height","lower_height","add_water","remove_water",
                                         "smooth_terrain","steepen_terrain","add_river","remove_river"]):
        print("[apply_patch] 重建衍生地图...")
        rebuild_derived_maps(ws)

    # 更新迭代计数
    ws["iteration"] = ws.get("iteration", 0) + 1
    ws["era"] = args.era

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(ws, f, ensure_ascii=False)

    print(f"[apply_patch] 完成 → {args.output}")
    if skipped:
        print(f"  跳过操作: {skipped}")


if __name__ == "__main__":
    main()
