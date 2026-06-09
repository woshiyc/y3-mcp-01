#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
"""
cv_height_reader.py — 高度图读取脚本

将灰度高度图直接转换为 Y3 地形高度网格，无需 AI 参与，纯像素阈值操作。

高度映射规则（与高度图生成协议对应）:
  像素值   0~ 63  → terrain_height = 0  (平原基准, 0层悬崖)
  像素值  64~127  → terrain_height = 2  (丘陵, 1层悬崖)
  像素值 128~191  → terrain_height = 4  (山地, 2层悬崖)
  像素值 192~255  → terrain_height = 6  (高山, 3层悬崖)

输出:
  height_full.npy       — 原图分辨率的高度矩阵，供 cv_delighting.py 使用
  height_grid.npy       — 网格分辨率的高度矩阵，供 cv_height_boundary.py 使用
                          (若未提供 --grid-size 则与 height_full.npy 相同)
  height_grid_preview.png — 高度层级可视化

用法:
  python cv_height_reader.py <height_map_path> --output-dir <dir>
  python cv_height_reader.py <height_map_path> --output-dir <dir> --grid-size 128x128
"""

import argparse
import json
import os
import sys

import numpy as np


# 默认灰度阈值 → Y3 terrain_height 映射
DEFAULT_THRESHOLDS   = [64, 128, 192]   # 分级边界（左闭右开）
DEFAULT_HEIGHT_VALUES = [0, 2, 4, 6]    # 对应各层的 Y3 terrain_height

# 高度层可视化颜色 (BGR)
HEIGHT_PREVIEW_COLORS = {
    0: (80,  160,  80),   # 浅绿  — 平原
    2: (60,  110,  90),   # 橄榄绿 — 丘陵
    4: (50,   75, 120),   # 蓝棕  — 山地
    6: (210, 215, 220),   # 灰白  — 高山
}


def gray_to_height_grid(gray: np.ndarray,
                         thresholds=None,
                         height_values=None) -> np.ndarray:
    """将灰度图按阈值映射为 Y3 terrain_height 网格。

    Args:
        gray:          (H, W) uint8 灰度图
        thresholds:    分级边界列表，默认 [64, 128, 192]
        height_values: 各层高度值，默认 [0, 2, 4, 6]

    Returns:
        height_grid: (H, W) int32，每格 terrain_height 值
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if height_values is None:
        height_values = DEFAULT_HEIGHT_VALUES

    bins = [0] + list(thresholds) + [256]
    height_grid = np.zeros(gray.shape, dtype=np.int32)
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        h_val = height_values[i] if i < len(height_values) else height_values[-1]
        height_grid[(gray >= lo) & (gray < hi)] = h_val
    return height_grid


def resize_height_grid(height_grid: np.ndarray,
                        target_h: int,
                        target_w: int) -> np.ndarray:
    """将高度网格缩放到目标分辨率（使用最近邻插值，保持离散值不变）。"""
    try:
        import cv2
        resized = cv2.resize(height_grid.astype(np.float32),
                             (target_w, target_h),
                             interpolation=cv2.INTER_NEAREST)
        return resized.astype(np.int32)
    except ImportError:
        # fallback: numpy 手动最近邻
        z_indices = (np.arange(target_h) * height_grid.shape[0] / target_h).astype(int)
        x_indices = (np.arange(target_w) * height_grid.shape[1] / target_w).astype(int)
        return height_grid[np.ix_(z_indices, x_indices)]


def compute_stats(height_grid: np.ndarray, height_values=None) -> dict:
    """统计各高度层的格子数量和占比。"""
    if height_values is None:
        height_values = DEFAULT_HEIGHT_VALUES
    total = height_grid.size
    stats = {}
    for h in sorted(set(height_values)):
        count = int(np.sum(height_grid == h))
        stats[h] = {"count": count, "pct": round(count * 100.0 / total, 1)}
    return stats


def generate_preview(height_grid: np.ndarray, output_path: str) -> None:
    """生成高度层级可视化预览图。"""
    try:
        import cv2
    except ImportError:
        print("  ⚠️  opencv 未安装，跳过预览图生成")
        return

    H, W = height_grid.shape
    preview = np.full((H, W, 3), 50, dtype=np.uint8)  # 默认深灰底色
    for h_val, color in HEIGHT_PREVIEW_COLORS.items():
        preview[height_grid == h_val] = color

    cv2.imwrite(output_path, preview)


def load_as_gray(image_path: str) -> np.ndarray:
    """加载图片并转为灰度图，支持 PNG/JPG/WEBP。"""
    try:
        import cv2
    except ImportError:
        print("[ERROR] 需要 opencv-python: pip install opencv-python")
        sys.exit(1)

    img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        print(f"[ERROR] 无法读取图片: {image_path}")
        sys.exit(1)

    if len(img.shape) == 2:
        return img.astype(np.uint8)
    elif img.shape[2] == 4:
        # RGBA → 灰度
        bgr = img[:, :, :3]
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    else:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def main():
    parser = argparse.ArgumentParser(
        description="高度图读取 — 将灰度高度图转为 Y3 terrain_height 网格（无需AI）"
    )
    parser.add_argument("height_map", help="高度图路径（灰度PNG，4个离散色阶）")
    parser.add_argument("--output-dir", default=".", help="输出目录")
    parser.add_argument(
        "--thresholds", default="64,128,192",
        help="灰度分级阈值，逗号分隔（默认 64,128,192）"
    )
    parser.add_argument(
        "--height-values", default="0,2,4,6",
        help="各层 Y3 terrain_height 值，逗号分隔（默认 0,2,4,6）"
    )
    parser.add_argument(
        "--grid-size", default=None,
        help="目标网格分辨率 WxH（如 128x128），用于输出 height_grid.npy；"
             "不提供时与原图相同"
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    thresholds    = [int(x) for x in args.thresholds.split(",")]
    height_values = [int(x) for x in args.height_values.split(",")]

    # ── Step 1: 加载高度图 ──────────────────────────────────────────────
    print("[Step 1] 加载高度图 ...")
    gray = load_as_gray(args.height_map)
    H, W = gray.shape
    print(f"  路径: {args.height_map}")
    print(f"  尺寸: {W}×{H}")
    print(f"  灰度范围: [{gray.min()}, {gray.max()}]")
    print(f"  阈值: {thresholds}  →  高度层: {height_values}")

    # ── Step 2: 转为高度网格（全分辨率）──────────────────────────────────
    print("\n[Step 2] 阈值分级 → height_full.npy ...")
    height_full = gray_to_height_grid(gray, thresholds, height_values)

    stats_full = compute_stats(height_full, height_values)
    print("  高度层分布:")
    for h_val, stat in sorted(stats_full.items()):
        bar = "█" * max(1, int(stat["pct"] // 2))
        print(f"    h={h_val}: {stat['count']:>7} 格 ({stat['pct']:>5.1f}%) {bar}")

    full_path = os.path.join(args.output_dir, "height_full.npy")
    np.save(full_path, height_full)
    print(f"  ✅ 保存: {full_path}")

    # ── Step 3: 网格分辨率版本 ──────────────────────────────────────────
    print("\n[Step 3] 生成网格分辨率版 height_grid.npy ...")
    if args.grid_size:
        gw, gh = [int(x) for x in args.grid_size.lower().split("x")]
        print(f"  目标网格: {gw}×{gh}")
        height_grid = resize_height_grid(height_full, gh, gw)

        stats_grid = compute_stats(height_grid, height_values)
        print("  网格高度层分布:")
        for h_val, stat in sorted(stats_grid.items()):
            print(f"    h={h_val}: {stat['count']:>6} 格 ({stat['pct']:>5.1f}%)")
    else:
        print("  未指定 --grid-size，height_grid.npy 与 height_full.npy 相同")
        height_grid = height_full

    grid_path = os.path.join(args.output_dir, "height_grid.npy")
    np.save(grid_path, height_grid)
    print(f"  ✅ 保存: {grid_path}")

    # ── Step 4: 预览图 ──────────────────────────────────────────────────
    print("\n[Step 4] 生成预览图 ...")
    preview_path = os.path.join(args.output_dir, "height_grid_preview.png")
    generate_preview(height_grid, preview_path)
    print(f"  ✅ 预览图: {preview_path}")

    # ── Step 5: 元数据 ──────────────────────────────────────────────────
    meta = {
        "source": args.height_map,
        "original_size": {"width": W, "height": H},
        "grid_size": {"width": int(height_grid.shape[1]),
                      "height": int(height_grid.shape[0])},
        "thresholds": thresholds,
        "height_values": height_values,
        "stats_full": {str(k): v for k, v in stats_full.items()},
    }
    meta_path = os.path.join(args.output_dir, "height_reader_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 高度图读取完成！")
    print(f"   height_full.npy  → cv_delighting.py （法线贴图计算）")
    print(f"   height_grid.npy  → cv_height_boundary.py （高度边界分析）")


if __name__ == "__main__":
    main()
