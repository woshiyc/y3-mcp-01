#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cv_slope_auto.py — 自动斜坡规划脚本（像素级连通分析版）

设计目标：
  1. 最小连通性：每个 h=2/h=4 连通区域至少有一条斜坡可达
  2. 稀疏放置：保留天然屏障，让玩家有探索感
  3. delta=4 边界默认不放斜坡（自然悬崖），但孤立 h=4 区域例外

算法：
  Phase 1 - 直接扫描 height_grid，找所有相邻高度格对
  Phase 2 - 连通分析：BFS 从所有 h=0 区域出发，标记可达的 h=2/h=4 区域
  Phase 3 - 最小连通：为不可达区域找最短斜坡路径（最小格子数）
  Phase 4 - 稀疏增补：在已连通边界追加少量额外斜坡（目标斜坡率≤目标值）

用法:
  python cv_slope_auto.py \\
    --height-grid <dir>/height_grid.npy \\
    --water-mask  <dir>/water_mask_grid.npy \\
    --output-dir  <dir> \\
    [--target-slope-pct 12]   # 目标斜坡占陆地百分比（默认12%）
    [--sparse-step 4]         # 每N格放1格斜坡（稀疏度）
    [--allow-delta4-for-isolated]  # 孤立h=4区域可在delta=4处放斜坡
"""

import argparse
import json
import os
import random
from collections import defaultdict, deque

import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: 像素级相邻扫描
# ─────────────────────────────────────────────────────────────────────────────

def scan_adjacent_pairs(height_grid: np.ndarray,
                         water_mask: np.ndarray) -> dict:
    """扫描所有相邻格对，按高度组合分类。

    Returns:
        pairs: dict[(h_low, h_high)] → list of (low_x, low_z) 低侧格坐标
    """
    H, W = height_grid.shape
    pairs = defaultdict(list)

    for z in range(H):
        for x in range(W):
            if water_mask[z, x] or height_grid[z, x] < 0:
                continue
            h_here = int(height_grid[z, x])

            for dz, dx in [(0, 1), (1, 0)]:  # 只看右和下，避免重复
                nz, nx = z + dz, x + dx
                if nz >= H or nx >= W:
                    continue
                if water_mask[nz, nx] or height_grid[nz, nx] < 0:
                    continue
                h_neighbor = int(height_grid[nz, nx])
                delta = h_neighbor - h_here

                if delta == 0:
                    continue
                elif delta > 0:
                    # here=低侧
                    pairs[(h_here, h_neighbor)].append((x, z))
                else:
                    # neighbor=低侧
                    pairs[(h_neighbor, h_here)].append((nx, nz))

    return pairs


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: 连通分析（BFS，像素级）
# ─────────────────────────────────────────────────────────────────────────────

def find_connected_components(height_grid: np.ndarray,
                               water_mask: np.ndarray,
                               target_h: int) -> np.ndarray:
    """找 target_h 层的连通分量，返回 (H,W) 标签矩阵（0=非本层，1..N=分量ID）。"""
    H, W = height_grid.shape
    mask = (height_grid == target_h) & ~water_mask
    labeled = np.zeros((H, W), dtype=np.int32)
    n = 0

    for z in range(H):
        for x in range(W):
            if mask[z, x] and labeled[z, x] == 0:
                n += 1
                q = deque([(z, x)])
                labeled[z, x] = n
                while q:
                    cz, cx = q.popleft()
                    for dz, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                        nz, nx = cz+dz, cx+dx
                        if 0<=nz<H and 0<=nx<W and mask[nz,nx] and labeled[nz,nx]==0:
                            labeled[nz, nx] = n
                            q.append((nz, nx))

    return labeled, n


def build_adjacency_from_grid(height_grid: np.ndarray,
                               water_mask: np.ndarray,
                               labeled_low: np.ndarray,
                               labeled_high: np.ndarray,
                               h_low: int,
                               h_high: int) -> dict:
    """从 height_grid 直接建立低层组件→高层组件的连接关系。

    Returns:
        adj: dict[(low_comp, high_comp)] → list of (low_x, low_z)
    """
    H, W = height_grid.shape
    adj = defaultdict(list)

    for z in range(H):
        for x in range(W):
            if height_grid[z, x] != h_low or water_mask[z, x]:
                continue
            low_comp = int(labeled_low[z, x])
            if low_comp == 0:
                continue
            for dz, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                nz, nx = z+dz, x+dx
                if 0<=nz<H and 0<=nx<W and height_grid[nz,nx] == h_high and not water_mask[nz,nx]:
                    high_comp = int(labeled_high[nz, nx])
                    if high_comp > 0:
                        adj[(low_comp, high_comp)].append((x, z))

    return adj


def compute_reachability(height_grid: np.ndarray,
                          water_mask: np.ndarray) -> tuple:
    """
    计算从 h=0 出发，哪些 h=2/h=4 连通区域可达。

    Returns:
        h2_labeled, h4_labeled: 各层标签矩阵
        h2_reachable: set of h=2 component IDs reachable from h=0
        h4_reachable: set of h=4 component IDs reachable from h=2
        adj_02: dict[(h0_comp, h2_comp)] → [(low_x, low_z)]
        adj_24: dict[(h2_comp, h4_comp)] → [(low_x, low_z)]
    """
    h0_labeled, _ = find_connected_components(height_grid, water_mask, 0)
    h2_labeled, n2 = find_connected_components(height_grid, water_mask, 2)
    h4_labeled, n4 = find_connected_components(height_grid, water_mask, 4)

    # h=0 ↔ h=2 adjacency
    adj_02 = build_adjacency_from_grid(height_grid, water_mask,
                                        h0_labeled, h2_labeled, 0, 2)
    # h=2 ↔ h=4 adjacency
    adj_24 = build_adjacency_from_grid(height_grid, water_mask,
                                        h2_labeled, h4_labeled, 2, 4)

    # h=0 所有组件视为可达起点
    h2_reachable = set()
    for (_, h2_comp) in adj_02.keys():
        h2_reachable.add(h2_comp)

    # h=4 可达 = 与任意可达 h=2 相邻
    h4_reachable = set()
    for (h2_comp, h4_comp) in adj_24.keys():
        if h2_comp in h2_reachable:
            h4_reachable.add(h4_comp)

    return (h0_labeled, h2_labeled, h4_labeled,
            h2_reachable, h4_reachable,
            adj_02, adj_24, n2, n4)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: 最小连通斜坡
# ─────────────────────────────────────────────────────────────────────────────

def find_nearest_slope_for_component(height_grid, water_mask,
                                      labeled_high, comp_id,
                                      adj_map, h_low, h_high):
    """为孤立组件找到最近的可用斜坡格子（与低层相邻的一个像素）。"""
    H, W = height_grid.shape
    # 遍历该组件的所有像素，找与低层相邻的格子
    best = None
    for z in range(H):
        for x in range(W):
            if labeled_high[z, x] != comp_id:
                continue
            # 找低层邻居
            for dz, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                nz, nx = z+dz, x+dx
                if 0<=nz<H and 0<=nx<W and height_grid[nz,nx] == h_low and not water_mask[nz,nx]:
                    # 返回低侧格子坐标
                    return [(nx, nz)]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4: 稀疏增补
# ─────────────────────────────────────────────────────────────────────────────

def sparse_sample(cells: list, step: int, max_count: int = None) -> list:
    """从 cells 中每 step 格取 1 格，限制最多 max_count 个。"""
    selected = cells[::step]
    if max_count:
        selected = selected[:max_count]
    return selected


# ─────────────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="自动斜坡规划（像素级连通分析）"
    )
    parser.add_argument("--height-grid",    required=True)
    parser.add_argument("--water-mask",     required=True)
    parser.add_argument("--output-dir",     default=".")
    parser.add_argument("--target-slope-pct", type=float, default=12.0,
                        help="目标斜坡占陆地百分比（默认12）")
    parser.add_argument("--sparse-step",    type=int, default=4,
                        help="每N格放1格斜坡（默认4）")
    parser.add_argument("--max-slope-per-boundary", type=int, default=20,
                        help="每段边界最多放的斜坡格子数（默认20）")
    parser.add_argument("--allow-delta4-for-isolated", action="store_true",
                        help="孤立h=4区域允许在delta=4处放斜坡（否则保留为悬崖）")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    rng = random.Random(args.seed)

    # ── 加载 ───────────────────────────────────────────────────────────────────
    print("[Step 1] 加载数据 ...")
    height_grid = np.load(args.height_grid).astype(np.int32)
    water_mask  = np.load(args.water_mask).astype(bool)
    H, W = height_grid.shape

    land_total = int(((height_grid >= 0) & ~water_mask).sum())
    target_slope = int(land_total * args.target_slope_pct / 100)
    print(f"  陆地格子: {land_total}，目标斜坡: {target_slope} ({args.target_slope_pct:.0f}%)")

    # ── 连通分析 ───────────────────────────────────────────────────────────────
    print("\n[Step 2] 像素级连通分析 ...")
    (h0_lab, h2_lab, h4_lab,
     h2_reach, h4_reach,
     adj_02, adj_24, n2, n4) = compute_reachability(height_grid, water_mask)

    n2_isolated = n2 - len(h2_reach)
    n4_isolated = n4 - len(h4_reach)
    print(f"  h=2: {n2} 个区域，{len(h2_reach)} 可达，{n2_isolated} 孤立")
    print(f"  h=4: {n4} 个区域，{len(h4_reach)} 可达，{n4_isolated} 孤立")

    # ── 最小连通斜坡（强制） ────────────────────────────────────────────────────
    print("\n[Step 3] 最小连通斜坡 ...")
    forced_slope_cells = set()

    # 孤立 h=2 区域：强制在 h=0↔h=2 边界放 1 格斜坡
    for comp_id in range(1, n2 + 1):
        if comp_id in h2_reach:
            continue
        cells = find_nearest_slope_for_component(
            height_grid, water_mask, h2_lab, comp_id, adj_02, 0, 2
        )
        for c in cells:
            forced_slope_cells.add(c)
        if cells:
            h2_reach.add(comp_id)  # 标记为现在可达

    print(f"  孤立h=2强制斜坡: {len(forced_slope_cells)} 格")

    forced_h4 = 0
    # 孤立 h=4 区域：强制在 h=2↔h=4 边界放 1 格斜坡
    for comp_id in range(1, n4 + 1):
        if comp_id in h4_reach:
            continue
        cells = find_nearest_slope_for_component(
            height_grid, water_mask, h4_lab, comp_id, adj_24, 2, 4
        )
        if cells:
            for c in cells:
                forced_slope_cells.add(c)
            h4_reach.add(comp_id)
            forced_h4 += 1
        elif args.allow_delta4_for_isolated:
            # 找 h=0↔h=4 相邻（只在允许时）
            cells04 = find_nearest_slope_for_component(
                height_grid, water_mask, h4_lab, comp_id, {}, 0, 4
            )
            for c in cells04:
                forced_slope_cells.add(c)

    print(f"  孤立h=4强制斜坡: {forced_h4} 个区域")
    print(f"  强制斜坡合计: {len(forced_slope_cells)} 格")

    # ── 稀疏增补 ───────────────────────────────────────────────────────────────
    print("\n[Step 4] 稀疏增补 ...")
    extra_slope_cells = set()

    remaining_budget = max(0, target_slope - len(forced_slope_cells))
    print(f"  剩余预算: {remaining_budget} 格")

    # 对所有 h=0↔h=2 边界做稀疏采样
    for (low_comp, high_comp), cells in adj_02.items():
        if not cells or remaining_budget <= 0:
            break
        # 随机打乱后稀疏采样
        shuffled = list(cells)
        rng.shuffle(shuffled)
        selected = sparse_sample(shuffled, args.sparse_step,
                                  max_count=args.max_slope_per_boundary)
        for c in selected:
            if c not in forced_slope_cells:
                extra_slope_cells.add(c)
                remaining_budget -= 1

    # 对所有 h=2↔h=4 边界做稀疏采样（更保守）
    for (low_comp, high_comp), cells in adj_24.items():
        if not cells or remaining_budget <= 0:
            break
        shuffled = list(cells)
        rng.shuffle(shuffled)
        selected = sparse_sample(shuffled, args.sparse_step * 2,
                                  max_count=args.max_slope_per_boundary // 2)
        for c in selected:
            if c not in forced_slope_cells:
                extra_slope_cells.add(c)
                remaining_budget -= 1

    all_slope_cells = forced_slope_cells | extra_slope_cells
    total_slope = len(all_slope_cells)
    print(f"  额外斜坡: {len(extra_slope_cells)} 格")
    print(f"  斜坡合计: {total_slope} 格 ({total_slope*100//max(land_total,1)}% 陆地)")

    # ── 构建 cells_override 格式输出 ───────────────────────────────────────────
    slope_list = [{"x": int(c[0]), "z": int(c[1])} for c in sorted(all_slope_cells)]

    out = {
        "mode": "pixel_level",
        "total_slope_cells": total_slope,
        "slope_pct_of_land": round(total_slope * 100 / max(land_total, 1), 1),
        "stats": {
            "h2_zones": n2, "h2_isolated": n2 - len(h2_reach),
            "h4_zones": n4, "h4_isolated": n4 - len(h4_reach),
            "forced": len(forced_slope_cells),
            "extra": len(extra_slope_cells),
        },
        # 直接提供 slope_cells 列表，供 gen_round1_csv.py 使用
        "slope_cells": slope_list,
    }

    path = os.path.join(args.output_dir, "slope_decision.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 斜坡规划完成: {path}")

    # 合理性评估
    if total_slope < land_total * 0.03:
        print(f"  ⚠️  斜坡比例偏低（{total_slope*100//land_total}%），部分高地可能较难到达")
    elif total_slope > land_total * 0.20:
        print(f"  ⚠️  斜坡比例偏高（{total_slope*100//land_total}%），建议增大 --sparse-step")
    else:
        print(f"  ✅ 斜坡比例合理（{total_slope*100//land_total}%）")

    isolated_remaining = (n2 - len(h2_reach)) + (n4 - len(h4_reach))
    if isolated_remaining > 0:
        print(f"  ⚠️  仍有 {isolated_remaining} 个孤立区域无法到达（可运行 cv_height_smooth.py 后重试）")


if __name__ == "__main__":
    main()
