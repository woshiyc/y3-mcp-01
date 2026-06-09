#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

"""
mcp_icon_writer.py — 读取 icon_manifest.json + icon_mapping.json，批量写入 Y3 实体

用法：
  python scripts/mcp_icon_writer.py \\
    --manifest  output/09/icon_manifest.json \\
    --mapping   output/09/icon_mapping.json  \\
    --dry-run                                   # 只统计不写入

映射文件格式（icon_mapping.json）：
  {
    "orange": {"y3_entity_id": 12345, "description": "橡树", "place_on_ground": true},
    "cyan":   {"y3_entity_id": 67890, "description": "岩石堆", "place_on_ground": true},
    ...
  }
  y3_entity_id 为 null 的颜色类型会被跳过。
"""

import argparse, json, pathlib, time
import urllib.request, urllib.error


# ─────────────────────────────────────────────
#  MCP 调用
# ─────────────────────────────────────────────

def call_mcp(url, tool, params, timeout=30):
    payload = json.dumps({'tool': tool, 'params': params}).encode('utf-8')
    req = urllib.request.Request(
        url, data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'error': str(e)}


def grid_to_world(gx, gz, map_w, map_h):
    """格子坐标 → Y3 世界坐标（单位：0.5m）"""
    wx = round(gx * 2 - (map_w - 1), 2)
    wz = round(gz * 2 - (map_h - 1), 2)
    return wx, wz


# ─────────────────────────────────────────────
#  主流程
# ─────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', required=True, help='icon_manifest.json 路径')
    ap.add_argument('--mapping',  required=True, help='icon_mapping.json 路径')
    ap.add_argument('--url',      default='http://localhost:23333', help='MCP Server URL')
    ap.add_argument('--dry-run',  action='store_true', help='只统计，不实际写入')
    ap.add_argument('--delay',    type=float, default=0.05, help='每次写入间隔(秒)')
    args = ap.parse_args()

    manifest = json.loads(pathlib.Path(args.manifest).read_text(encoding='utf-8'))
    mapping  = json.loads(pathlib.Path(args.mapping).read_text(encoding='utf-8'))

    meta   = manifest['meta']
    icons  = manifest['icons']
    map_w  = meta['grid_size']['w']
    map_h  = meta['grid_size']['h']

    # 统计计划
    plan = {}   # color_name → {entity_id, count, icons:[]}
    skipped_colors = []

    for icon in icons:
        cn = icon['color_name']
        mp = mapping.get(cn, {})
        eid = mp.get('y3_entity_id')
        if not eid:
            skipped_colors.append(cn)
            continue
        if cn not in plan:
            plan[cn] = {
                'entity_id':   eid,
                'description': mp.get('description', ''),
                'place_on_ground': mp.get('place_on_ground', True),
                'count': 0,
                'icons': []
            }
        plan[cn]['count'] += 1
        plan[cn]['icons'].append(icon)

    print('=' * 50)
    print(f'图标写入计划:')
    total = 0
    for cn, p in plan.items():
        print(f'  {cn:<20} entity_id={p["entity_id"]}  数量={p["count"]}  ({p["description"]})')
        total += p['count']
    if skipped_colors:
        skip_set = set(skipped_colors)
        print(f'\n跳过 (y3_entity_id=null): {", ".join(skip_set)}')
    print(f'\n合计写入: {total} 个实体')
    print('=' * 50)

    if args.dry_run:
        print('[dry-run] 未实际写入')
        return

    # 写入
    written = 0
    failed  = 0

    for cn, p in plan.items():
        print(f'\n写入 {cn} ({p["description"]}) — {p["count"]} 个 ...')
        for icon in p['icons']:
            wx, wz = grid_to_world(icon['grid_x'], icon['grid_z'], map_w, map_h)
            params = {
                'entity_id': p['entity_id'],
                'x': wx,
                'y': 0,
                'z': wz,
                'place_on_ground': p['place_on_ground'],
            }
            result = call_mcp(args.url, 'entity_create', params)
            if 'error' in result:
                print(f'  FAIL ({wx},{wz}): {result["error"]}')
                failed += 1
            else:
                written += 1
            if args.delay > 0:
                time.sleep(args.delay)

    print(f'\n写入完成: {written} 成功 / {failed} 失败 / {total - written - failed} 跳过')


if __name__ == '__main__':
    main()
