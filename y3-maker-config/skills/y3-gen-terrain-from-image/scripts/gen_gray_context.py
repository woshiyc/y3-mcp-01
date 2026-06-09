# scripts/gen_gray_context.py
import numpy as np

# water_type encoding (matches cv_water_classify.py convention)
# 0=land, 1=deep_water, 2=shallow_water, 3=plain_water
_WATER_BRIGHTNESS = {1: 20, 2: 60, 3: 80}
_HEIGHT_BRIGHTNESS = {0: 120, 2: 155, 4: 190, 6: 230}


def compute_brightness_grid(height_grid: np.ndarray,
                             water_mask: np.ndarray,
                             water_type: np.ndarray) -> np.ndarray:
    """
    Returns uint8 brightness grid (H x W).
    Water cells override height. Unknown heights clamp to nearest defined value.
    """
    H, W = height_grid.shape
    result = np.zeros((H, W), dtype=np.uint8)

    for r in range(H):
        for c in range(W):
            if water_mask[r, c]:
                wt = int(water_type[r, c])
                result[r, c] = _WATER_BRIGHTNESS.get(wt, 80)
            else:
                h = int(height_grid[r, c])
                defined = sorted(_HEIGHT_BRIGHTNESS.keys())
                closest = min(defined, key=lambda x: abs(x - h))
                result[r, c] = _HEIGHT_BRIGHTNESS[closest]

    return result


import argparse, json, pathlib, sys
from PIL import Image, ImageDraw

# Candidate position colors per spatial_analysis.json key (RGB)
_CANDIDATE_COLORS = {
    'resource_points':    (255, 210,   0),
    'monster_lairs':      (150,   0, 200),
    'dungeon_entrances':  ( 70,   0, 150),
    'bridge_candidates':  (  0,  60, 220),
}


def overlay_candidates(img: Image.Image, candidates: list,
                        color: tuple, dot_radius: int = 1) -> Image.Image:
    """Draw filled square dots for candidate positions onto img (in-place copy)."""
    draw = ImageDraw.Draw(img)
    for c in candidates:
        x, z = int(c['x']), int(c['z'])
        draw.rectangle(
            [x - dot_radius, z - dot_radius, x + dot_radius, z + dot_radius],
            fill=color
        )
    return img


def brightness_to_png(height_grid, water_mask, water_type, spatial_analysis,
                       out_path, scale: int = 1):
    """
    Full pipeline: grids -> grayscale PNG with candidate overlays.
    scale: 每个格子用 scale×scale 像素表示（默认1，即1格=1像素）。
           scale=8 时输出与 2048×2048 源图等分辨率，AI绘制精度最高。
    """
    brightness = compute_brightness_grid(height_grid, water_mask, water_type)
    H, W = brightness.shape

    if scale > 1:
        # 用最近邻放大：每格扩展为 scale×scale 像素块，保持纯色无渐变
        import cv2
        upscaled = cv2.resize(brightness, (W * scale, H * scale),
                              interpolation=cv2.INTER_NEAREST)
        img = Image.fromarray(upscaled, mode='L').convert('RGB')
    else:
        img = Image.fromarray(brightness, mode='L').convert('RGB')

    # 候选位置圆点：坐标乘以 scale，半径也按比例放大（至少3px可见）
    dot_r = max(scale * 2, 3)
    for key, color in _CANDIDATE_COLORS.items():
        candidates = spatial_analysis.get(key, [])
        if candidates:
            scaled_cands = [{'x': c['x'] * scale + scale // 2,
                             'z': c['z'] * scale + scale // 2}
                            for c in candidates]
            overlay_candidates(img, scaled_cands, color, dot_radius=dot_r)

    img.save(out_path)
    grid_w, grid_h = W, H
    out_w, out_h = img.size
    print(f"gray_context.png saved {out_path}  ({out_w}x{out_h}px | {grid_w}x{grid_h}格 | scale={scale})")


def main():
    parser = argparse.ArgumentParser(description='Generate grayscale context image for Round 3')
    parser.add_argument('run_dir', help='Path to output/{run_id}/ directory')
    parser.add_argument('--scale', type=int, default=1,
                        help='每格像素数（默认1=1格1像素，推荐8=与源图等分辨率）')
    args = parser.parse_args()

    run = pathlib.Path(args.run_dir)
    import numpy as _np
    height_grid  = _np.load(str(run / 'height_grid.npy'))
    water_mask   = _np.load(str(run / 'water_mask_grid.npy'))
    water_type   = _np.load(str(run / 'water_type_grid.npy'))
    spatial      = json.loads((run / 'spatial_analysis.json').read_text(encoding='utf-8'))

    brightness_to_png(height_grid, water_mask, water_type, spatial,
                       str(run / 'gray_context.png'), scale=args.scale)


if __name__ == '__main__':
    main()
