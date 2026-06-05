#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

"""
cv_icon_extract.py — 从装饰图中提取小图标位置，生成 icon_manifest.json

原理：
  将装饰图与原始地形块做像素差分，找出新增的图标像素
  → 连通域检测 → 按主色聚类 → 输出每个图标的坐标 + 颜色类型

用法：
  python scripts/cv_icon_extract.py \\
    --deco-dir   path/to/decoration_blocks \\   # 装饰图目录（含 0_0.png 等）
    --source-dir path/to/source_blocks     \\   # 原始地形块目录（含 source_block_0_0.png）
    --output-dir path/to/output/09         \\   # 输出目录
    --grid-cols 2 --grid-rows 2            \\   # 分块数（2x2）
    --map-w 256 --map-h 256                     # 地图格子数

输出：
  icon_manifest.json   — 所有检测到的图标坐标 + 颜色类型
  icon_mapping.json    — 颜色名→Y3实体ID 映射模板（用户填写）
"""

import argparse, json, math, pathlib, datetime, collections
import numpy as np
import cv2


# ─────────────────────────────────────────────
#  颜色命名
# ─────────────────────────────────────────────

COLOR_RULES = [
    # (name,  r_min, r_max, g_min, g_max, b_min, b_max)
    ('orange',  180, 255,  100, 200,    0, 120),
    ('cyan',      0, 120,  160, 255,  160, 255),
    ('green',     0, 120,  160, 255,    0, 120),
    ('purple',   80, 220,    0, 100,  130, 255),
    ('blue',      0,  80,   40, 140,  160, 255),
    ('yellow',  180, 255,  180, 255,    0, 100),
    ('red',     160, 255,    0,  80,    0,  80),
    ('white',   180, 255,  180, 255,  180, 255),
    ('brown',   100, 200,   40, 120,    0,  80),
    ('pink',    180, 255,   60, 160,  100, 220),
]

def classify_color(r, g, b):
    for name, r0, r1, g0, g1, b0, b1 in COLOR_RULES:
        if r0 <= r <= r1 and g0 <= g <= g1 and b0 <= b <= b1:
            return name
    # fallback: 返回最强通道
    ch = max((r, 'red'), (g, 'green'), (b, 'blue'), key=lambda x: x[0])
    return ch[1] + '_misc'


# ─────────────────────────────────────────────
#  单块提取
# ─────────────────────────────────────────────

def extract_icons_from_block(deco_path, src_path, block_row, block_col,
                              block_w, block_h, map_w, map_h,
                              diff_thresh=40, min_px=6, max_px=2000):
    """
    从一张装饰图中提取图标，返回 list of dict:
      {color_name, rgb, grid_x, grid_z, pixel_size, block_row, block_col}
    """
    deco = cv2.imread(str(deco_path))
    src  = cv2.imread(str(src_path))
    if deco is None:
        raise FileNotFoundError(f"Cannot read: {deco_path}")
    if src is None:
        raise FileNotFoundError(f"Cannot read: {src_path}")

    # 统一尺寸（以装饰图为准）
    h, w = deco.shape[:2]
    if src.shape[:2] != (h, w):
        src = cv2.resize(src, (w, h), interpolation=cv2.INTER_NEAREST)

    # BGR → RGB
    deco_rgb = cv2.cvtColor(deco, cv2.COLOR_BGR2RGB)
    src_rgb  = cv2.cvtColor(src,  cv2.COLOR_BGR2RGB)

    # 差分：找新增像素
    diff = np.abs(deco_rgb.astype(np.int32) - src_rgb.astype(np.int32))
    diff_sum = diff.sum(axis=2)                       # (H, W)
    changed = (diff_sum > diff_thresh).astype(np.uint8)

    # 连通域检测
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        changed, connectivity=8
    )

    # 每格子对应多少像素
    cell_w = w / (map_w // 2)   # 每格对应 deco 图的像素数（块内）
    cell_h = h / (map_h // 2)

    # 块在地图中的格子偏移
    grid_offset_x = block_col * (map_w // 2)
    grid_offset_z = block_row * (map_h // 2)

    results = []
    for i in range(1, num_labels):
        px_count = stats[i, cv2.CC_STAT_AREA]
        if px_count < min_px or px_count > max_px:
            continue

        cx_px = float(centroids[i, 0])   # pixel x (col)
        cz_px = float(centroids[i, 1])   # pixel z (row)

        # 提取该连通域的主色（取装饰图对应区域均值）
        comp_mask = (labels == i).astype(np.uint8)
        pixels = deco_rgb[comp_mask > 0]
        mean_rgb = pixels.mean(axis=0)
        r, g, b = int(mean_rgb[0]), int(mean_rgb[1]), int(mean_rgb[2])

        color = classify_color(r, g, b)

        # 像素坐标 → 地图格子坐标
        gx = grid_offset_x + cx_px / cell_w
        gz = grid_offset_z + cz_px / cell_h

        results.append({
            'color_name':  color,
            'rgb':         [r, g, b],
            'grid_x':      round(gx, 1),
            'grid_z':      round(gz, 1),
            'pixel_size':  int(px_count),
            'block_row':   block_row,
            'block_col':   block_col,
        })

    return results


# ─────────────────────────────────────────────
#  主流程
# ─────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--deco-dir',   required=True, help='装饰图目录（含 0_0.png / 1_1.png 等）')
    ap.add_argument('--source-dir', required=True, help='原始地形块目录（含 source_block_0_0.png）')
    ap.add_argument('--output-dir', required=True, help='输出目录')
    ap.add_argument('--grid-cols',  type=int, default=2, help='横向分块数')
    ap.add_argument('--grid-rows',  type=int, default=2, help='纵向分块数')
    ap.add_argument('--map-w',      type=int, default=256, help='地图宽度（格子数）')
    ap.add_argument('--map-h',      type=int, default=256, help='地图高度（格子数）')
    ap.add_argument('--diff-thresh',type=int, default=40,  help='差分阈值（每通道总差）')
    ap.add_argument('--min-px',     type=int, default=6,   help='图标最小像素数')
    ap.add_argument('--max-px',     type=int, default=2000,help='图标最大像素数（排除大块地形噪声）')
    args = ap.parse_args()

    deco_dir   = pathlib.Path(args.deco_dir)
    source_dir = pathlib.Path(args.source_dir)
    out_dir    = pathlib.Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_icons = []
    color_stats = collections.Counter()

    for br in range(args.grid_rows):
        for bc in range(args.grid_cols):
            deco_path = deco_dir / f'{br}_{bc}.png'
            src_path  = source_dir / f'source_block_{br}_{bc}.png'

            if not deco_path.exists():
                print(f'  [skip] {deco_path} not found')
                continue
            if not src_path.exists():
                print(f'  [skip] {src_path} not found')
                continue

            print(f'  Block ({br},{bc}): {deco_path.name} vs {src_path.name}')
            icons = extract_icons_from_block(
                deco_path, src_path,
                br, bc,
                block_w=1024, block_h=1024,
                map_w=args.map_w, map_h=args.map_h,
                diff_thresh=args.diff_thresh,
                min_px=args.min_px,
                max_px=args.max_px,
            )
            print(f'    -> {len(icons)} icons detected')
            for icon in icons:
                color_stats[icon['color_name']] += 1
            all_icons.extend(icons)

    # 添加全局 ID
    for i, icon in enumerate(all_icons):
        icon['id'] = f'icon_{i:04d}'

    # 统计各颜色
    print('\n颜色统计:')
    for name, cnt in sorted(color_stats.items(), key=lambda x: -x[1]):
        print(f'  {name:<20} {cnt} 个')

    # ── 生成 icon_manifest.json ──
    manifest = {
        'meta': {
            'generated_at': datetime.datetime.now().isoformat(),
            'total_icons': len(all_icons),
            'grid_size': {'w': args.map_w, 'h': args.map_h},
            'blocks': f'{args.grid_rows}x{args.grid_cols}',
            'color_summary': dict(color_stats),
            'note': '用 icon_mapping.json 为每种颜色指定 Y3 实体ID，然后运行 mcp_icon_writer.py 写入'
        },
        'icons': all_icons
    }
    manifest_path = out_dir / 'icon_manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\nicon_manifest.json -> {len(all_icons)} icons, {manifest_path}')

    # ── 生成 icon_mapping.json 模板 ──
    mapping = {}
    for color_name in sorted(color_stats.keys()):
        mapping[color_name] = {
            'y3_entity_id': None,      # 填入 Y3 物编实体ID
            'description':  '',        # 描述（如"橡树"、"岩石堆"）
            'place_on_ground': True,   # 是否贴地
            'count': color_stats[color_name]
        }
    mapping_path = out_dir / 'icon_mapping.json'
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'icon_mapping.json  -> {len(mapping)} color types, {mapping_path}')
    print('\n请编辑 icon_mapping.json，为每种颜色填入 y3_entity_id 后运行 mcp_icon_writer.py')


if __name__ == '__main__':
    main()
