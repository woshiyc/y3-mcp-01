#!/usr/bin/env python3
"""
Y3 Terrain Evolution - Terrain Analyzer

读取 world_state.json，生成 terrain_summary.json 供 LLM 评估。
也可接收 ecology_layer.json / civilization_layer.json 来生成完整摘要。
"""

import numpy as np
import json
import argparse
from pathlib import Path
from collections import deque


def _label_connected(binary_map):
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


def _touches_edge(mask):
    return bool(mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any())


def analyze_terrain_layer(ws):
    h, w = ws["height"], ws["width"]
    total = h * w

    hill_map  = np.array(ws["hill_map"],  dtype=np.float64)
    cliff_map = np.array(ws["cliff_map"], dtype=np.int32)
    water_map = np.array(ws["water_map"], dtype=object)
    slope_map = np.array(ws["slope_map"], dtype=object)
    crack_map = np.array(ws["crack_map"], dtype=bool)
    biome_map = np.array(ws["biome_map"], dtype=object)

    # ----- 基本统计 -----
    water_mask = (water_map != "none")
    land_mask  = ~water_mask

    wt_pct  = lambda t: round(float(np.sum(water_map == t)) / total * 100, 1)
    bm_pct  = lambda b: round(float(np.sum(biome_map == b)) / total * 100, 1)

    stats = {
        "total_cells":      total,
        "water_total_pct":  round(float(water_mask.sum()) / total * 100, 1),
        "deep_water_pct":   wt_pct("deep"),
        "shallow_water_pct":wt_pct("shallow"),
        "plain_water_pct":  wt_pct("plain"),
        "land_pct":         round(float(land_mask.sum()) / total * 100, 1),
        "cliff_pct":        round(float((cliff_map > 0).sum()) / total * 100, 1),
        "crack_pct":        round(float(crack_map.sum()) / total * 100, 1),
        "slope_pct":        round(float((slope_map != "none").sum()) / total * 100, 1),
    }

    biome_types = ["mountain","cliff","hill","forest","plain","wetland","coastal","water"]
    biome_distribution = {b: bm_pct(b) for b in biome_types}

    height_stats = {
        "mean": round(float(hill_map.mean()), 3),
        "max":  round(float(hill_map.max()),  3),
        "min":  round(float(hill_map.min()),  3),
        "std":  round(float(hill_map.std()),  3),
    }

    # ----- 水体分析 -----
    water_bodies = []
    if water_mask.any():
        labeled = _label_connected(water_mask)
        unique, counts = np.unique(labeled[labeled > 0], return_counts=True)
        for lbl, cnt in sorted(zip(unique, counts), key=lambda x: -x[1])[:6]:
            region = labeled == lbl
            pct = round(cnt / total * 100, 1)
            types_in = list(np.unique(water_map[region]))
            body_type = "sea" if _touches_edge(region) else ("lake" if pct > 1.5 else "pond")
            water_bodies.append({
                "size_pct":    pct,
                "type":        body_type,
                "touches_edge":bool(_touches_edge(region)),
                "water_types": types_in,
            })

    # ----- 连通性 -----
    land_connectivity = {"all_land_connected": True, "land_regions": 1, "isolated_islands": 0}
    if land_mask.any():
        ll = _label_connected(land_mask)
        unique, counts = np.unique(ll[ll > 0], return_counts=True)
        n_regions = len(unique)
        isolated = int(np.sum(counts < total * 0.01))
        land_connectivity = {
            "all_land_connected": n_regions == 1,
            "land_regions":       n_regions,
            "isolated_islands":   isolated,
        }

    # ----- 新增字段：山脉连通链 -----
    mountain_mask = (biome_map == "mountain") | (biome_map == "hill")
    if mountain_mask.any():
        labeled_m = _label_connected(mountain_mask)
        unique_m, counts_m = np.unique(labeled_m[labeled_m > 0], return_counts=True)
        chains = counts_m[counts_m >= 3]
        mountain_chain_count   = int(len(chains))
        mountain_chain_avg_len = float(chains.mean()) if len(chains) > 0 else 0.0
    else:
        mountain_chain_count   = 0
        mountain_chain_avg_len = 0.0

    # ----- 新增字段：河流合法性（river_validity_ratio）-----
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
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = ry + dy, rx + dx
                    if 0 <= ny < h and 0 <= nx < w:
                        neighbors.append(hill_map[ny, nx])
                if neighbors and hill_map[ry, rx] <= max(neighbors):
                    valid_river += 1
        river_validity_ratio = valid_river / total_river if total_river > 0 else 1.0
    else:
        river_validity_ratio = 1.0

    # ----- 新增字段：水岸平均宽度（coastal_avg_width）-----
    coastal_mask = (biome_map == "coastal")
    if coastal_mask.any():
        labeled_c = _label_connected(coastal_mask)
        _, counts_c = np.unique(labeled_c[labeled_c > 0], return_counts=True)
        coastal_avg_width = float(counts_c.mean()) if len(counts_c) > 0 else 0.0
    else:
        coastal_avg_width = 0.0

    # ----- 自动问题检测 -----
    issues = []
    if stats["water_total_pct"] < 10:
        issues.append(f"水域比例过低 ({stats['water_total_pct']}%)，地图可能过于干燥")
    if stats["water_total_pct"] > 58:
        issues.append(f"水域比例过高 ({stats['water_total_pct']}%)，陆地严重不足")
    if biome_distribution.get("mountain", 0) < 5:
        issues.append("山地比例不足 5%，地形缺乏层次")
    if biome_distribution.get("mountain", 0) > 45:
        issues.append("山地比例超过 45%，可通行区域不足")
    if not land_connectivity["all_land_connected"]:
        issues.append(f"陆地分裂为 {land_connectivity['land_regions']} 个独立区域")
    if land_connectivity["isolated_islands"] > 2:
        issues.append(f"存在 {land_connectivity['isolated_islands']} 个孤立小岛")
    if stats["cliff_pct"] < 2:
        issues.append("悬崖格子不足 2%，地形缺乏立体感")
    if stats["slope_pct"] < 0.5:
        issues.append("斜坡过少，悬崖缺乏过渡")
    if stats["crack_pct"] > 10:
        issues.append(f"裂隙过多 ({stats['crack_pct']}%)，可能阻断路径")
    if stats["plain_water_pct"] < 1:
        issues.append("缺少平面水体（湖面/海面）")
    if height_stats["std"] < 0.15:
        issues.append(f"高度标准差 {height_stats['std']} 过低，地形过于平坦")

    return {
        "width":               w,
        "height":              h,
        "era":                 ws.get("era", "terrain"),
        "iteration":           ws.get("iteration", 0),
        "stats":               stats,
        "biome_distribution":  biome_distribution,
        "height_stats":        height_stats,
        "water_bodies":        water_bodies,
        "land_connectivity":          land_connectivity,
        "issues":                     issues,
        "mountain_chain_count":       mountain_chain_count,
        "mountain_chain_avg_length":  round(mountain_chain_avg_len, 1),
        "river_validity_ratio":       round(river_validity_ratio, 3),
        "coastal_avg_width":          round(coastal_avg_width, 1),
    }


def merge_ecology(summary, ecology_path):
    """将 ecology_layer.json 合并到摘要。"""
    if not ecology_path or not Path(ecology_path).exists():
        return summary
    with open(ecology_path, "r", encoding="utf-8") as f:
        eco = json.load(f)
    summary["ecology"] = {
        "total_entities":   eco.get("total_entities", 0),
        "by_category":      eco.get("by_category", {}),
        "biome_coverage":   eco.get("biome_coverage", {}),
        "issues":           eco.get("issues", []),
    }
    return summary


def merge_civilization(summary, civ_path):
    """将 civilization_layer.json 合并到摘要。"""
    if not civ_path or not Path(civ_path).exists():
        return summary
    with open(civ_path, "r", encoding="utf-8") as f:
        civ = json.load(f)
    summary["civilization"] = {
        "settlements":              civ.get("settlements", []),
        "roads":                    civ.get("roads", []),
        "total_settlements":        len(civ.get("settlements", [])),
        "total_road_segments":      len(civ.get("roads", [])),
        "unconnected_settlements":  civ.get("unconnected_settlements", 0),
        "issues":                   civ.get("issues", []),
    }
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world-state", required=True,  help="world_state.json 路径")
    parser.add_argument("--output",      required=True,  help="terrain_summary.json 输出路径")
    parser.add_argument("--ecology",     default=None,   help="ecology_layer.json 路径（可选）")
    parser.add_argument("--civilization",default=None,   help="civilization_layer.json 路径（可选）")
    args = parser.parse_args()

    with open(args.world_state, "r", encoding="utf-8") as f:
        ws = json.load(f)

    print("[analyze_terrain] 分析地形层...")
    summary = analyze_terrain_layer(ws)

    if args.ecology:
        print("[analyze_terrain] 合并生态层...")
        summary = merge_ecology(summary, args.ecology)

    if args.civilization:
        print("[analyze_terrain] 合并文明层...")
        summary = merge_civilization(summary, args.civilization)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[analyze_terrain] 摘要已保存 → {args.output}")
    print(f"  水域: {summary['stats']['water_total_pct']}% | "
          f"山地: {summary['biome_distribution'].get('mountain',0)}% | "
          f"连通: {summary['land_connectivity']['all_land_connected']} | "
          f"问题: {len(summary['issues'])} 个")


if __name__ == "__main__":
    main()
