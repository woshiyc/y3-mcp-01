#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cv_height_smooth.py — 高度网格平滑脚本

解决 per-pixel 高度映射产生的碎片化问题：
  1. 识别每个高度层的连通区域
  2. 移除面积 < min_area 的孤立小区域（用周围主导高度填充）
  3. 迭代直到无更多小区域

重要：水域格（-1）和 h=0 格不参与清理（保留水域边界，平原是基准）

用法:
  python cv_height_smooth.py \\
    --height-grid <dir>/height_grid.npy \\
    --water-mask  <dir>/water_mask_grid.npy \\
    --output-dir  <dir> \\
    [--min-area 8]      # 小于此格数的孤立区域会被清除
    [--max-iters 5]     # 最大迭代次数
"""

import argparse
import json
import os

import numpy as np


def fill_small_components(height_grid: np.ndarray,
                           water_mask: np.ndarray,
                           target_h: int,
                           min_area: int) -> tuple:
    """移除 target_h 高度层中面积 < min_area 的孤立区域，用邻近主导高度填充。

    Returns:
        new_grid: 修改后的高度网格
        removed_count: 移除的格子数
    """
    try:
        from scipy.ndimage import label as scipy_label
    except ImportError:
        scipy_label = None

    H, W = height_grid.shape
    grid = height_grid.copy()
    mask = (grid == target_h) & ~water_mask

    if not mask.any():
        return grid, 0

    # 连通区域分析
    if scipy_label:
        labeled, n_components = scipy_label(mask)
    else:
        # 简单 BFS 实现
        labeled = np.zeros((H, W), dtype=np.int32)
        n_components = 0
        for z in range(H):
            for x in range(W):
                if mask[z, x] and labeled[z, x] == 0:
                    n_components += 1
                    q = [(z, x)]
                    labeled[z, x] = n_components
                    while q:
                        cz, cx = q.pop()
                        for dz, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                            nz, nx = cz+dz, cx+dx
                            if 0<=nz<H and 0<=nx<W and mask[nz,nx] and labeled[nz,nx]==0:
                                labeled[nz, nx] = n_components
                                q.append((nz, nx))

    removed_count = 0

    for comp_id in range(1, n_components + 1):
        comp_mask = (labeled == comp_id)
        area = int(comp_mask.sum())

        if area >= min_area:
            continue

        # 小区域：用周围主导高度填充
        ys, xs = np.where(comp_mask)

        # 收集边界邻居高度
        neighbor_heights = []
        for z, x in zip(ys, xs):
            for dz, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                nz, nx = z+dz, x+dx
                if 0<=nz<H and 0<=nx<W and not comp_mask[nz, nx] and not water_mask[nz, nx]:
                    h = grid[nz, nx]
                    if h >= 0:
                        neighbor_heights.append(h)

        if not neighbor_heights:
            fill_h = 0  # 无邻居则降为平原
        else:
            # 取最常见的邻居高度
            unique, counts = np.unique(neighbor_heights, return_counts=True)
            fill_h = int(unique[counts.argmax()])

        grid[comp_mask] = fill_h
        removed_count += area

    return grid, removed_count


def smooth_height_grid(height_grid: np.ndarray,
                        water_mask: np.ndarray,
                        min_area: int = 8,
                        max_iters: int = 5) -> tuple:
    """迭代平滑高度网格，移除碎片化的小区域。

    优先清理 h=4（最细碎），再清理 h=2。
    h=0 是基准，不清理。

    Returns:
        smoothed: 平滑后的高度网格
        stats: 每次迭代的清理统计
    """
    grid = height_grid.copy()
    stats = []

    for iteration in range(max_iters):
        iter_removed = 0

        for h in [4, 2]:  # 先清理高层，再清低层
            grid, removed = fill_small_components(grid, water_mask, h, min_area)
            iter_removed += removed

        stats.append({"iteration": iteration + 1, "removed": iter_removed})

        if iter_removed == 0:
            print(f"  迭代 {iteration+1}: 无更多小区域，提前结束")
            break
        else:
            print(f"  迭代 {iteration+1}: 清理 {iter_removed} 格")

    return grid, stats


def main():
    parser = argparse.ArgumentParser(
        description="高度网格平滑 — 移除碎片化小高度区域，提升地形连通性"
    )
    parser.add_argument("--height-grid", required=True, help="height_grid.npy 路径")
    parser.add_argument("--water-mask",  required=True, help="water_mask_grid.npy 路径")
    parser.add_argument("--output-dir",  default=".",   help="输出目录")
    parser.add_argument("--min-area",    type=int, default=8,
                        help="小于此格数的孤立区域会被清除（默认8）")
    parser.add_argument("--max-iters",   type=int, default=5,
                        help="最大迭代次数（默认5）")
    parser.add_argument("--no-overwrite", action="store_true",
                        help="输出到 height_grid_smoothed.npy 而非覆盖原文件")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print("[Step 1] 加载数据 ...")
    height_grid = np.load(args.height_grid).astype(np.int32)
    water_mask  = np.load(args.water_mask).astype(bool)
    H, W = height_grid.shape
    print(f"  网格尺寸: {W}×{H}")

    # 统计原始分布
    print("\n  原始高度分布:")
    for h in [0, 2, 4, 6]:
        cnt = int(np.sum(height_grid == h))
        if cnt:
            print(f"    h={h}: {cnt:5d} 格 ({cnt*100//H//W}%)")

    print(f"\n[Step 2] 平滑处理（min_area={args.min_area}，max_iters={args.max_iters}）...")
    smoothed, stats = smooth_height_grid(
        height_grid, water_mask,
        min_area=args.min_area,
        max_iters=args.max_iters,
    )

    # 统计平滑后分布
    print("\n  平滑后高度分布:")
    total_removed = sum(s["removed"] for s in stats)
    for h in [0, 2, 4, 6]:
        before = int(np.sum(height_grid == h))
        after  = int(np.sum(smoothed == h))
        diff = after - before
        sign = "+" if diff >= 0 else ""
        if before or after:
            print(f"    h={h}: {after:5d} 格 ({after*100//H//W}%)  [{sign}{diff:+d}]")
    print(f"  总清理格数: {total_removed}")

    # 保存
    out_name = "height_grid.npy" if not args.no_overwrite else "height_grid_smoothed.npy"
    out_path = os.path.join(args.output_dir, out_name)
    np.save(out_path, smoothed)
    print(f"\n  ✅ 已保存: {out_path}")

    # 保存元数据
    meta = {
        "min_area": args.min_area,
        "max_iters": args.max_iters,
        "total_removed": total_removed,
        "iterations": stats,
    }
    with open(os.path.join(args.output_dir, "height_smooth_meta.json"), "w") as f:
        import json; json.dump(meta, f, indent=2)

    print(f"\n✅ 高度平滑完成！")
    print(f"   下一步: 重新运行 cv_height_boundary.py 和 cv_slope_auto.py")


if __name__ == "__main__":
    main()
