"""
temperate_fantasy/decoration_logic.py

温带奇幻风格的装饰物识别逻辑 + 程序化布局规则。
由共享脚本通过 --style temperate_fantasy 加载。

提供两类功能：
1. validate_placement / assign_density：在 cv_decoration_extract.py 中使用
2. apply_programmatic_rules：在 AI 生成装饰图后调用，程序化写入确定性规则
"""

import json, pathlib, math
import numpy as np
from PIL import Image, ImageDraw

# 加载本风格的 rules.json
_RULES_PATH = pathlib.Path(__file__).parent / 'rules.json'
RULES = json.loads(_RULES_PATH.read_text(encoding='utf-8'))
ELEM_RULES = RULES['element_rules']
PROG_RULES = RULES['programmatic_rules']

# 从共享颜色协议读取颜色定义
_PROTO_PATH = pathlib.Path(__file__).parent.parent.parent / 'references' / 'color_protocol_v1.json'
_PROTO = json.loads(_PROTO_PATH.read_text(encoding='utf-8'))
_COLORS = {k: tuple(v['rgb']) for k, v in _PROTO['elements'].items()}


# ─────────────────────────────────────────────
#  1. 元素高度验证（供 cv_decoration_extract 调用）
# ─────────────────────────────────────────────

def validate_placement(elem_type: str, cx: float, cz: float,
                        height_grid: np.ndarray,
                        water_mask: np.ndarray) -> tuple:
    """
    验证元素是否可以放在 (cx, cz) 位置。
    返回 (ok: bool, reason: str)
    """
    if elem_type not in ELEM_RULES:
        return True, ''

    rule = ELEM_RULES[elem_type]
    r, c = int(round(cz)), int(round(cx))
    H, W = height_grid.shape

    if not (0 <= r < H and 0 <= c < W):
        return False, 'out_of_bounds'

    h = int(height_grid[r, c])

    if h in rule.get('forbidden_heights', []):
        return False, f'h={h} forbidden for {elem_type}'

    if h > rule.get('max_height', 6):
        return False, f'h={h} > max_height={rule["max_height"]}'

    min_h = rule.get('min_height', 0)
    if h < min_h:
        near_w = rule.get('near_water_exception', False) and _near_water(r, c, water_mask, radius=3)
        if not near_w:
            return False, f'h={h} < min_height={min_h}, not near water'

    return True, ''


# ─────────────────────────────────────────────
#  2. 密度分配（供 cv_decoration_extract 调用）
# ─────────────────────────────────────────────

def assign_density(elem_type: str, cx: float, cz: float,
                   height_grid: np.ndarray,
                   water_mask: np.ndarray) -> str:
    """根据地形位置为面状元素分配密度。"""
    if elem_type not in ELEM_RULES:
        return 'medium'

    rule = ELEM_RULES[elem_type]
    r, c = int(round(cz)), int(round(cx))
    H, W = height_grid.shape

    if not (0 <= r < H and 0 <= c < W):
        return 'medium'

    h = int(height_grid[r, c])
    near_w = _near_water(r, c, water_mask, radius=3)

    if near_w:
        return rule.get('density_near_water', 'medium')
    if h <= 0:
        return rule.get('density_flat', 'medium')
    return rule.get('density_hill', 'sparse')


# ─────────────────────────────────────────────
#  3. 程序化布局规则（AI 生成后调用）
# ─────────────────────────────────────────────

def apply_programmatic_rules(img_path: str,
                              height_grid: np.ndarray,
                              water_mask: np.ndarray,
                              water_type_grid: np.ndarray,
                              spatial_analysis: dict,
                              scale: int = 1) -> int:
    """
    在 AI 生成的 decoration_design.png 上程序化叠加确定性规则。
    scale: 图像相对于地形格的缩放比（1格=scale像素）

    返回新增像素数。
    """
    img = Image.open(img_path).convert('RGB')
    draw = ImageDraw.Draw(img)
    H, W = height_grid.shape
    added = 0

    def _fill_cell(r, c, color):
        nonlocal added
        x0, y0 = c * scale, r * scale
        x1, y1 = x0 + scale - 1, y0 + scale - 1
        draw.rectangle([x0, y0, x1, y1], fill=color)
        added += 1

    def _is_land(r, c):
        return (0 <= r < H and 0 <= c < W and
                not water_mask[r, c] and
                int(height_grid[r, c]) >= 0)

    # ── 规则1：地图封边（边缘 border_cells 格填充密林）──────────────
    if PROG_RULES['border_seal']['enabled']:
        bc   = PROG_RULES['border_seal']['border_cells']
        col  = _COLORS[PROG_RULES['border_seal']['element_type']]
        for r in range(H):
            for c in range(W):
                dist = min(r, c, H-1-r, W-1-c)
                if dist < bc and _is_land(r, c):
                    _fill_cell(r, c, col)

    # ── 规则2：水边植被带（水域边缘 edge_cells 格填充稀疏植被）────────
    if PROG_RULES['water_edge_vegetation']['enabled']:
        ec  = PROG_RULES['water_edge_vegetation']['edge_cells']
        col = _COLORS[PROG_RULES['water_edge_vegetation']['element_type']]
        for r in range(H):
            for c in range(W):
                if not _is_land(r, c):
                    continue
                if min(r, c, H-1-r, W-1-c) < PROG_RULES['border_seal']['border_cells']:
                    continue
                if _near_water(r, c, water_mask, radius=ec):
                    _fill_cell(r, c, col)

    # ── 规则3：危险区围林（巢穴/地牢周围填充密林）────────────────
    if PROG_RULES['danger_zone_surround']['enabled']:
        sc   = PROG_RULES['danger_zone_surround']['surround_cells']
        col  = _COLORS[PROG_RULES['danger_zone_surround']['element_type']]
        triggers = PROG_RULES['danger_zone_surround']['trigger_node_types']

        danger_centers = []
        if 'monster_lairs' in triggers or 'monster_lair' in triggers:
            danger_centers += [(int(p['x']), int(p['z'])) for p in spatial_analysis.get('monster_lairs', [])]
        if 'dungeon_entrances' in triggers or 'dungeon_entrance' in triggers:
            danger_centers += [(int(p['x']), int(p['z'])) for p in spatial_analysis.get('dungeon_entrances', [])]

        for (gx, gz) in danger_centers:
            for dr in range(-sc, sc+1):
                for dc in range(-sc, sc+1):
                    dist = math.sqrt(dr**2 + dc**2)
                    if dist > sc:
                        continue
                    nr, nc = gz+dr, gx+dc
                    if _is_land(nr, nc):
                        _fill_cell(nr, nc, col)

    img.save(img_path)
    return added


# ─────────────────────────────────────────────
#  内部工具函数
# ─────────────────────────────────────────────

def _near_water(r: int, c: int, water_mask: np.ndarray, radius: int = 3) -> bool:
    if water_mask is None:
        return False
    H, W = water_mask.shape
    for dr in range(-radius, radius+1):
        for dc in range(-radius, radius+1):
            nr, nc = r+dr, c+dc
            if 0 <= nr < H and 0 <= nc < W and water_mask[nr, nc]:
                return True
    return False
