#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cv_height_boundary.py — 高度边界分析脚本

根据大陆高度配置，扫描所有相邻格子间的高差，
找出高差 >= 2 的边界，为 AI 斜坡规划提供决策依据。

用法:
  python cv_height_boundary.py \
    --continent-map <dir>/continent_map_grid.npy \
    --water-mask   <dir>/water_mask_grid.npy \
    --height-config '{"1":0,"2":2,"3":4}' \
    --output-dir   <dir>

输出:
  height_grid.npy              — 每格高度值 (H, W) int32
  height_boundary_report.json  — 边界分析报告（供 AI 斜坡规划参考）
  height_boundary_preview.png  — 可视化预览图（需 opencv）
"""

import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np


def build_height_grid(continent_map, water_mask, height_config):
    """根据大陆高度配置构建每格高度矩阵。

    Args:
        continent_map: (H, W) int32，大陆编号（0=水域）
        water_mask:    (H, W) bool，True=水域
        height_config: dict[int, int]，大陆ID → 高度值（0/2/4/6…）

    Returns:
        height_grid: (H, W) int32，每格高度值；水域格填 -1（标记，不参与斜坡分析）
    """
    H, W = continent_map.shape
    height_grid = np.zeros((H, W), dtype=np.int32)

    for z in range(H):
        for x in range(W):
            if water_mask[z, x]:
                height_grid[z, x] = -1  # 水域，不参与斜坡
            else:
                cid = int(continent_map[z, x])
                height_grid[z, x] = height_config.get(cid, 0)

    return height_grid


def find_boundaries(height_grid, continent_map, water_mask):
    """扫描所有相邻陆地格，找出高差 >= 2 的边界。

    只扫描水平和垂直方向（4连通），水域格不参与。

    Returns:
        boundaries: list[dict]，每条边界包含：
            - id: int
            - low_continent: int
            - high_continent: int
            - low_height: int
            - high_height: int
            - delta: int（高差，始终为正偶数）
            - low_cells: list[{"x": int, "z": int}]  低侧格（建议铺斜坡处）
            - cell_count: int
    """
    H, W = height_grid.shape

    # key: (low_cid, high_cid) → list of (low_x, low_z)
    boundary_map = defaultdict(list)

    for z in range(H):
        for x in range(W):
            if water_mask[z, x]:
                continue
            h_here = int(height_grid[z, x])
            cid_here = int(continent_map[z, x])

            for dz, dx in [(0, 1), (1, 0)]:  # 右、下（避免重复）
                nz, nx = z + dz, x + dx
                if nz >= H or nx >= W:
                    continue
                if water_mask[nz, nx]:
                    continue

                h_neighbor = int(height_grid[nz, nx])
                cid_neighbor = int(continent_map[nz, nx])

                delta = h_neighbor - h_here
                if abs(delta) < 2:
                    continue

                if delta > 0:
                    # here=低侧, neighbor=高侧
                    low_cid, high_cid = cid_here, cid_neighbor
                    low_h, high_h = h_here, h_neighbor
                    low_x, low_z = x, z
                else:
                    low_cid, high_cid = cid_neighbor, cid_here
                    low_h, high_h = h_neighbor, h_here
                    low_x, low_z = nx, nz

                boundary_map[(low_cid, high_cid, low_h, high_h)].append((low_x, low_z))

    boundaries = []
    for bid, ((low_cid, high_cid, low_h, high_h), low_cells_raw) in enumerate(
        sorted(boundary_map.items())
    ):
        # 去重
        seen = set()
        low_cells = []
        for (lx, lz) in low_cells_raw:
            if (lx, lz) not in seen:
                seen.add((lx, lz))
                low_cells.append({"x": lx, "z": lz})

        boundaries.append({
            "id": bid,
            "low_continent": low_cid,
            "high_continent": high_cid,
            "low_height": low_h,
            "high_height": high_h,
            "delta": high_h - low_h,
            "low_cells": low_cells,
            "cell_count": len(low_cells),
        })

    return boundaries


def generate_preview(height_grid, water_mask, boundaries, output_path):
    """生成高度分区 + 边界标注的预览图。"""
    try:
        import cv2
    except ImportError:
        print("  ⚠️ opencv 未安装，跳过预览图生成")
        return

    H, W = height_grid.shape

    # 高度 → 颜色映射（BGR）
    height_colors = {
        -1: (180, 120, 60),   # 水域（蓝棕）
        0:  (120, 180, 80),   # 平原（浅绿）
        2:  (80,  140, 60),   # 丘陵（橄榄绿）
        4:  (60,  90,  110),  # 山地（蓝灰棕）
        6:  (200, 200, 210),  # 高山（灰白）
        8:  (220, 230, 240),  # 雪峰（白）
    }

    scale = max(1, min(4, 512 // max(H, W)))
    img = np.zeros((H * scale, W * scale, 3), dtype=np.uint8)

    for z in range(H):
        for x in range(W):
            h = int(height_grid[z, x])
            color = height_colors.get(h, (100, 100, 100))
            img[z * scale:(z + 1) * scale, x * scale:(x + 1) * scale] = color

    # 边界格子标为红色
    for b in boundaries:
        for cell in b["low_cells"]:
            lx, lz = cell["x"], cell["z"]
            img[lz * scale:(lz + 1) * scale, lx * scale:(lx + 1) * scale] = (0, 0, 200)

    cv2.imwrite(output_path, img)
    print(f"  ✅ 预览图: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="高度边界分析 — 找出高差边界，供 AI 斜坡规划参考"
    )
    parser.add_argument("--continent-map", required=True, help="continent_map_grid.npy 路径")
    parser.add_argument("--water-mask",    required=True, help="water_mask_grid.npy 路径")
    # 两种高度输入方式：直接传高度网格（优先）或按大陆ID的配置
    parser.add_argument("--height-grid",   default=None,
                        help="height_grid.npy 路径（cv_height_reader.py 输出，与 continent_map 同分辨率）"
                             "；提供时优先使用，忽略 --height-config")
    parser.add_argument("--height-config", default=None,
                        help='大陆高度配置 JSON，key=大陆ID，value=高度值(0/2/4/6)'
                             '；无高度图时使用，如 \'{"1":0,"2":2,"3":4}\'')
    parser.add_argument("--output-dir", default=".", help="输出目录")
    args = parser.parse_args()

    if args.height_grid is None and args.height_config is None:
        print("[ERROR] 必须提供 --height-grid 或 --height-config 之一")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    # 加载数据
    print("[Step 1] 加载 continent_map + water_mask ...")
    continent_map = np.load(args.continent_map)
    water_mask = np.load(args.water_mask).astype(bool)
    H, W = continent_map.shape
    print(f"  网格尺寸: {W}x{H}")

    # 构建高度网格
    print("\n[Step 2] 构建高度网格 ...")
    if args.height_grid:
        # 优先：直接加载 cv_height_reader.py 的输出
        print(f"  模式: 从高度图读取（{args.height_grid}）")
        height_grid_raw = np.load(args.height_grid)
        # 若尺寸不一致（高度图原图分辨率 vs 网格分辨率），做最近邻缩放
        if height_grid_raw.shape != (H, W):
            try:
                import cv2
                height_grid = cv2.resize(
                    height_grid_raw.astype(np.float32), (W, H),
                    interpolation=cv2.INTER_NEAREST
                ).astype(np.int32)
                print(f"  缩放: {height_grid_raw.shape[::-1]} → {W}x{H}")
            except ImportError:
                # numpy fallback
                z_idx = (np.arange(H) * height_grid_raw.shape[0] / H).astype(int)
                x_idx = (np.arange(W) * height_grid_raw.shape[1] / W).astype(int)
                height_grid = height_grid_raw[np.ix_(z_idx, x_idx)]
        else:
            height_grid = height_grid_raw.astype(np.int32)
        # 水域格子标记为 -1
        height_grid[water_mask] = -1
    else:
        # 备选：从 AI 手动分配的大陆高度配置构建
        print(f"  模式: 从大陆高度配置构建")
        try:
            raw = json.loads(args.height_config)
            height_config = {int(k): int(v) for k, v in raw.items()}
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[ERROR] height-config 解析失败: {e}")
            sys.exit(1)
        print(f"  高度配置: {height_config}")
        height_grid = build_height_grid(continent_map, water_mask, height_config)

    height_values = sorted(set(int(v) for v in height_grid.flat if v >= 0))
    for h in height_values:
        count = int(np.sum(height_grid == h))
        print(f"  高度 h={h}: {count} 格")

    height_path = os.path.join(args.output_dir, "height_grid.npy")
    np.save(height_path, height_grid)
    print(f"  ✅ 高度网格: {height_path}")

    # 扫描高度边界
    print("\n[Step 3] 扫描高差 >= 2 的边界 ...")
    boundaries = find_boundaries(height_grid, continent_map, water_mask)

    if not boundaries:
        print("  ✅ 无高度边界（全图等高），无需斜坡规划")
        report = {"boundaries": [], "summary": "全图等高，无需斜坡"}
    else:
        print(f"  发现 {len(boundaries)} 条高度边界:")
        for b in boundaries:
            print(
                f"    边界 #{b['id']}: 大陆{b['low_continent']}(h={b['low_height']}) ←→ "
                f"大陆{b['high_continent']}(h={b['high_height']})，"
                f"高差={b['delta']}，共 {b['cell_count']} 格低侧格子"
            )

        # 警告：高差 > 2 的边界无法直接铺斜坡
        large_delta = [b for b in boundaries if b["delta"] > 2]
        if large_delta:
            print(f"\n  ⚠️ 注意：以下 {len(large_delta)} 条边界高差 > 2，无法直接铺斜坡，")
            print("     AI 需要在高度分配时确保可通行相邻大陆高差 <= 2，")
            print("     或在此处标记为 traversable=false（自然屏障）：")
            for b in large_delta:
                print(f"     边界 #{b['id']}: 高差={b['delta']}")

        report = {
            "boundaries": boundaries,
            "summary": f"共 {len(boundaries)} 条高度边界，其中高差>2 的有 {len(large_delta)} 条",
        }

    report_path = os.path.join(args.output_dir, "height_boundary_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 边界报告: {report_path}")

    # 生成预览图
    print("\n[Step 4] 生成预览图 ...")
    preview_path = os.path.join(args.output_dir, "height_boundary_preview.png")
    generate_preview(height_grid, water_mask, boundaries, preview_path)

    print("\n✅ 高度边界分析完成！")
    print("   下一步：AI 查看 height_boundary_report.json + 原图，")
    print("   对每条边界决策 traversable(需斜坡) 或 not(自然屏障)，")
    print("   输出 slope_decision.json 后继续。")


if __name__ == "__main__":
    main()
