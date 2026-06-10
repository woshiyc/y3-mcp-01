#!/usr/bin/env python3
"""
Y3 Terrain Evolution - World Validator

执行硬规则检查，输出 validation_report.json。
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


def validate_terrain(ws):
    errors = []
    warnings = []
    h, w = ws["height"], ws["width"]
    total = h * w

    hill  = np.array(ws["hill_map"],  dtype=np.float64)
    cliff = np.array(ws["cliff_map"], dtype=np.int32)
    water = np.array(ws["water_map"], dtype=object)
    slope = np.array(ws["slope_map"], dtype=object)
    crack = np.array(ws["crack_map"], dtype=bool)

    land_mask  = (water == "none")
    water_mask = ~land_mask

    # 1. 悬崖旁必须有斜坡过渡
    has_cliff = (cliff >= 2) & land_mask
    if has_cliff.any():
        neighbors_slope = np.zeros((h, w), dtype=bool)
        for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
            shifted = np.roll(slope != "none", dy, axis=0) if dy else np.roll(slope != "none", dx, axis=1)
            neighbors_slope |= shifted
        cliff_no_slope = has_cliff & ~neighbors_slope
        pct = float(cliff_no_slope.sum()) / total * 100
        if pct > 5:
            warnings.append(f"悬崖格子中有 {pct:.1f}% 缺少相邻斜坡（allow_slopes 可能未开启）")

    # 2. 水域不应出现孤立水体（完全被陆地包围）
    if water_mask.any():
        labeled = _label_connected(water_mask)
        unique, counts = np.unique(labeled[labeled > 0], return_counts=True)
        for lbl, cnt in zip(unique, counts):
            region = labeled == lbl
            touches = (region[0].any() or region[-1].any() or
                       region[:,0].any() or region[:,-1].any())
            if not touches and cnt < total * 0.005:
                warnings.append(f"存在孤立水体（{cnt} 格），可能无法到达")

    # 3. 陆地连通性
    if land_mask.any():
        ll = _label_connected(land_mask)
        unique, counts = np.unique(ll[ll > 0], return_counts=True)
        if len(unique) > 1:
            errors.append(f"陆地分裂为 {len(unique)} 个不连通区域（最大 {counts.max()} 格）")

    # 4. 裂隙不能占据超过 15% 的陆地
    crack_land = crack & land_mask
    crack_land_pct = float(crack_land.sum()) / max(land_mask.sum(), 1) * 100
    if crack_land_pct > 15:
        errors.append(f"裂隙占陆地面积 {crack_land_pct:.1f}%，超过 15% 上限")

    # 5. 水域比例检查
    water_pct = float(water_mask.sum()) / total * 100
    if water_pct > 70:
        errors.append(f"水域比例 {water_pct:.1f}% 超过 70%，陆地严重不足")
    if water_pct < 5:
        warnings.append(f"水域比例仅 {water_pct:.1f}%，过于干燥")

    # 6. 斜坡不能出现在水域
    slope_in_water = (slope != "none") & water_mask
    if slope_in_water.any():
        errors.append(f"存在 {int(slope_in_water.sum())} 个水域格子被标记为斜坡")

    return errors, warnings


def validate_ecology(eco):
    errors = []
    warnings = []
    if not eco:
        return errors, warnings

    total_entities = eco.get("total_entities", 0)
    if total_entities == 0:
        warnings.append("生态层无任何实体放置")

    coverage = eco.get("biome_coverage", {})
    for biome, data in coverage.items():
        if biome in ("forest", "plain") and data.get("vegetation_density", 0) < 0.1:
            warnings.append(f"{biome} 生物群系植被密度过低 ({data.get('vegetation_density', 0):.2f})")

    return errors, warnings


def validate_civilization(civ):
    errors = []
    warnings = []
    if not civ:
        return errors, warnings

    unconnected = civ.get("unconnected_settlements", 0)
    if unconnected > 0:
        errors.append(f"{unconnected} 个聚落没有道路连接")

    settlements = civ.get("settlements", [])
    for s in settlements:
        if not s.get("near_water", True):
            warnings.append(f"聚落 {s.get('id')} 距水源过远")
        if not s.get("accessible", True):
            errors.append(f"聚落 {s.get('id')} 不可到达")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world-state",   required=True)
    parser.add_argument("--ecology",       default=None)
    parser.add_argument("--civilization",  default=None)
    parser.add_argument("--output",        required=True)
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

    print("[validate_world] 执行硬规则检查...")

    t_err, t_warn = validate_terrain(ws)
    e_err, e_warn = validate_ecology(eco)
    c_err, c_warn = validate_civilization(civ)

    all_errors   = t_err + e_err + c_err
    all_warnings = t_warn + e_warn + c_warn

    passed = len(all_errors) == 0
    report = {
        "passed":   passed,
        "errors":   all_errors,
        "warnings": all_warnings,
        "summary": {
            "terrain_errors":       len(t_err),
            "terrain_warnings":     len(t_warn),
            "ecology_errors":       len(e_err),
            "ecology_warnings":     len(e_warn),
            "civilization_errors":  len(c_err),
            "civilization_warnings":len(c_warn),
        }
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    status = "✅ 通过" if passed else f"❌ 失败（{len(all_errors)} 个错误）"
    print(f"[validate_world] {status}")
    for e in all_errors:
        print(f"  ERROR: {e}")
    for w in all_warnings[:5]:
        print(f"  WARN:  {w}")
    print(f"[validate_world] 报告已保存 → {args.output}")


if __name__ == "__main__":
    main()
