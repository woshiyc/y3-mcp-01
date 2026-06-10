#!/usr/bin/env python3
"""
Y3 Terrain Evolution - Civilization Generator

基于地形 + 生态层，生成聚落、道路、建筑：
- 聚落选址：平地 + 近水 + 远离危险区
- 道路：A* 寻路连接聚落
- 输出 civilization_layer.json
"""

import numpy as np
import json
import argparse
from pathlib import Path
from collections import deque
import heapq


SETTLEMENT_TYPES = ["hamlet", "village", "town", "fortress"]


def _distance_transform(mask, H, W):
    dist = np.full((H, W), np.inf)
    q = deque()
    ys, xs = np.where(mask)
    for y, x in zip(ys, xs):
        dist[y, x] = 0.0
        q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
            ny, nx = y+dy, x+dx
            if 0 <= ny < H and 0 <= nx < W and dist[ny,nx] == np.inf:
                dist[ny,nx] = dist[y,x] + 1.0
                q.append((ny, nx))
    return dist


def score_settlement_cell(y, x, hill, water, dist_water, danger_map, H, W):
    """对一个格子的聚落适宜度打分（越高越好）。"""
    if water[y, x] != "none":
        return -9999
    score = 0.0
    # 高度适中（平地）
    h = hill[y, x]
    if 0.25 < h < 0.6:
        score += 30
    elif h <= 0.25 or h >= 0.8:
        score -= 50
    # 距水源近但不在水里
    dw = dist_water[y, x]
    if 3 <= dw <= 15:
        score += 25
    elif dw <= 2:
        score += 10
    elif dw > 30:
        score -= 20
    # 远离危险区
    danger = danger_map[y, x]
    score -= danger * 15
    # 远离边缘
    edge_dist = min(y, H-1-y, x, W-1-x)
    if edge_dist < 5:
        score -= 20
    return score


def find_settlements(ws, eco, n_settlements, rng):
    H, W = ws["height"], ws["width"]
    hill  = np.array(ws["hill_map"],  dtype=np.float64)
    water = np.array(ws["water_map"], dtype=object)

    water_mask = (water != "none")
    dist_water = _distance_transform(water_mask, H, W)

    # 构建危险度地图（来自 ecology）
    danger_map = np.zeros((H, W), dtype=np.float64)
    if eco:
        for biome, cov in eco.get("biome_coverage", {}).items():
            for zone in cov.get("monster_zone_list", []):
                zy, zx = zone["grid_y"], zone["grid_x"]
                r = zone.get("radius", 5)
                dl = zone.get("danger_level", 1)
                for dy in range(-r, r+1):
                    for dx in range(-r, r+1):
                        ny, nx = zy+dy, zx+dx
                        if 0 <= ny < H and 0 <= nx < W:
                            danger_map[ny, nx] = max(danger_map[ny, nx], dl)

    # 评分所有陆地格子
    scores = np.full((H, W), -9999.0)
    for y in range(H):
        for x in range(W):
            if water[y, x] == "none":
                scores[y, x] = score_settlement_cell(y, x, hill, water, dist_water, danger_map, H, W)

    settlements = []
    used_mask = np.zeros((H, W), dtype=bool)
    exclusion_radius = max(H, W) // (n_settlements + 1)

    for i in range(n_settlements):
        # 找分数最高的未被排斥的格子
        valid_scores = scores.copy()
        valid_scores[used_mask] = -9999
        if valid_scores.max() < -5000:
            break

        idx = np.argmax(valid_scores)
        iy, ix = np.unravel_index(idx, (H, W))

        stype = SETTLEMENT_TYPES[min(i, len(SETTLEMENT_TYPES)-1)]
        if n_settlements > 4:
            stype = rng.choice(SETTLEMENT_TYPES[:3])

        settlements.append({
            "id":         i,
            "type":       stype,
            "grid_y":     int(iy),
            "grid_x":     int(ix),
            "near_water": bool(dist_water[iy, ix] <= 20),
            "accessible": True,   # 连通性由道路生成后验证
            "danger_level": float(danger_map[iy, ix]),
        })

        # 排斥周围格子
        r = exclusion_radius
        y0, y1 = max(0, iy-r), min(H, iy+r)
        x0, x1 = max(0, ix-r), min(W, ix+r)
        used_mask[y0:y1, x0:x1] = True

    return settlements


def astar_road(start, goal, passable, cost_map, H, W):
    """A* 寻路（严格 4-connectivity），使用 cost_map 确定移动代价。

    Args:
        start, goal: (y, x) 坐标
        passable: bool 矩阵，False = 不可通行（水域）
        cost_map: float 矩阵，进入该格代价（cliff 差值越大越高）
        H, W: 地图尺寸
    Returns:
        [(y,x), ...] 路径，或 None
    """
    if not passable[start[0], start[1]] or not passable[goal[0], goal[1]]:
        return None

    def h(a, b): return abs(a[0]-b[0]) + abs(a[1]-b[1])

    open_set = [(h(start, goal), 0.0, start)]
    came_from = {}
    g = {start: 0.0}

    # 严格 4-connectivity，不允许对角线（防止绕过悬崖角落）
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
            ny, nx = cur[0]+dy, cur[1]+dx
            nb = (ny, nx)
            if not (0 <= ny < H and 0 <= nx < W): continue
            if not passable[ny, nx]: continue
            ng = g[cur] + cost_map[ny, nx]
            if ng < g.get(nb, 1e18):
                came_from[nb] = cur
                g[nb] = ng
                heapq.heappush(open_set, (ng + h(nb, goal), ng, nb))
    return None


def generate_roads(settlements, ws):
    H, W = ws["height"], ws["width"]
    water = np.array(ws["water_map"], dtype=object)
    cliff = np.array(ws["cliff_map"], dtype=np.int32)

    # 所有水域不可通行（含 deep/shallow/plain）
    passable = (water == "none")

    # cliff cost map：相邻格差值越大代价越高
    cost_map = np.ones((H, W), dtype=np.float64)
    for y in range(H):
        for x in range(W):
            max_diff = 0
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y+dy, x+dx
                if 0 <= ny < H and 0 <= nx < W:
                    diff = abs(int(cliff[y, x]) - int(cliff[ny, nx]))
                    max_diff = max(max_diff, diff)
            if max_diff >= 2:
                cost_map[y, x] = 100.0  # 悬崖边界，极高代价
            elif max_diff == 1:
                cost_map[y, x] = 5.0   # 斜坡区，中等代价
        # 水域设为不可通行（已由 passable 控制，cost 设高作双重保险）
        for x in range(W):
            if water[y, x] != "none":
                cost_map[y, x] = 1e9

    roads = []
    road_cells = set()
    unconnected = 0

    # 连接相邻聚落（最小生成树思路：按距离从近到远）
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
        # 已有道路的格子 cost 减半（鼓励共线复用）
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
                "from":        i,
                "to":          j,
                "length":      len(path),
                "passable":    True,
                "cells":       [(y, x) for y, x in path],
            })
            for y, x in path:
                road_cells.add((y, x))
            connected[i] = True
            connected[j] = True
        else:
            unconnected += 1

    return roads, unconnected, road_cells


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world-state",    required=True)
    parser.add_argument("--ecology",        default=None)
    parser.add_argument("--asset-profiles", default=None)
    parser.add_argument("--output",         required=True)
    parser.add_argument("--n-settlements",  type=int, default=4)
    args = parser.parse_args()

    with open(args.world_state, "r", encoding="utf-8") as f:
        ws = json.load(f)

    eco = None
    if args.ecology and Path(args.ecology).exists():
        with open(args.ecology, "r", encoding="utf-8") as f:
            eco = json.load(f)

    asset_profiles = None
    if args.asset_profiles and Path(args.asset_profiles).exists():
        with open(args.asset_profiles, "r", encoding="utf-8") as f:
            asset_profiles = json.load(f)
        print("[generate_civilization] 已加载 asset_profiles")
    else:
        print("[generate_civilization] 未提供 asset_profiles，跳过实体模型放置")

    seed  = ws.get("seed", 42)
    rng   = np.random.RandomState(seed + 700)
    H, W  = ws["height"], ws["width"]
    water = np.array(ws["water_map"], dtype=object)

    print(f"[generate_civilization] 生成 {args.n_settlements} 个聚落...")
    settlements = find_settlements(ws, eco, args.n_settlements, rng)

    print(f"[generate_civilization] 生成道路...")
    roads, unconnected, road_cells = generate_roads(settlements, ws)

    # -----------------------------------------------------------------------
    # 道路实体（Y3 无道路地形类型，道路通过实体摆件表现，entity_create_block）
    # 需要 asset_profiles 中 decorations[].category == "road" 提供 model_id
    # -----------------------------------------------------------------------
    road_entities = []
    road_model_id = ""
    if asset_profiles:
        for a in asset_profiles.get("decorations", []):
            if a.get("category") == "road":
                road_model_id = a.get("model_id", "")
                break
    if road_model_id:
        for road in roads:
            for ry, rx in road.get("cells", []):
                # 道路是每格密铺的小方块模型（decoration-model-ids.md §道路密铺）
                # 不按间距稀释，每格一个，由 model_id 对应的路面方块拼接成连续道路
                road_entities.append({
                    "grid_x":          int(rx),
                    "grid_y":          int(ry),
                    "entity_type":     16777216,
                    "model_id":        road_model_id,
                    "yaw":             0,
                    "scale":           [1.0, 1.0, 1.0],
                    "stick_to_ground": True,
                })

    # -----------------------------------------------------------------------
    # 建筑实体（聚落核心，每个聚落放置 1 个标志性建筑）
    # 需要 asset_profiles 中 buildings[].settlement_type 提供 model_id
    # -----------------------------------------------------------------------
    building_entities = []
    building_model_map = {}
    if asset_profiles:
        for a in asset_profiles.get("buildings", []):
            stype = a.get("settlement_type")
            if stype:
                building_model_map[stype] = a.get("model_id", "")
    for s in settlements:
        mid = building_model_map.get(s["type"], "")
        if mid:
            building_entities.append({
                "grid_x":          int(s["grid_x"]),
                "grid_y":          int(s["grid_y"]),
                "entity_type":     16777216,
                "model_id":        mid,
                "yaw":             int(rng.randint(0, 360)),
                "scale":           [1.0, 1.0, 1.0],
                "stick_to_ground": True,
            })

    # -----------------------------------------------------------------------
    # 特殊纹理区域（供 mcp_writer.py texture pass 使用）
    # settlement_footprint：聚落周边 4 格范围内的踩踏泥地纹理
    # -----------------------------------------------------------------------
    special_texture_zones = []
    for s in settlements:
        sy, sx = s["grid_y"], s["grid_x"]
        zone_cells = [
            [sy + dy, sx + dx]
            for dy in range(-4, 5) for dx in range(-4, 5)
            if 0 <= sy + dy < H and 0 <= sx + dx < W
            and str(water[sy + dy, sx + dx]) == "none"
        ]
        if zone_cells:
            special_texture_zones.append({
                "texture_profile_id": "settlement_footprint",
                "cells":              zone_cells,
            })

    issues = []
    if unconnected > 0:
        issues.append(f"{unconnected} 个聚落无法通过道路连接（可能被水域隔断）")
    for s in settlements:
        if not s["near_water"]:
            issues.append(f"聚落 {s['id']} ({s['type']}) 距水源超过 20 格")

    result = {
        "settlements":             settlements,
        "roads":                   roads,
        "unconnected_settlements": unconnected,
        "road_cells":              [[y, x] for y, x in road_cells],
        "road_entities":           road_entities,
        "building_entities":       building_entities,
        "special_texture_zones":   special_texture_zones,
        "issues":                  issues,
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[generate_civilization] 聚落: {len(settlements)} | 道路段: {len(roads)} | 未连通: {unconnected}")
    print(f"[generate_civilization] 道路实体: {len(road_entities)} | 建筑实体: {len(building_entities)}")
    print(f"[generate_civilization] 完成 → {args.output}")


if __name__ == "__main__":
    main()
