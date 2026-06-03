#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cv_postprocess_plan.py — Majesty 类游戏地图后处理规划脚本

基于地形数据（高度/纹理/水域）自动生成装饰物放置方案：
  1. 确定首都位置
  2. 计算距离场（Dijkstra，按地形成本加权）
  3. 放置游戏节点（资源点/怪物巢穴/地牢/遗迹）
  4. 生成道路网络（A* 连接首都与关键节点）
  5. 自动放置树木和山石（规则驱动，避开节点和道路）

输出:
  postprocess_plan.json    — 完整规划（供 AI 审核/调整）
  distance_map.npy         — 距离场
  road_grid.npy            — 道路格子标记
  postprocess_preview.png  — 规划可视化

用法:
  python cv_postprocess_plan.py \\
    --height-grid <dir>/height_grid.npy \\
    --texture-grid <dir>/texture_grid.csv \\
    --water-mask <dir>/water_mask_grid.npy \\
    --map-info <dir>/map_info.json \\
    --output-dir <dir> \\
    [--capital "center" | "x,z"] \\
    [--game-style majesty] \\
    [--node-counts "resource=5,lair=6,dungeon=2,ruin=8"]
"""

import argparse
import csv
import heapq
import json
import math
import os
import random
import sys
from collections import defaultdict

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# 游戏风格预设（各类节点的距离区间、数量范围）
# ─────────────────────────────────────────────────────────────────────────────

GAME_STYLES = {
    "majesty": {
        # 各节点放置的距离区间（占最大距离的比例）
        "resource_zone":   (0.28, 0.62),
        "lair_zone":       (0.48, 0.82),
        "dungeon_zone":    (0.62, 1.00),
        "ruin_zone":       (0.15, 1.00),
        # 节点数量范围（根据地图面积自动缩放）
        "resource_count":  (3, 7),
        "lair_count":      (4, 9),
        "dungeon_count":   (1, 4),
        "ruin_count":      (5, 12),
        # 节点最小间距（格）
        "min_spacing":     5,
        "road_min_spacing": 2,
        # 建造区定义（近首都平地，供游戏内玩家建造使用）
        "buildable_zone":  (0.00, 0.38),
        # 首都附近保护半径（不放任何节点）
        "capital_safe_radius": 6,
    }
}

# 地形移动成本（用于距离场和道路寻路）
TERRAIN_COST = {
    0:  1.0,   # 平原：最易通行
    2:  3.0,   # 丘陵：较难
    4:  8.0,   # 山地：很难
    6:  20.0,  # 高山：近乎不可通行（但不完全封闭）
    -1: float('inf'),  # 水域：完全不可通行（inf+inf=inf，Dijkstra 不会穿越）
}

# 纹理组 → 地貌语义（用于节点候选区偏好判断）
# 草地系更适合放树木，岩石系更适合放地牢
TEXTURE_GROUP_DANGER = defaultdict(lambda: 0.5, {
    # 草地/平原 → 安全，适合资源点
    "grassland": 0.2,
    "autumn":    0.3,
    # 沙漠 → 半危险
    "desert":    0.5,
    # 岩石/冰雪 → 危险，适合地牢/巢穴
    "rock":      0.8,
    "snow":      0.7,
    "ice":       0.8,
    # 沼泽 → 危险，适合巢穴
    "swamp":     0.75,
})


# ─────────────────────────────────────────────────────────────────────────────
# 地形数据加载
# ─────────────────────────────────────────────────────────────────────────────

def load_texture_grid(path: str, H: int, W: int) -> np.ndarray:
    """加载 texture_grid.csv，返回 (H, W) int32 纹理 ID 矩阵。"""
    grid = np.zeros((H, W), dtype=np.int32)
    with open(path, "r", encoding="utf-8") as f:
        for z, row in enumerate(csv.reader(f)):
            for x, val in enumerate(row):
                try:
                    grid[z, x] = int(val.strip())
                except ValueError:
                    pass
    return grid


def build_cost_map(height_grid: np.ndarray, water_mask: np.ndarray) -> np.ndarray:
    """构建地形移动成本矩阵。"""
    H, W = height_grid.shape
    cost = np.ones((H, W), dtype=np.float64)
    for z in range(H):
        for x in range(W):
            h = int(height_grid[z, x])
            cost[z, x] = TERRAIN_COST.get(h, 1.0)
    cost[water_mask] = np.inf  # 水域完全不可通行：inf+inf=inf，Dijkstra/A* 均不穿越
    return cost


# ─────────────────────────────────────────────────────────────────────────────
# 首都位置确定
# ─────────────────────────────────────────────────────────────────────────────

def find_capital(height_grid: np.ndarray, water_mask: np.ndarray,
                 hint: str = "center") -> tuple:
    """确定首都格子坐标 (x, z)。

    hint: "center" | "x,z"（具体坐标）
    """
    H, W = height_grid.shape

    if hint and "," in hint:
        x, z = [int(v.strip()) for v in hint.split(",")]
        return (x, z)

    # 自动选：地图中心区域（25%~75%范围内），h=0 的最大平地连通区质心
    center_x, center_z = W // 2, H // 2

    if hint == "center":
        # 搜索中心 40% 区域内最近的 h=0 陆地格
        best, best_dist = (center_x, center_z), 1e9
        x_range = range(int(W * 0.3), int(W * 0.7))
        z_range = range(int(H * 0.3), int(H * 0.7))
        for z in z_range:
            for x in x_range:
                if not water_mask[z, x] and int(height_grid[z, x]) == 0:
                    d = (x - center_x) ** 2 + (z - center_z) ** 2
                    if d < best_dist:
                        best_dist = d
                        best = (x, z)
        return best

    return (center_x, center_z)


# ─────────────────────────────────────────────────────────────────────────────
# 距离场计算（Dijkstra）
# ─────────────────────────────────────────────────────────────────────────────

def compute_distance_map(capital: tuple, cost_map: np.ndarray) -> np.ndarray:
    """从首都出发，用 Dijkstra 计算所有格子的加权距离。"""
    H, W = cost_map.shape
    dist = np.full((H, W), np.inf, dtype=np.float64)
    cx, cz = capital
    dist[cz, cx] = 0.0

    pq = [(0.0, cz, cx)]
    while pq:
        d, z, x = heapq.heappop(pq)
        if d > dist[z, x]:
            continue
        for dz, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
            nz, nx = z + dz, x + dx
            if 0 <= nz < H and 0 <= nx < W:
                nd = d + cost_map[nz, nx]
                if nd < dist[nz, nx]:
                    dist[nz, nx] = nd
                    heapq.heappush(pq, (nd, nz, nx))

    return dist


# ─────────────────────────────────────────────────────────────────────────────
# 游戏节点放置
# ─────────────────────────────────────────────────────────────────────────────

def place_nodes(node_type: str,
                count_range: tuple,
                dist_zone: tuple,
                dist_normalized: np.ndarray,
                height_grid: np.ndarray,
                water_mask: np.ndarray,
                placed: list,
                min_spacing: int,
                capital_radius: int,
                capital: tuple,
                rng: random.Random,
                preferred_h_range: tuple = (0, 6),
                map_area_factor: float = 1.0) -> list:
    """在距离区间内放置 node_type 类型的游戏节点。

    Args:
        dist_zone: (min_ratio, max_ratio)，normalized 距离区间
        preferred_h_range: 偏好的高度范围 (min_h, max_h)
        map_area_factor: 地图面积比例因子（用于缩放数量）

    Returns:
        新放置的节点列表 [{"type":..., "x":..., "z":..., "h":...}, ...]
    """
    H, W = height_grid.shape
    min_d, max_d = dist_zone
    min_h, max_h = preferred_h_range

    # 根据地图面积缩放数量
    raw_count = rng.randint(*count_range)
    count = max(1, int(raw_count * map_area_factor))

    # 候选格子：在距离区间内、陆地、高度满足
    candidates = []
    for z in range(H):
        for x in range(W):
            if water_mask[z, x]:
                continue
            h = int(height_grid[z, x])
            if not (min_h <= h <= max_h):
                continue
            nd = float(dist_normalized[z, x])
            if not (min_d <= nd <= max_d):
                continue
            # 首都保护区
            if math.sqrt((x - capital[0])**2 + (z - capital[1])**2) < capital_radius:
                continue
            candidates.append((z, x))

    rng.shuffle(candidates)
    result = []
    for z, x in candidates:
        if len(result) >= count:
            break
        # 检查与已放节点的最小间距
        too_close = any(
            math.sqrt((x - n["x"])**2 + (z - n["z"])**2) < min_spacing
            for n in placed + result
        )
        if not too_close:
            result.append({
                "type": node_type,
                "x": int(x),
                "z": int(z),
                "h": int(height_grid[z, x]),
            })

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 道路生成（A*）
# ─────────────────────────────────────────────────────────────────────────────

def astar(start: tuple, goal: tuple, cost_map: np.ndarray) -> list:
    """A* 寻路，返回从 start 到 goal 的格子路径列表 [(x,z), ...]。"""
    H, W = cost_map.shape
    sx, sz = start
    gx, gz = goal

    def heuristic(x, z):
        return math.sqrt((x - gx)**2 + (z - gz)**2)

    open_set = [(0.0, sz, sx)]
    came_from = {}
    g_score = {(sz, sx): 0.0}

    while open_set:
        _, z, x = heapq.heappop(open_set)
        if (z, x) == (gz, gx):
            # 回溯路径
            path = []
            cur = (gz, gx)
            while cur in came_from:
                path.append((cur[1], cur[0]))  # (x, z)
                cur = came_from[cur]
            path.append((sx, sz))
            return path[::-1]

        for dz, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
            nz, nx = z + dz, x + dx
            if not (0 <= nz < H and 0 <= nx < W):
                continue
            if cost_map[nz, nx] >= 1e8:
                continue
            tentative = g_score.get((z, x), 1e18) + cost_map[nz, nx]
            if tentative < g_score.get((nz, nx), 1e18):
                came_from[(nz, nx)] = (z, x)
                g_score[(nz, nx)] = tentative
                f = tentative + heuristic(nx, nz)
                heapq.heappush(open_set, (f, nz, nx))

    return []  # 无路可走


def build_road_network(capital: tuple, nodes: list,
                       cost_map: np.ndarray) -> np.ndarray:
    """从首都向所有节点连通道路，返回道路格子标记矩阵。"""
    H, W = cost_map.shape
    road_grid = np.zeros((H, W), dtype=bool)

    for node in nodes:
        goal = (node["x"], node["z"])
        path = astar(capital, goal, cost_map)
        for px, pz in path:
            if 0 <= pz < H and 0 <= px < W:
                road_grid[pz, px] = True

    return road_grid


# ─────────────────────────────────────────────────────────────────────────────
# 自动树木/山石放置
# ─────────────────────────────────────────────────────────────────────────────

def auto_place_trees_rocks(height_grid: np.ndarray,
                            water_mask: np.ndarray,
                            road_grid: np.ndarray,
                            all_nodes: list,
                            style: dict,
                            rng: random.Random) -> list:
    """基于地形规则自动放置树木和山石，避开道路和游戏节点。

    Returns:
        list of {"type": "tree"|"rock", "x", "z", "h", "density"}
    """
    H, W = height_grid.shape
    node_positions = {(n["x"], n["z"]) for n in all_nodes}
    node_exclusion_radius = style.get("min_spacing", 5)

    def near_node(x, z):
        return any(
            math.sqrt((x - nx)**2 + (z - nz)**2) < node_exclusion_radius
            for nx, nz in node_positions
        )

    placements = []

    # 树木放置：h=0~2，非水域，非道路，非节点附近，按网格采样
    tree_spacing = 3  # 每 3 格采样一个候选点
    for z in range(0, H, tree_spacing):
        for x in range(0, W, tree_spacing):
            if water_mask[z, x]:
                continue
            h = int(height_grid[z, x])
            if h > 2:
                continue
            if road_grid[z, x]:
                continue
            if near_node(x, z):
                continue
            # 随机抖动（避免过于规则）
            jx = x + rng.randint(-1, 1)
            jz = z + rng.randint(-1, 1)
            jx = max(0, min(W - 1, jx))
            jz = max(0, min(H - 1, jz))
            if water_mask[jz, jx] or road_grid[jz, jx]:
                continue
            # 50% 概率跳过（稀疏化）
            if rng.random() < 0.5:
                continue
            placements.append({
                "type": "tree",
                "x": int(jx), "z": int(jz), "h": h,
                "density": "normal" if rng.random() > 0.3 else "sparse",
            })

    # 山石放置：h=4~6，非水域，非节点附近
    rock_spacing = 4
    for z in range(0, H, rock_spacing):
        for x in range(0, W, rock_spacing):
            if water_mask[z, x]:
                continue
            h = int(height_grid[z, x])
            if h < 4:
                continue
            if near_node(x, z):
                continue
            if rng.random() < 0.4:
                continue
            placements.append({
                "type": "rock",
                "x": int(x), "z": int(z), "h": h,
                "density": "normal",
            })

    return placements


# ─────────────────────────────────────────────────────────────────────────────
# 可视化
# ─────────────────────────────────────────────────────────────────────────────

def generate_preview(height_grid, water_mask, dist_normalized,
                     road_grid, all_nodes, capital, output_path):
    """生成规划可视化图：地形 + 距离场 + 节点 + 道路。"""
    try:
        import cv2
    except ImportError:
        print("  ⚠️  opencv 未安装，跳过预览图")
        return

    H, W = height_grid.shape
    scale = max(1, min(4, 512 // max(H, W)))
    img = np.zeros((H * scale, W * scale, 3), dtype=np.uint8)

    # 地形底色
    height_colors = {-1:(120,80,40), 0:(80,160,80), 2:(60,110,60), 4:(50,75,110), 6:(210,215,220)}
    for z in range(H):
        for x in range(W):
            h = -1 if water_mask[z, x] else int(height_grid[z, x])
            c = height_colors.get(h, (100,100,100))
            img[z*scale:(z+1)*scale, x*scale:(x+1)*scale] = c

    # 距离场叠加（越远越红）
    valid = ~water_mask & np.isfinite(dist_normalized)
    for z in range(H):
        for x in range(W):
            if valid[z, x]:
                d = float(dist_normalized[z, x])
                r = int(d * 60)
                img[z*scale:(z+1)*scale, x*scale:(x+1)*scale, 2] = \
                    np.clip(img[z*scale:(z+1)*scale, x*scale:(x+1)*scale, 2].astype(int) + r, 0, 255)

    # 道路（黄色）
    for z in range(H):
        for x in range(W):
            if road_grid[z, x]:
                img[z*scale:(z+1)*scale, x*scale:(x+1)*scale] = (0, 200, 220)

    # 游戏节点标注
    node_colors = {
        "capital":  (255, 255, 0),   # 黄色
        "resource": (0, 200, 255),   # 橙色
        "lair":     (0, 0, 220),     # 红色
        "dungeon":  (180, 0, 180),   # 紫色
        "ruin":     (140, 140, 140), # 灰色
    }
    node_radius = max(2, scale)
    for node in all_nodes:
        cx_p = node["x"] * scale + scale // 2
        cz_p = node["z"] * scale + scale // 2
        color = node_colors.get(node["type"], (255,255,255))
        cv2.circle(img, (cx_p, cz_p), node_radius * 2, color, -1)
        cv2.circle(img, (cx_p, cz_p), node_radius * 2, (0,0,0), 1)

    # 首都（大黄点）
    cap_x_p = capital[0] * scale + scale // 2
    cap_z_p = capital[1] * scale + scale // 2
    cv2.circle(img, (cap_x_p, cap_z_p), node_radius * 4, (0, 255, 255), -1)
    cv2.circle(img, (cap_x_p, cap_z_p), node_radius * 4, (0, 0, 0), 2)

    # 图例
    legend = [
        ("首都", (0,255,255)), ("资源点", (0,200,255)),
        ("怪物巢穴", (0,0,220)), ("地牢", (180,0,180)),
        ("遗迹", (140,140,140)), ("道路", (0,200,220)),
    ]
    for i, (label, color) in enumerate(legend):
        cv2.rectangle(img, (5, 5 + i*15), (12, 12 + i*15), color, -1)

    cv2.imwrite(output_path, img)


# ─────────────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Majesty 类游戏地图后处理规划 — 距离场 + 节点放置 + 道路生成"
    )
    parser.add_argument("--height-grid",  required=True, help="height_grid.npy")
    parser.add_argument("--texture-grid", required=True, help="texture_grid.csv")
    parser.add_argument("--water-mask",   required=True, help="water_mask_grid.npy")
    parser.add_argument("--map-info",     default=None,  help="map_info.json（读取地图尺寸）")
    parser.add_argument("--output-dir",   default=".",   help="输出目录")
    parser.add_argument("--capital",      default="center",
                        help="首都位置：'center' 或 'x,z'，如 '32,32'")
    parser.add_argument("--game-style",   default="majesty",
                        choices=list(GAME_STYLES.keys()), help="游戏风格预设")
    parser.add_argument("--node-counts",  default=None,
                        help="覆盖节点数量，如 'resource=5,lair=6,dungeon=2,ruin=8'")
    parser.add_argument("--seed",         type=int, default=42, help="随机种子")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    rng = random.Random(args.seed)
    style = GAME_STYLES[args.game_style]

    # ── 覆盖节点数量 ──────────────────────────────────────────────────────────
    if args.node_counts:
        for pair in args.node_counts.split(","):
            k, v = pair.strip().split("=")
            count = int(v)
            key = f"{k.strip()}_count"
            if key in style:
                style[key] = (count, count)

    # ── Step 1: 加载地形数据 ──────────────────────────────────────────────────
    print("[Step 1] 加载地形数据 ...")
    height_grid = np.load(args.height_grid).astype(np.int32)
    water_mask  = np.load(args.water_mask).astype(bool)
    H, W = height_grid.shape
    print(f"  网格尺寸: {W}×{H}")

    texture_grid = load_texture_grid(args.texture_grid, H, W)

    # 地图面积缩放因子（以 64×64=4096 为基准）
    area_factor = (H * W) / 4096.0

    # ── Step 2: 确定首都 ──────────────────────────────────────────────────────
    print("\n[Step 2] 确定首都位置 ...")
    capital = find_capital(height_grid, water_mask, args.capital)
    print(f"  首都: x={capital[0]}, z={capital[1]}, h={height_grid[capital[1], capital[0]]}")

    # ── Step 3: 地形成本图 + 距离场 ──────────────────────────────────────────
    print("\n[Step 3] 计算距离场 ...")
    cost_map = build_cost_map(height_grid, water_mask)
    distance_map = compute_distance_map(capital, cost_map)

    # 归一化距离（0~1）
    valid_dist = distance_map[np.isfinite(distance_map) & ~water_mask]
    max_dist = float(valid_dist.max()) if len(valid_dist) > 0 else 1.0
    dist_normalized = np.where(np.isfinite(distance_map), distance_map / max_dist, 1.0)

    np.save(os.path.join(args.output_dir, "distance_map.npy"), distance_map)
    print(f"  距离场: max={max_dist:.1f}")

    # ── Step 4: 游戏节点放置 ─────────────────────────────────────────────────
    print("\n[Step 4] 放置游戏节点 ...")
    all_nodes = []

    # 首都节点
    all_nodes.append({"type": "capital", "x": capital[0], "z": capital[1],
                       "h": int(height_grid[capital[1], capital[0]])})

    common_kwargs = dict(
        dist_normalized=dist_normalized,
        height_grid=height_grid,
        water_mask=water_mask,
        placed=all_nodes,
        min_spacing=style["min_spacing"],
        capital_radius=style["capital_safe_radius"],
        capital=capital,
        rng=rng,
        map_area_factor=min(2.0, area_factor),
    )

    # 资源点（中圈，平地优先）
    resources = place_nodes("resource", style["resource_count"], style["resource_zone"],
                            preferred_h_range=(0, 2), **common_kwargs)
    all_nodes.extend(resources)
    print(f"  资源点: {len(resources)} 个")

    # 怪物巢穴（外圈，森林/高地区域）
    lairs = place_nodes("lair", style["lair_count"], style["lair_zone"],
                        preferred_h_range=(0, 4), **common_kwargs)
    all_nodes.extend(lairs)
    print(f"  怪物巢穴: {len(lairs)} 个")

    # 地牢（最外圈，山地优先）
    dungeons = place_nodes("dungeon", style["dungeon_count"], style["dungeon_zone"],
                           preferred_h_range=(2, 6), **common_kwargs)
    all_nodes.extend(dungeons)
    print(f"  地牢: {len(dungeons)} 个")

    # 遗迹（全图散布）
    ruins = place_nodes("ruin", style["ruin_count"], style["ruin_zone"],
                        preferred_h_range=(0, 4), **common_kwargs)
    all_nodes.extend(ruins)
    print(f"  遗迹: {len(ruins)} 个")

    # ── Step 5: 道路网络 ─────────────────────────────────────────────────────
    print("\n[Step 5] 生成道路网络 ...")
    road_nodes = [n for n in all_nodes if n["type"] in ("resource", "lair", "dungeon")]
    road_grid = build_road_network(capital, road_nodes, cost_map)
    np.save(os.path.join(args.output_dir, "road_grid.npy"), road_grid)
    road_tile_count = int(road_grid.sum())
    print(f"  道路格子: {road_tile_count}")

    # ── Step 6: 树木/山石自动放置 ────────────────────────────────────────────
    print("\n[Step 6] 自动放置树木和山石 ...")
    deco_placements = auto_place_trees_rocks(
        height_grid, water_mask, road_grid, all_nodes, style, rng
    )
    tree_count = sum(1 for d in deco_placements if d["type"] == "tree")
    rock_count = sum(1 for d in deco_placements if d["type"] == "rock")
    print(f"  树木: {tree_count}, 山石: {rock_count}")

    # ── Step 7: 建造区标注 ───────────────────────────────────────────────────
    bz_min, bz_max = style["buildable_zone"]
    buildable_count = int(np.sum(
        (dist_normalized <= bz_max) & (dist_normalized >= bz_min) &
        (~water_mask) & (height_grid == 0)
    ))
    print(f"\n  建造区（h=0，距首都 {int(bz_min*100)}~{int(bz_max*100)}%）: {buildable_count} 格")

    # ── Step 8: 输出规划 JSON ────────────────────────────────────────────────
    plan = {
        "game_style": args.game_style,
        "map_size": {"width": W, "height": H},
        "capital": {"x": capital[0], "z": capital[1]},
        "nodes": all_nodes,
        "road_tile_count": road_tile_count,
        "decorations": deco_placements,
        "buildable_zone": {"dist_range": style["buildable_zone"], "tile_count": buildable_count},
        "summary": {
            "total_nodes": len(all_nodes),
            "resources": len(resources),
            "lairs": len(lairs),
            "dungeons": len(dungeons),
            "ruins": len(ruins),
            "trees": tree_count,
            "rocks": rock_count,
        }
    }

    plan_path = os.path.join(args.output_dir, "postprocess_plan.json")
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 规划文件: {plan_path}")

    # ── Step 9: 预览图 ───────────────────────────────────────────────────────
    print("\n[Step 9] 生成预览图 ...")
    preview_path = os.path.join(args.output_dir, "postprocess_preview.png")
    generate_preview(height_grid, water_mask, dist_normalized,
                     road_grid, all_nodes, capital, preview_path)
    print(f"  ✅ 预览图: {preview_path}")

    print(f"\n✅ 后处理规划完成！")
    print(f"   节点总计: {len(all_nodes)} | 道路: {road_tile_count} 格 | 树: {tree_count} | 石: {rock_count}")
    print(f"   下一步: AI 审查 postprocess_preview.png + postprocess_plan.json")
    print(f"   可调整参数后重跑，或直接进入 MCP 写入阶段。")


if __name__ == "__main__":
    main()
