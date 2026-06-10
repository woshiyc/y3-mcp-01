#!/usr/bin/env python3
"""
Y3 Terrain Evolution - MCP Batch Writer

将 world_state.json + ecology_layer.json + civilization_layer.json
批量写入 Y3 编辑器（通过 MCP HTTP 接口）。

写入顺序（严格不可乱，基于 terrain-adjacency-rules.md）：
  Pass 1: terrain_hill_lift_block        (hill_map，微调高度 < 0.1)
  Pass 2: terrain_set_height_block       (cliff_map，悬崖整数高度)
  Pass 3: terrain_set_crack_block        (crack_map，裂缝，terrain_height=-40)
  Pass 4: terrain_set_deep_water_block
  Pass 5: terrain_set_shallow_water_block
  Pass 6: terrain_set_plain_water_block
  Pass 7: terrain_cover_draw_block       (地形纹理，格点坐标)
  Pass 8: terrain_set_road_block         (斜坡，必须在水体/纹理之后最后刷)
  Pass 9: entity_create_block            (实体模型，世界坐标)

⚠️ 坐标系说明（来源：y3-terrain-basics.md）：
  - terrain API (Pass 1-8)：格点坐标，直接用 grid x, z
  - entity_create (Pass 9)：世界坐标，公式：
      world_x = grid_x * 2 - (map_width - 1)
      world_z = grid_z * 2 - (map_height - 1)

⚠️ 斜坡说明（来源：y3-terrain-basics.md + terrain-adjacency-rules.md）：
  - 斜坡激活条件：相邻格高差 = 2（flat=1横向/flat=2纵向）
  - 斜坡必须在所有地形/水体/纹理操作完成后最后刷
  - 道路 ≠ 斜坡，Y3 没有道路地形类型，道路通过实体摆件表现

用法（单批循环模式）：
  python mcp_writer.py --world-state output/world_state.json \\
    --ecology output/ecology_layer.json \\
    --civilization output/civilization_layer.json \\
    --texture-profiles config/texture_profiles.json \\
    --single-batch 1

AI 必须循环调用直到 BATCH_RESULT status == "all_done"。
"""

import collections
import numpy as np
import json
import argparse
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


# Pass 顺序：斜坡在水体和纹理之后（terrain-adjacency-rules.md §5）
PASS_NAMES = [
    "hill_lift",      # Pass 1: terrain_hill_lift_block
    "cliff_height",   # Pass 2: terrain_set_height_block（高度差=2处引擎自动生成斜坡）
    "crack",          # Pass 3: terrain_set_crack_block
    "deep_water",     # Pass 4: terrain_set_deep_water_block
    "shallow_water",  # Pass 5: terrain_set_shallow_water_block
    "plain_water",    # Pass 6: terrain_set_plain_water_block
    "textures",       # Pass 7: terrain_cover_draw_block
    "vegetation",     # Pass 8: terrain_vegetation_draw_block（植被贴片，非 3D 模型）
    "entities",       # Pass 9: entity_create_block
    # 斜坡不主动写（terrain-adjacency-rules.md §5.2）：
    # 引擎在 cliff_height 写完后，自动在相邻高差=2处生成斜坡。
    # slope_map 仅作为验证输出（terrain_summary），不参与 MCP 写入。
]

PROGRESS_FILE = "output/.mcp_progress.json"
TILE_SIZE     = 100  # 每批格子数
ENTITY_BATCH  = 50   # 每批实体数


# ---------------------------------------------------------------------------
# 坐标转换（来源：y3-terrain-basics.md TerrainHelper.calculate_terrain_grid_pos）
# ---------------------------------------------------------------------------

def grid_to_world(grid_x, grid_z, map_width, map_height):
    """
    格点坐标 → Y3 世界坐标（entity_create_block 专用）。
    公式来自 TerrainHelper.py::calculate_terrain_grid_pos()：
      world_x = grid_x * 2 - (W - 1)
      world_z = grid_z * 2 - (H - 1)
    注意：terrain API 直接用格点坐标，无需转换。
    """
    world_x = grid_x * 2 - (map_width - 1)
    world_z = grid_z * 2 - (map_height - 1)
    return float(world_x), float(world_z)


# ---------------------------------------------------------------------------
# MCP HTTP 调用
# ---------------------------------------------------------------------------

def call_mcp(tool_name, params, url, timeout):
    payload = json.dumps({"tool": tool_name, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"MCP 连接失败: {e}")


# ---------------------------------------------------------------------------
# 进度管理
# ---------------------------------------------------------------------------

def load_progress(progress_file):
    p = Path(progress_file)
    if p.exists():
        with open(p, "r") as f:
            return json.load(f)
    return {"current_pass": 0, "current_index": 0}


def save_progress(progress, progress_file):
    Path(progress_file).parent.mkdir(parents=True, exist_ok=True)
    with open(progress_file, "w") as f:
        json.dump(progress, f)


# ---------------------------------------------------------------------------
# 纹理分配（Pass 7）
# ---------------------------------------------------------------------------

def compute_water_distance(water_map, H, W, max_dist):
    """BFS：每格到水体（deep/shallow）的距离，上限 max_dist+1。"""
    dist = np.full((H, W), max_dist + 1, dtype=np.int32)
    queue = collections.deque()
    for y in range(H):
        for x in range(W):
            if str(water_map[y, x]) in ("deep", "shallow"):
                dist[y, x] = 0
                queue.append((y, x))
    while queue:
        cy, cx = queue.popleft()
        if dist[cy, cx] >= max_dist:
            continue
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < H and 0 <= nx < W and dist[ny, nx] > dist[cy, cx] + 1:
                dist[ny, nx] = dist[cy, cx] + 1
                queue.append((ny, nx))
    return dist


def build_texture_pass(ws, civ, texture_profiles):
    """
    构建纹理分配（terrain_cover_draw_block，格点坐标）。
    优先级：特殊叙事纹理 > 道路纹理 > 悬崖→岩石 > 中坡→裸土 > 水边→湿泥 > biome默认 > fallback
    """
    if not texture_profiles:
        return []

    H, W = ws["height"], ws["width"]
    biome_map = np.array(ws["biome_map"], dtype=object)
    cliff_map = np.array(ws["cliff_map"], dtype=np.int32)
    water_map = np.array(ws["water_map"], dtype=object)
    slope_map = np.array(ws["slope_map"], dtype=object)

    rules         = texture_profiles.get("mapping_rules", {})
    water_edge    = rules.get("water_edge_texture_range_cells", 4)
    fallback_id   = int(rules.get("default_fallback_texture_id", 170))

    terrain_by_id = {t["id"]: t for t in texture_profiles.get("terrain_textures", [])}
    special_by_id = {t["id"]: t for t in texture_profiles.get("special_textures", [])}

    def tex(pid):
        p = terrain_by_id.get(pid) or special_by_id.get(pid)
        if p:
            tid = p.get("y3_texture_id")
            if tid:
                return int(tid)
        return None

    biome_tex = {}
    for t in texture_profiles.get("terrain_textures", []):
        tid = t.get("y3_texture_id")
        if not tid:
            continue
        for biome in t.get("applies_to", {}).get("biomes", []):
            biome_tex.setdefault(biome, int(tid))

    water_dist = compute_water_distance(water_map, H, W, water_edge)

    road_cells = set()
    special_zone_map = {}
    if civ:
        for rc in civ.get("road_cells", []):
            road_cells.add((int(rc[0]), int(rc[1])))
        for zone in civ.get("special_texture_zones", []):
            pid = zone.get("texture_profile_id")
            for cell in zone.get("cells", []):
                special_zone_map[(int(cell[0]), int(cell[1]))] = pid

    assignments = []
    for y in range(H):
        for x in range(W):
            if str(water_map[y, x]) in ("deep", "shallow", "plain"):
                continue

            biome = str(biome_map[y, x])
            cl    = int(cliff_map[y, x])
            sd    = str(slope_map[y, x])
            wd    = int(water_dist[y, x])

            tid = None
            if tid is None and (y, x) in special_zone_map:
                tid = tex(special_zone_map[(y, x)])
            if tid is None and (y, x) in road_cells:
                tid = tex("road_dirt")
            if tid is None and cl > 0:
                tid = tex("rock")
            if tid is None and sd != "none":
                tid = tex("soil_bare")
            if tid is None and wd <= water_edge:
                tid = tex("mud_wet")
            if tid is None:
                tid = biome_tex.get(biome)
            if tid is None:
                tid = fallback_id

            # terrain_cover_draw_block 使用格点坐标（x, z 直接传入）
            assignments.append({
                "x": int(x),
                "z": int(y),
                "texture_type": int(tid),
            })

    return assignments


# ---------------------------------------------------------------------------
# 构建写入队列
# ---------------------------------------------------------------------------

def build_write_queue(ws, eco, civ, texture_profiles):
    H, W = ws["height"], ws["width"]
    hill_map  = np.array(ws["hill_map"],  dtype=np.float64)
    cliff_map = np.array(ws["cliff_map"], dtype=np.int32)
    water_map = np.array(ws["water_map"], dtype=object)
    slope_map = np.array(ws["slope_map"], dtype=object)
    crack_map = np.array(ws["crack_map"], dtype=bool)

    passes = {name: [] for name in PASS_NAMES}

    for y in range(H):
        for x in range(W):
            # terrain API 全部使用格点坐标（x, z），无需转换
            cell = {"x": int(x), "z": int(y)}

            # Pass 1: hill lift（微调高度，< 0.1，用于平滑地形起伏）
            hv = float(hill_map[y, x])
            if hv > 0.01:
                passes["hill_lift"].append({**cell, "height": round(hv * 10, 2), "radius": 0})

            # Pass 2: cliff（悬崖整数高度，每层 height=2）
            # y3-terrain-basics.md：1 层悬崖 = API height=2，故 cliff_map 层数 × 2
            cl = int(cliff_map[y, x])
            if cl > 0:
                passes["cliff_height"].append({**cell, "height": cl * 2, "cliff_tex_id": 0})

            # Pass 3: crack（裂缝，terrain_height=-40，专用接口）
            if crack_map[y, x]:
                passes["crack"].append(cell)

            # Pass 4-6: water
            wt = str(water_map[y, x])
            if wt == "deep":
                passes["deep_water"].append(cell)
            elif wt == "shallow":
                passes["shallow_water"].append(cell)
            elif wt == "plain":
                passes["plain_water"].append(cell)

            # slope 不主动写：引擎根据 cliff_height 写入后的高度差自动生成斜坡
            # slope_map 已在 world_state.json 中保留，供 analyze_terrain 统计用

    # Pass 7: 纹理（格点坐标）
    passes["textures"] = build_texture_pass(ws, civ, texture_profiles)

    # Pass 8: 植被贴片（格点坐标，terrain_vegetation_draw_block）
    # 植被是地表面片（草/花/芦苇等），非 3D 模型，走独立坐标系和独立 API
    # 数据来源：ecology_layer.json["vegetation"]，格式：
    #   {"x": grid_x, "z": grid_z, "vegetation_type": int, "density": int(0-100)}
    # 植被类型 ID 见 decoration-model-ids.md §植被系统
    if eco:
        for v in eco.get("vegetation", []):
            passes["vegetation"].append({
                "x":               int(v["x"]),
                "z":               int(v["z"]),
                "vegetation_type": int(v["vegetation_type"]),
                "density":         int(v.get("density", 80)),
            })

    # Pass 10: 实体（world 坐标，entity_create_block）
    # 注意：道路通过实体摆件表现，不走 terrain_set_road_block
    # （Y3 没有道路地形类型，terrain-adjacency-rules.md 道路体系）
    entity_list = []
    if eco:
        for ent in eco.get("entities", []):
            gx, gy = ent["grid_x"], ent["grid_y"]
            wx, wz = grid_to_world(gx, gy, W, H)
            entity_list.append({
                "type":            ent.get("entity_type", 16777216),
                "pos":             [wx, 0, wz],
                "model_id":        ent.get("model_id", ""),
                "yaw":             ent.get("yaw", 0),
                "pitch":           0,
                "roll":            0,
                "scale":           ent.get("scale", [1.0, 1.0, 1.0]),
                "stick_to_ground": ent.get("stick_to_ground", True),
            })

    if civ:
        # 道路实体（路面摆件，entity_create，非 terrain 操作）
        for ent in civ.get("road_entities", []):
            gx, gy = ent["grid_x"], ent["grid_y"]
            wx, wz = grid_to_world(gx, gy, W, H)
            entity_list.append({
                "type":            ent.get("entity_type", 16777216),
                "pos":             [wx, 0, wz],
                "model_id":        ent.get("model_id", ""),
                "yaw":             ent.get("yaw", 0),
                "pitch":           0,
                "roll":            0,
                "scale":           ent.get("scale", [1.0, 1.0, 1.0]),
                "stick_to_ground": True,
            })
        # 建筑/聚落实体
        for ent in civ.get("building_entities", []):
            gx, gy = ent["grid_x"], ent["grid_y"]
            wx, wz = grid_to_world(gx, gy, W, H)
            entity_list.append({
                "type":            ent.get("entity_type", 16777216),
                "pos":             [wx, 0, wz],
                "model_id":        ent.get("model_id", ""),
                "yaw":             ent.get("yaw", 0),
                "pitch":           0,
                "roll":            0,
                "scale":           ent.get("scale", [1.0, 1.0, 1.0]),
                "stick_to_ground": ent.get("stick_to_ground", True),
            })

    passes["entities"] = entity_list
    return passes


# ---------------------------------------------------------------------------
# 单批执行
# ---------------------------------------------------------------------------

def execute_single_batch(passes, progress, mcp_url, timeout, batch_size):
    current_pass_idx = progress["current_pass"]
    current_index    = progress["current_index"]

    if current_pass_idx >= len(PASS_NAMES):
        return {"status": "all_done"}

    pass_name = PASS_NAMES[current_pass_idx]
    pass_data = passes[pass_name]

    if not pass_data:
        progress["current_pass"] += 1
        progress["current_index"] = 0
        return {"status": "pass_complete", "pass": pass_name, "reason": "empty"}

    chunk = pass_data[current_index: current_index + batch_size]
    if not chunk:
        progress["current_pass"] += 1
        progress["current_index"] = 0
        total_done = sum(len(passes[n]) for n in PASS_NAMES[:current_pass_idx]) + current_index
        total_all  = sum(len(passes[n]) for n in PASS_NAMES)
        return {"status": "pass_complete", "pass": pass_name,
                "progress": f"{total_done}/{total_all}"}

    try:
        if pass_name == "hill_lift":
            call_mcp("terrain_hill_lift_block",          {"cells": chunk}, mcp_url, timeout)
        elif pass_name == "cliff_height":
            call_mcp("terrain_set_height_block",         {"cells": chunk}, mcp_url, timeout)
        elif pass_name == "crack":
            call_mcp("terrain_set_crack_block",          {"cells": chunk}, mcp_url, timeout)
        elif pass_name == "deep_water":
            call_mcp("terrain_set_deep_water_block",     {"cells": chunk}, mcp_url, timeout)
        elif pass_name == "shallow_water":
            call_mcp("terrain_set_shallow_water_block",  {"cells": chunk}, mcp_url, timeout)
        elif pass_name == "plain_water":
            call_mcp("terrain_set_plain_water_block",    {"cells": chunk}, mcp_url, timeout)
        elif pass_name == "textures":
            call_mcp("terrain_cover_draw_block",         {"cells": chunk}, mcp_url, timeout)
        elif pass_name == "vegetation":
            call_mcp("terrain_vegetation_draw_block",    {"cells": chunk}, mcp_url, timeout)
        elif pass_name == "entities":
            for i in range(0, len(chunk), ENTITY_BATCH):
                call_mcp("entity_create_block", {"entities_info": chunk[i:i + ENTITY_BATCH]},
                         mcp_url, timeout)
                time.sleep(0.5)
    except RuntimeError as e:
        print(json.dumps({"BATCH_RESULT": {"status": "error", "message": str(e)}}))
        sys.exit(1)

    progress["current_index"] += batch_size
    total_done = sum(len(passes[n]) for n in PASS_NAMES[:current_pass_idx]) + progress["current_index"]
    total_all  = sum(len(passes[n]) for n in PASS_NAMES)

    if progress["current_index"] >= len(pass_data):
        progress["current_pass"] += 1
        progress["current_index"] = 0
        status = "pass_complete" if progress["current_pass"] < len(PASS_NAMES) else "all_done"
    else:
        status = "in_progress"

    return {"status": status, "pass": pass_name, "progress": f"{total_done}/{total_all}"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world-state",      required=True)
    parser.add_argument("--ecology",          default=None)
    parser.add_argument("--civilization",     default=None)
    parser.add_argument("--texture-profiles", default=None)
    parser.add_argument("--single-batch",     type=int, default=None)
    parser.add_argument("--dry-run",          action="store_true")
    parser.add_argument("--restart",          action="store_true")
    parser.add_argument("--url",              default="http://localhost:8765")
    parser.add_argument("--timeout",          type=int, default=300)
    parser.add_argument("--progress-file",    default=PROGRESS_FILE)
    args = parser.parse_args()

    with open(args.world_state, "r", encoding="utf-8") as f:
        ws = json.load(f)

    eco = None
    if args.ecology and Path(args.ecology).exists():
        with open(args.ecology, "r", encoding="utf-8") as f:
            eco = json.load(f)

    civ = None
    if args.civilization and Path(args.civilization).exists():
        with open(args.civilization, "r", encoding="utf-8") as f:
            civ = json.load(f)

    texture_profiles = None
    if args.texture_profiles and Path(args.texture_profiles).exists():
        with open(args.texture_profiles, "r", encoding="utf-8") as f:
            texture_profiles = json.load(f)
        print(f"[mcp_writer] 已加载纹理配置")
    else:
        print("[mcp_writer] 未提供 texture_profiles，Pass 7（纹理）跳过")

    print("[mcp_writer] 构建写入队列...")
    passes = build_write_queue(ws, eco, civ, texture_profiles)
    total  = sum(len(passes[n]) for n in PASS_NAMES)

    if args.dry_run:
        print("[mcp_writer] Dry Run 统计:")
        for n in PASS_NAMES:
            print(f"  Pass {PASS_NAMES.index(n)+1} {n}: {len(passes[n])} 项")
        print(f"  总计: {total} 项")
        print(json.dumps({"BATCH_RESULT": {"status": "dry_run", "total": total}}))
        return

    if args.restart and Path(args.progress_file).exists():
        Path(args.progress_file).unlink()

    progress    = load_progress(args.progress_file)
    batch_count = args.single_batch if args.single_batch else 9999

    for _ in range(batch_count):
        result = execute_single_batch(passes, progress, args.url, args.timeout, TILE_SIZE)
        save_progress(progress, args.progress_file)
        print(f"BATCH_RESULT: {json.dumps({'BATCH_RESULT': result})}")
        if result["status"] in ("all_done", "error"):
            if result["status"] == "all_done":
                Path(args.progress_file).unlink(missing_ok=True)
            break


if __name__ == "__main__":
    main()
