#!/usr/bin/env python3
"""
Y3 Terrain Evolution - Ecology Generator

根据 biome_map + asset_profiles.json 生成生态层：
- 每个生物群系分配合适的模型
- 泊松盘采样确定放置坐标
- 输出 ecology_layer.json
"""

import numpy as np
import json
import argparse
from pathlib import Path
from collections import defaultdict


BIOME_DEFAULTS = {
    "mountain":  {"vegetation_density": 0.15, "monster_density": 0.4, "danger": 3},
    "cliff":     {"vegetation_density": 0.05, "monster_density": 0.3, "danger": 3},
    "hill":      {"vegetation_density": 0.45, "monster_density": 0.2, "danger": 2},
    "forest":    {"vegetation_density": 0.80, "monster_density": 0.15,"danger": 1},
    "plain":     {"vegetation_density": 0.30, "monster_density": 0.05,"danger": 0},
    "wetland":   {"vegetation_density": 0.60, "monster_density": 0.1, "danger": 1},
    "coastal":   {"vegetation_density": 0.20, "monster_density": 0.05,"danger": 0},
    "water":     {"vegetation_density": 0.00, "monster_density": 0.0, "danger": 0},
}

BIOME_CATEGORY_AFFINITY = {
    "mountain":  ["decoration", "vegetation"],
    "cliff":     ["decoration"],
    "hill":      ["vegetation", "decoration"],
    "forest":    ["vegetation", "decoration"],
    "plain":     ["vegetation", "decoration", "building"],
    "wetland":   ["vegetation", "decoration"],
    "coastal":   ["decoration", "vegetation"],
    "water":     [],
}


def poisson_sample(eligible_cells, min_dist, max_samples, rng):
    """简单排斥采样（rejection sampling）作为泊松盘近似。"""
    if len(eligible_cells) == 0:
        return []
    indices = rng.permutation(len(eligible_cells))
    samples = []
    for i in indices:
        if len(samples) >= max_samples:
            break
        cy, cx = eligible_cells[i]
        ok = True
        for sy, sx in samples:
            if abs(cy-sy) + abs(cx-sx) < min_dist:
                ok = False
                break
        if ok:
            samples.append((cy, cx))
    return samples


def select_model_for_biome(biome, profiles, rng):
    """从 asset_profiles 中为该群系选择合适模型。"""
    if not profiles:
        return None
    affinity = BIOME_CATEGORY_AFFINITY.get(biome, [])
    candidates = [
        p for p in profiles
        if p.get("category") in affinity
        and biome not in p.get("placement", {}).get("forbidden_biomes", [])
    ]
    if not candidates:
        candidates = [p for p in profiles if p.get("category") in ("vegetation", "decoration")]
    if not candidates:
        return None
    return candidates[rng.randint(len(candidates))]


def generate_ecology(ws, profiles, seed):
    H, W = ws["height"], ws["width"]
    biome_map = np.array(ws["biome_map"], dtype=object)
    water_map = np.array(ws["water_map"], dtype=object)
    rng = np.random.RandomState(seed + 500)

    # 按系统类型分离 profiles
    # system="entity_create"（默认）：3D 模型，用 entity_create_block，按 footprint_cells 间距 Poisson 采样
    # system="vegetation_draw"：地表贴片（草/花/芦苇），用 terrain_vegetation_draw_block，区域整体铺设
    entity_profiles = [p for p in profiles if p.get("system", "entity_create") == "entity_create"]
    veg_draw_profiles = [p for p in profiles if p.get("system") == "vegetation_draw"]

    entities   = []
    vegetation = []   # terrain_vegetation_draw_block 所需格子列表
    by_category = defaultdict(int)
    biome_coverage = {}
    issues = []

    for biome, biome_cfg in BIOME_DEFAULTS.items():
        if biome == "water":
            continue

        veg_density = biome_cfg["vegetation_density"]
        mon_density = biome_cfg["monster_density"]

        biome_cells = list(zip(*np.where((biome_map == biome) & (water_map == "none"))))
        if not biome_cells:
            continue

        biome_cells = [(int(y), int(x)) for y, x in biome_cells]
        n_cells = len(biome_cells)

        # ------------------------------------------------------------------
        # 3D 模型实体（entity_create_block）
        # min_dist 取候选模型中最大 footprint_cells，确保模型不互相穿插
        # footprint_cells 由用户在 asset_profiles 中填写（单位：格）
        # 换算：1格 = 50cm（09-地形系统.md），模型直径(cm) ÷ 50 = footprint_cells
        # 示例：树冠直径 3m → 300cm ÷ 50 = 6格；岩石直径 1m → 2格
        # ------------------------------------------------------------------
        affinity = BIOME_CATEGORY_AFFINITY.get(biome, [])
        candidates = [
            p for p in entity_profiles
            if p.get("category") in affinity
            and biome not in p.get("placement", {}).get("forbidden_biomes", [])
        ]
        if not candidates:
            candidates = [p for p in entity_profiles
                          if p.get("category") in ("vegetation", "decoration")]

        max_footprint = max((p.get("footprint_cells", 2) for p in candidates), default=2)
        max_veg       = max(1, int(n_cells * veg_density))
        veg_samples   = poisson_sample(biome_cells, max_footprint, max_veg, rng)

        for sy, sx in veg_samples:
            model = select_model_for_biome(biome, entity_profiles, rng)
            if model is None:
                continue
            mcp   = model.get("mcp", {})
            scale = mcp.get("scale_default", [1.0, 1.0, 1.0])
            var   = mcp.get("scale_variance", 0.15)
            s     = [round(v * (1 + rng.uniform(-var, var)), 3) for v in scale]
            yaw   = int(rng.uniform(0, 360)) if mcp.get("yaw_random", True) else 0

            entities.append({
                "layer":           "ecology",
                "category":        model.get("category", "vegetation"),
                "model_id":        model.get("model_id", ""),
                "name":            model.get("name", ""),
                "biome":           biome,
                "grid_y":          sy,
                "grid_x":          sx,
                "yaw":             yaw,
                "scale":           s,
                "stick_to_ground": mcp.get("stick_to_ground", True),
                "entity_type":     mcp.get("entity_type", 16777216),
            })
            by_category[model.get("category", "vegetation")] += 1

        # ------------------------------------------------------------------
        # 植被贴片（terrain_vegetation_draw_block）
        # 草/花/芦苇等面片，area 全覆盖，density 由 asset_profiles 配置
        # 植被类型 ID 见 decoration-model-ids.md §植被系统
        # ------------------------------------------------------------------
        for vp in veg_draw_profiles:
            applies = vp.get("applies_to_biomes", [])
            if biome not in applies:
                continue
            veg_type = vp.get("vegetation_type")
            density  = int(vp.get("density", 80))
            if veg_type is None:
                continue
            for cy, cx in biome_cells:
                vegetation.append({
                    "x":               int(cx),
                    "z":               int(cy),
                    "vegetation_type": int(veg_type),
                    "density":         density,
                })
            by_category["vegetation_draw"] += 1

        # 怪物区域标注（区域标签，不是实体）
        monster_zones = []
        if mon_density > 0:
            max_mon    = max(1, int(n_cells * mon_density * 0.1))
            mon_samples = poisson_sample(biome_cells, 8, max_mon, rng)
            for sy, sx in mon_samples:
                monster_zones.append({
                    "grid_y": sy, "grid_x": sx,
                    "danger_level": biome_cfg["danger"],
                    "radius": 5,
                })

        biome_coverage[biome] = {
            "cell_count":         n_cells,
            "entity_density":     round(len(veg_samples) / max(n_cells, 1), 3),
            "monster_zones":      len(monster_zones),
            "monster_zone_list":  monster_zones,
        }

    # 检查问题
    if len(entities) == 0 and len(vegetation) == 0:
        issues.append("未生成任何实体或植被（可能缺少 asset_profiles.json）")
    if biome_coverage.get("forest", {}).get("entity_density", 0) < 0.3:
        issues.append("森林 3D 模型密度不足 30%（可降低 footprint_cells 或提高 vegetation_density）")

    return {
        "total_entities":        len(entities),
        "total_vegetation_cells": len(vegetation),
        "by_category":           dict(by_category),
        "biome_coverage":        biome_coverage,
        "entities":              entities,
        "vegetation":            vegetation,
        "issues":                issues,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world-state",    required=True)
    parser.add_argument("--asset-profiles", default=None,  help="asset_profiles.json 路径（可选）")
    parser.add_argument("--output",         required=True)
    args = parser.parse_args()

    with open(args.world_state, "r", encoding="utf-8") as f:
        ws = json.load(f)

    profiles = []
    if args.asset_profiles and Path(args.asset_profiles).exists():
        with open(args.asset_profiles, "r", encoding="utf-8") as f:
            data = json.load(f)
        profiles = data.get("profiles", data) if isinstance(data, dict) else data
        print(f"[generate_ecology] 加载 {len(profiles)} 个模型档案")
    else:
        print("[generate_ecology] 无 asset_profiles，使用默认密度（不放置实体）")

    seed = ws.get("seed", 42)
    print(f"[generate_ecology] 生成生态层...")
    eco = generate_ecology(ws, profiles, seed)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(eco, f, ensure_ascii=False, indent=2)

    print(f"[generate_ecology] 3D实体: {eco['total_entities']} 个 | 植被格子: {eco['total_vegetation_cells']} 个")
    print(f"  分类: {eco['by_category']}")
    print(f"[generate_ecology] 完成 → {args.output}")


if __name__ == "__main__":
    main()
