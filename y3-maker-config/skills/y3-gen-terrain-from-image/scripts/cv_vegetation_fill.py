#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cv_vegetation_fill.py — 植被填充脚本（规则映射，零 AI）

根据 texture_grid.csv 中的纹理类型，自动为各地面区域分配植被，
通过 MCP 调用 terrain_vegetation_draw_block 写入 Y3 编辑器。

映射规则（纹理组 → 植被类型 + 密度）：
  草地系   → 草丛（中密度）
  秋色系   → 枯草/落叶草（低密度）
  沙漠系   → 无植被 或 稀疏荒草
  岩石系   → 无植被
  冰雪系   → 无植被
  沼泽系   → 芦苇（中密度）
  水域边缘 → 水草/芦苇（低密度）

用法:
  python cv_vegetation_fill.py \\
    --texture-grid <dir>/texture_grid.csv \\
    --water-mask <dir>/water_mask_grid.npy \\
    --map-info <dir>/map_info.json \\
    --output-dir <dir> \\
    [--dry-run]
"""

import argparse
import csv
import json
import os
import sys
import time

import numpy as np

try:
    import requests
except ImportError:
    requests = None


# ─────────────────────────────────────────────────────────────────────────────
# 纹理 ID → 纹理组映射（来自 texture_group_catalog.json）
# ─────────────────────────────────────────────────────────────────────────────

# 主要纹理组对应的纹理 ID（从 texture_group_catalog.json 提取）
TEXTURE_GROUP_MAP = {
    # 草地系
    5:5, 6:5, 14:5, 50:5, 51:5, 103:5, 132:5, 134:5, 135:5,
    145:5, 146:5, 170:5, 178:5, 179:5, 194:5, 198:5, 199:5,
    217:5, 219:5, 223:5, 226:5, 227:5,
    # 秋色系
    154:2, 153:2, 155:2, 161:2,
    # 沙漠系
    11:3, 12:3, 138:3, 165:3, 180:3, 181:3,
    # 岩石系（默认 0 = 无植被）
    # 冰雪系（默认 0 = 无植被）
    90:4, 91:4, 92:4,
    # 沼泽系
    # 腐化地/沼泽
    225:6, 224:6,
}

# 植被组规则
# group_id → {"vegetation_types": [...], "density": 0.0~1.0, "label": ""}
VEGETATION_RULES = {
    0:  {"vegetation_types": [],           "density": 0.0,  "label": "无植被"},
    1:  {"vegetation_types": [1, 2, 3],    "density": 0.6,  "label": "稀疏草丛"},
    2:  {"vegetation_types": [4, 5],       "density": 0.4,  "label": "枯草落叶"},
    3:  {"vegetation_types": [6],          "density": 0.15, "label": "稀疏荒草"},
    4:  {"vegetation_types": [],           "density": 0.0,  "label": "冰雪无植被"},
    5:  {"vegetation_types": [1, 2, 3],    "density": 0.7,  "label": "草地植被"},
    6:  {"vegetation_types": [7, 8],       "density": 0.5,  "label": "沼泽芦苇"},
}

# 水域边缘（邻接水域的陆地）→ 水草
WATER_EDGE_RULE = {
    "vegetation_types": [8, 9],
    "density": 0.3,
    "label": "水边草苇",
}


def get_texture_group(texture_id: int) -> int:
    """纹理 ID → 植被规则组 ID（0=无植被，5=草地，...）"""
    return TEXTURE_GROUP_MAP.get(texture_id, 0)


def load_texture_grid(path: str, H: int, W: int) -> np.ndarray:
    grid = np.zeros((H, W), dtype=np.int32)
    with open(path, "r", encoding="utf-8") as f:
        for z, row in enumerate(csv.reader(f)):
            for x, val in enumerate(row):
                try:
                    grid[z, x] = int(val.strip())
                except ValueError:
                    pass
    return grid


def detect_water_edge(water_mask: np.ndarray) -> np.ndarray:
    """找出所有紧邻水域的陆地格子。"""
    H, W = water_mask.shape
    edge = np.zeros((H, W), dtype=bool)
    for z in range(H):
        for x in range(W):
            if water_mask[z, x]:
                continue
            for dz, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                nz, nx = z + dz, x + dx
                if 0 <= nz < H and 0 <= nx < W and water_mask[nz, nx]:
                    edge[z, x] = True
                    break
    return edge


def build_vegetation_plan(texture_grid: np.ndarray,
                           water_mask: np.ndarray) -> list:
    """根据纹理和水域边缘，生成植被放置计划。

    Returns:
        list of {"x", "z", "vegetation_type", "density", "label"}
    """
    H, W = texture_grid.shape
    water_edge = detect_water_edge(water_mask)
    plan = []

    # 采样步长（每 2 格采样一次，避免过密）
    sample_step = 2

    for z in range(0, H, sample_step):
        for x in range(0, W, sample_step):
            if water_mask[z, x]:
                continue

            if water_edge[z, x]:
                rule = WATER_EDGE_RULE
            else:
                group_id = get_texture_group(int(texture_grid[z, x]))
                rule = VEGETATION_RULES.get(group_id, VEGETATION_RULES[0])

            if not rule["vegetation_types"] or rule["density"] <= 0:
                continue

            # 按密度决定是否放置（随机采样）
            import random
            if random.random() > rule["density"]:
                continue

            veg_type = random.choice(rule["vegetation_types"])
            plan.append({
                "x": int(x),
                "z": int(z),
                "vegetation_type": veg_type,
                "density": rule["density"],
                "label": rule["label"],
            })

    return plan


# ─────────────────────────────────────────────────────────────────────────────
# MCP 写入
# ─────────────────────────────────────────────────────────────────────────────

def call_mcp(url: str, tool_name: str, arguments: dict, timeout: int = 60) -> str:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    # SSE 解析
    for line in resp.text.strip().splitlines():
        if line.startswith("data: "):
            data = json.loads(line[6:])
            content = data.get("result", {}).get("content", [])
            return content[0].get("text", "") if content else ""
    return resp.text


def world_to_foliage_grid(world_x: float, world_z: float,
                           map_w: int, map_h: int) -> tuple:
    """世界坐标 → 植被网格坐标（简化估算）。

    Y3 植被网格与地形网格有固定比例关系，实际转换应用引擎内部方法。
    此处按比例近似：植被格 ≈ 地形格 × 2（具体比例需根据地图验证）。
    """
    fol_x = int(world_x * 2)
    fol_z = int(world_z * 2)
    return fol_x, fol_z


def terrain_to_world(grid_x: int, grid_z: int, W: int, H: int) -> tuple:
    """地形格点坐标 → 世界坐标。"""
    wx = grid_x * 2 - (W - 1)
    wz = grid_z * 2 - (H - 1)
    return float(wx), float(wz)


def write_vegetation(plan: list, map_w: int, map_h: int,
                     mcp_url: str, batch_size: int = 200,
                     dry_run: bool = False) -> None:
    """将植被计划通过 MCP 写入 Y3 编辑器。"""
    if not plan:
        print("  无植被格子需要写入")
        return

    total = len(plan)
    written = 0

    for i in range(0, total, batch_size):
        batch = plan[i: i + batch_size]
        cells = []
        for item in batch:
            wx, wz = terrain_to_world(item["x"], item["z"], map_w, map_h)
            fx, fz = world_to_foliage_grid(wx, wz, map_w, map_h)
            cells.append({
                "x": fx,
                "z": fz,
                "vegetation_type": item["vegetation_type"],
                "density": round(item["density"], 2),
            })

        batch_label = f"[{i+1}~{min(i+batch_size, total)}/{total}]"

        if dry_run:
            written += len(batch)
            print(f"   [dry-run] {batch_label}: {len(batch)} 格")
            continue

        try:
            result = call_mcp(mcp_url, "terrain_vegetation_draw_block",
                              {"cells": cells})
            written += len(batch)
            print(f"   ✅ {batch_label}: {len(batch)} 格 → {result}")
        except Exception as e:
            print(f"   ❌ {batch_label}: 失败 ({e})")

        time.sleep(0.1)

    print(f"  植被写入完成: {written}/{total} 格")


# ─────────────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="植被填充 — 按纹理类型自动铺设草丛/芦苇等植被"
    )
    parser.add_argument("--texture-grid", required=True, help="texture_grid.csv")
    parser.add_argument("--water-mask",   required=True, help="water_mask_grid.npy")
    parser.add_argument("--map-info",     required=True, help="map_info.json")
    parser.add_argument("--output-dir",   default=".", help="输出目录（保存 vegetation_plan.json）")
    parser.add_argument("--url",          default="http://127.0.0.1:8765/mcp",
                        help="MCP Server URL")
    parser.add_argument("--dry-run",      action="store_true",
                        help="只生成计划，不实际写入 MCP")
    parser.add_argument("--batch-size",   type=int, default=200)
    args = parser.parse_args()

    if not args.dry_run and requests is None:
        print("[ERROR] 需要 requests 库: pip install requests")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    # 加载地图信息
    with open(args.map_info, "r", encoding="utf-8") as f:
        map_info = json.load(f)
    map_w = map_info.get("width", 65)
    map_h = map_info.get("height", 65)

    # 加载数据
    print("[Step 1] 加载地形数据 ...")
    water_mask = np.load(args.water_mask).astype(bool)
    H, W = water_mask.shape
    texture_grid = load_texture_grid(args.texture_grid, H, W)
    print(f"  网格尺寸: {W}×{H}")

    # 生成植被计划
    print("\n[Step 2] 生成植被放置计划 ...")
    plan = build_vegetation_plan(texture_grid, water_mask)

    # 统计
    from collections import Counter
    label_counts = Counter(item["label"] for item in plan)
    for label, count in sorted(label_counts.items()):
        print(f"  {label}: {count} 格")
    print(f"  植被总计: {len(plan)} 格")

    # 保存计划 JSON
    plan_path = os.path.join(args.output_dir, "vegetation_plan.json")
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump({"total": len(plan), "items": plan}, f,
                  ensure_ascii=False, indent=2)
    print(f"  ✅ 计划: {plan_path}")

    # MCP 写入
    print(f"\n[Step 3] {'[dry-run] 模拟' if args.dry_run else ''}MCP 写入植被 ...")
    write_vegetation(plan, map_w, map_h, args.url,
                     batch_size=args.batch_size, dry_run=args.dry_run)

    print("\n✅ 植被填充完成！")


if __name__ == "__main__":
    main()
