#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
"""
cv_terrain_preview.py — 地形预览图生成脚本

读取 terrain_grid.csv + texture_grid.csv，生成综合预览图：
  - 水域：深蓝 / 青蓝 / 暗蓝绿
  - 地面 h=0：浅绿
  - 地面 h=2：橄榄绿
  - 地面 h=4：棕褐
  - 地面 h=6：灰白
  - 斜坡：黄橙色（高亮显示）

可选叠加纹理颜色（--use-texture-color），用 texture_grid.csv 的纹理 ID
对应的原图色调渲染地面区域，更接近实际游戏效果。

用法:
  python cv_terrain_preview.py \\
    --terrain-csv <dir>/terrain_grid.csv \\
    --output-dir  <dir> \\
    [--texture-csv <dir>/texture_grid.csv] \\
    [--scale 4]
"""

import argparse
import csv
import os
import sys

import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# 颜色定义（BGR）
# ─────────────────────────────────────────────────────────────────────────────

TERRAIN_COLORS = {
    # 水体
    "deep_water":    (130,  40,  25),   # 深海蓝
    "shallow_water": (200, 160,  70),   # 青蓝
    "plain_water":   (100, 100,  50),   # 暗蓝绿
    # 地面高度
    "ground_0":      (80,  160,  80),   # 浅绿  h=0 平原
    "ground_2":      (55,  110,  60),   # 橄榄绿 h=2 丘陵
    "ground_4":      (50,   80, 120),   # 棕褐  h=4 山地
    "ground_6":      (200, 205, 210),   # 灰白  h=6 高山
    # 斜坡（高亮）
    "slope":         (30,  190, 210),   # 黄橙
    # 裂缝
    "crack":         (10,   10,  10),   # 近黑
}

# 纹理 ID → 近似颜色（BGR，参考 texture-color-map.md 的渲染色）
TEXTURE_COLORS = {
    0:   (100, 100, 100),   # 无纹理
    5:   (75,  155,  75),
    6:   (80,  165,  80),
    14:  (70,  150,  70),
    50:  (85,  160,  85),
    51:  (80,  155,  80),
    90:  (210, 215, 220),   # 雪地
    91:  (200, 210, 215),
    103: (65,  140,  65),
    109: (65,  130,  65),
    132: (60,  120,  65),
    134: (70,  145,  70),
    135: (60,  115,  60),
    138: (110, 160, 165),   # 沙地
    145: (75,  150,  75),
    146: (55,  110,  60),
    147: (85,  125,  75),
    153: (80,  130,  100),
    154: (90,  135, 105),
    165: (90,  165, 185),   # 沙地偏暖
    170: (70,  145,  75),
    171: (70,  100,  90),   # 岩石
    178: (80,  155,  80),
    179: (75,  150,  75),
    180: (95,  160, 170),
    194: (85,  165,  85),   # 浅草地
    198: (80,  160,  80),
    199: (75,  155,  75),
    217: (70,  145,  70),
    219: (65,  140,  65),
    223: (80,  155,  80),
    226: (75,  150,  75),
    227: (70,  145,  70),
}


def parse_terrain_csv(path):
    grid = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.reader(f):
            parsed_row = []
            for cell in row:
                parts = cell.strip().split(",")
                t = parts[0].strip()
                h = int(parts[1]) if len(parts) > 1 else 0
                parsed_row.append((t, h))
            grid.append(parsed_row)
    return grid


def parse_texture_csv(path):
    grid = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.reader(f):
            grid.append([int(v.strip()) for v in row])
    return grid


def build_image(terrain_grid, texture_grid=None, scale=4):
    """生成 BGR 预览图。"""
    H = len(terrain_grid)
    W = len(terrain_grid[0]) if H > 0 else 0

    img = np.zeros((H * scale, W * scale, 3), dtype=np.uint8)

    for z in range(H):
        for x in range(W):
            t, h = terrain_grid[z][x]

            if t in ("deep_water", "shallow_water", "plain_water"):
                color = TERRAIN_COLORS[t]
            elif t == "slope":
                color = TERRAIN_COLORS["slope"]
            elif t == "crack":
                color = TERRAIN_COLORS["crack"]
            elif t == "ground":
                if texture_grid:
                    tid = texture_grid[z][x]
                    color = TEXTURE_COLORS.get(tid, TERRAIN_COLORS.get(f"ground_{h}", (128, 128, 128)))
                else:
                    color = TERRAIN_COLORS.get(f"ground_{h}", TERRAIN_COLORS["ground_0"])
            else:
                color = (128, 128, 128)

            img[z*scale:(z+1)*scale, x*scale:(x+1)*scale] = color

    return img


def add_legend(img, use_texture=False):
    """在图片右下角加图例。"""
    try:
        import cv2
    except ImportError:
        return img

    legend_items = [
        ("deep_water",  TERRAIN_COLORS["deep_water"],  "深水"),
        ("shallow",     TERRAIN_COLORS["shallow_water"],"浅水"),
        ("plain_w",     TERRAIN_COLORS["plain_water"],  "平面水"),
        ("h=0 平原",   TERRAIN_COLORS["ground_0"],      "h=0 平原"),
        ("h=2 丘陵",   TERRAIN_COLORS["ground_2"],      "h=2 丘陵"),
        ("h=4 山地",   TERRAIN_COLORS["ground_4"],      "h=4 山地"),
        ("slope",       TERRAIN_COLORS["slope"],         "斜坡"),
    ]

    H, W = img.shape[:2]
    lw, lh = 120, 16
    legend_h = len(legend_items) * lh + 10
    legend_y = H - legend_h - 5
    legend_x = W - lw - 5

    # 半透明背景
    overlay = img.copy()
    cv2.rectangle(overlay, (legend_x-2, legend_y-2),
                  (W-3, H-3), (30, 30, 30), -1)
    img = cv2.addWeighted(overlay, 0.6, img, 0.4, 0)

    for i, (_, color, label) in enumerate(legend_items):
        y = legend_y + i * lh
        cv2.rectangle(img, (legend_x, y), (legend_x+14, y+12), color, -1)
        brightness = int(color[0])*0.114 + int(color[1])*0.587 + int(color[2])*0.299
        txt_color = (240,240,240) if brightness < 128 else (20,20,20)
        cv2.putText(img, label, (legend_x+18, y+11),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.32, txt_color, 1)

    return img


def main():
    parser = argparse.ArgumentParser(
        description="地形预览图 — 从 terrain_grid.csv 生成综合可视化"
    )
    parser.add_argument("--terrain-csv",  required=True, help="terrain_grid.csv 路径")
    parser.add_argument("--texture-csv",  default=None,  help="texture_grid.csv 路径（可选，启用纹理色渲染）")
    parser.add_argument("--output-dir",   default=".",   help="输出目录")
    parser.add_argument("--scale",        type=int, default=4,
                        help="每格放大倍数（默认4，128×128网格→512×512图）")
    parser.add_argument("--no-legend",    action="store_true", help="不加图例")
    args = parser.parse_args()

    try:
        import cv2
    except ImportError:
        print("[ERROR] 需要 opencv-python: pip install opencv-python")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    print("[Step 1] 读取 terrain_grid.csv ...")
    terrain_grid = parse_terrain_csv(args.terrain_csv)
    H, W = len(terrain_grid), len(terrain_grid[0])
    print(f"  网格尺寸: {W}×{H}")

    texture_grid = None
    if args.texture_csv and os.path.exists(args.texture_csv):
        print("[Step 2] 读取 texture_grid.csv ...")
        texture_grid = parse_texture_csv(args.texture_csv)
        print(f"  纹理色渲染: 启用")
    else:
        print("[Step 2] 未提供 texture_grid.csv，使用高度色渲染")

    print(f"\n[Step 3] 生成预览图（scale={args.scale}）...")
    img = build_image(terrain_grid, texture_grid, scale=args.scale)

    if not args.no_legend:
        img = add_legend(img, use_texture=texture_grid is not None)

    # 保存
    suffix = "_texture" if texture_grid else "_height"
    out_path = os.path.join(args.output_dir, f"terrain_preview{suffix}.png")
    cv2.imwrite(out_path, img)
    print(f"  ✅ 预览图: {out_path}  ({img.shape[1]}×{img.shape[0]}px)")

    # 统计
    from collections import Counter
    type_counts = Counter()
    h_counts = Counter()
    for row in terrain_grid:
        for t, h in row:
            type_counts[t] += 1
            if t not in ("deep_water","shallow_water","plain_water"):
                h_counts[h] += 1

    print("\n  地形统计:")
    total = W * H
    for k in ["deep_water","shallow_water","plain_water","ground","slope","crack"]:
        if type_counts[k]:
            print(f"    {k:15s}: {type_counts[k]:5d} ({type_counts[k]*100//total}%)")
    for h in sorted(h_counts):
        if h_counts[h]:
            print(f"    ground h={h}      : {h_counts[h]:5d} ({h_counts[h]*100//total}%)")

    print(f"\n✅ 完成！预览图已保存到: {out_path}")


if __name__ == "__main__":
    main()
