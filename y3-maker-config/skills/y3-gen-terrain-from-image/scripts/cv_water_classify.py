#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cv_water_classify.py — 水域类型分类脚本

根据 AI 输出的水域簇类型分类（深水/浅水/平面水），
为每个水域格子分配具体水体类型，生成 water_type_grid.npy。

输入:
  labels.npy              — K-means 聚类标签（全图分辨率）
  water_type_clusters.json — AI 输出的水域类型分类
  water_mask_grid.npy     — 二值水域掩码（网格分辨率）

输出:
  water_type_grid.npy     — 每格水体类型 (0=陆地, 1=深水, 2=浅水, 3=平面水)
  water_type_preview.png  — 可视化预览

水体类型编码:
  0 = land       陆地（不变）
  1 = deep_water 深水（不可通行，挖2层）
  2 = shallow_water 浅水（可通行，挖1层）
  3 = plain_water 平面水（可通行，不挖地形）

用法:
  python cv_water_classify.py \\
    --labels      <dir>/labels.npy \\
    --water-types <dir>/water_type_clusters.json \\
    --water-mask  <dir>/water_mask_grid.npy \\
    --output-dir  <dir>
"""

import argparse
import json
import os
import sys

import numpy as np

WATER_TYPE_CODES = {
    "deep_water":    1,
    "shallow_water": 2,
    "plain_water":   3,
}

WATER_TYPE_COLORS = {   # BGR for preview
    0: (80,  160,  80),  # 陆地：绿
    1: (130,  40,  25),  # 深水：深海蓝
    2: (200, 160,  70),  # 浅水：青蓝
    3: (90,  100,  45),  # 平面水：暗蓝绿
}


def build_cluster_type_map(water_type_clusters: dict) -> dict:
    """构建 cluster_id → water_type_code 映射表。"""
    mapping = {}
    for type_key, code in WATER_TYPE_CODES.items():
        clusters_key = f"{type_key}_clusters"
        for cid in water_type_clusters.get(clusters_key, []):
            mapping[int(cid)] = code
    return mapping


def classify_water_grid(labels_full: np.ndarray,
                         water_mask_grid: np.ndarray,
                         cluster_type_map: dict) -> np.ndarray:
    """将水域格子按聚类标签映射到水体类型。

    通过最近邻采样，从全图分辨率的 labels 中读取每个网格格子的聚类 ID，
    再查表得到水体类型。

    Args:
        labels_full:      (H_full, W_full) int，全图聚类标签
        water_mask_grid:  (H_grid, W_grid) bool，网格分辨率水域掩码
        cluster_type_map: cluster_id → water_type_code

    Returns:
        water_type_grid: (H_grid, W_grid) int8
    """
    H_grid, W_grid = water_mask_grid.shape
    H_full, W_full = labels_full.shape

    scale_h = H_full / H_grid
    scale_w = W_full / W_grid

    water_type_grid = np.zeros((H_grid, W_grid), dtype=np.int8)

    for gz in range(H_grid):
        for gx in range(W_grid):
            if not water_mask_grid[gz, gx]:
                continue
            # 采样全图分辨率中对应位置的聚类标签
            fz = min(int((gz + 0.5) * scale_h), H_full - 1)
            fx = min(int((gx + 0.5) * scale_w), W_full - 1)
            cluster_id = int(labels_full[fz, fx])
            water_type = cluster_type_map.get(cluster_id, 1)  # 默认深水
            water_type_grid[gz, gx] = water_type

    return water_type_grid


def generate_preview(water_type_grid: np.ndarray, output_path: str) -> None:
    """生成水体类型可视化预览图。"""
    try:
        import cv2
    except ImportError:
        print("  ⚠️  opencv 未安装，跳过预览图")
        return

    H, W = water_type_grid.shape
    scale = max(1, min(4, 512 // max(H, W)))
    img = np.zeros((H * scale, W * scale, 3), dtype=np.uint8)

    for z in range(H):
        for x in range(W):
            color = WATER_TYPE_COLORS.get(int(water_type_grid[z, x]), (128, 128, 128))
            img[z*scale:(z+1)*scale, x*scale:(x+1)*scale] = color

    cv2.imwrite(output_path, img)
    print(f"  ✅ 预览图: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="水域类型分类 — 将二值水域掩码细化为深水/浅水/平面水三类"
    )
    parser.add_argument("--labels",      required=True, help="labels.npy（全图分辨率聚类标签）")
    parser.add_argument("--water-types", required=True, help="water_type_clusters.json（AI 分类结果）")
    parser.add_argument("--water-mask",  required=True, help="water_mask_grid.npy（网格分辨率）")
    parser.add_argument("--output-dir",  default=".",   help="输出目录")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # ── 加载数据 ──────────────────────────────────────────────────────────────
    print("[Step 1] 加载数据 ...")
    labels_full    = np.load(args.labels)
    water_mask_grid = np.load(args.water_mask).astype(bool)

    with open(args.water_types, "r", encoding="utf-8") as f:
        water_type_clusters = json.load(f)

    H_grid, W_grid = water_mask_grid.shape
    H_full, W_full = labels_full.shape
    print(f"  标签矩阵（全图）: {W_full}×{H_full}")
    print(f"  水域掩码（网格）: {W_grid}×{H_grid}")
    print(f"  深水簇: {water_type_clusters.get('deep_water_clusters', [])}")
    print(f"  浅水簇: {water_type_clusters.get('shallow_water_clusters', [])}")
    print(f"  平面水簇: {water_type_clusters.get('plain_water_clusters', [])}")

    # ── 构建分类映射 ──────────────────────────────────────────────────────────
    cluster_type_map = build_cluster_type_map(water_type_clusters)
    print(f"\n[Step 2] 聚类→类型映射: {cluster_type_map}")

    if not cluster_type_map:
        print("  ⚠️  无水域簇分类信息，所有水域格子默认设为深水")

    # ── 分类 ─────────────────────────────────────────────────────────────────
    print("\n[Step 3] 分类水域格子 ...")
    water_type_grid = classify_water_grid(labels_full, water_mask_grid, cluster_type_map)

    # 统计
    total_water = int(water_mask_grid.sum())
    deep_count    = int(np.sum(water_type_grid == 1))
    shallow_count = int(np.sum(water_type_grid == 2))
    plain_count   = int(np.sum(water_type_grid == 3))
    print(f"  总水域格: {total_water}")
    print(f"  深水:    {deep_count} ({deep_count*100//max(total_water,1)}%)")
    print(f"  浅水:    {shallow_count} ({shallow_count*100//max(total_water,1)}%)")
    print(f"  平面水:  {plain_count} ({plain_count*100//max(total_water,1)}%)")

    # ── 保存 ─────────────────────────────────────────────────────────────────
    out_path = os.path.join(args.output_dir, "water_type_grid.npy")
    np.save(out_path, water_type_grid)
    print(f"\n  ✅ water_type_grid.npy: {out_path}")

    preview_path = os.path.join(args.output_dir, "water_type_preview.png")
    generate_preview(water_type_grid, preview_path)

    print("\n✅ 水域类型分类完成！")
    print("   下一步: 将 water_type_grid.npy 传给 gen_round1_csv.py --water-type-grid")


if __name__ == "__main__":
    main()
