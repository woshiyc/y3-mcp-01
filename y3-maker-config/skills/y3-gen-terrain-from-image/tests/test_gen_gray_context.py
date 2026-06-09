# tests/test_gen_gray_context.py
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from gen_gray_context import compute_brightness_grid

def test_deep_water_brightness():
    H, W = 4, 4
    height_grid = np.zeros((H, W), dtype=np.int32)
    water_mask  = np.ones((H, W), dtype=np.uint8)   # all water
    water_type  = np.ones((H, W), dtype=np.int8)    # 1 = deep_water
    result = compute_brightness_grid(height_grid, water_mask, water_type)
    assert result.shape == (H, W)
    assert np.all(result == 20), f"Expected 20, got {result}"

def test_ground_heights():
    H, W = 1, 4
    heights = np.array([[0, 2, 4, 6]], dtype=np.int32)
    water_mask = np.zeros((H, W), dtype=np.uint8)   # no water
    water_type = np.zeros((H, W), dtype=np.int8)
    result = compute_brightness_grid(heights, water_mask, water_type)
    assert result[0, 0] == 120  # h=0
    assert result[0, 1] == 155  # h=2
    assert result[0, 2] == 190  # h=4
    assert result[0, 3] == 230  # h=6

def test_water_overrides_height():
    H, W = 1, 3
    heights = np.array([[4, 4, 4]], dtype=np.int32)   # all high
    water_mask = np.array([[0, 1, 1]], dtype=np.uint8)
    water_type = np.array([[0, 2, 3]], dtype=np.int8)  # 2=shallow, 3=plain
    result = compute_brightness_grid(heights, water_mask, water_type)
    assert result[0, 0] == 190  # ground h=4
    assert result[0, 1] == 60   # shallow_water
    assert result[0, 2] == 80   # plain_water

import json, tempfile, pathlib
from PIL import Image
from gen_gray_context import overlay_candidates, brightness_to_png

def test_overlay_candidates_draws_dot():
    # 8x8 grayscale image, overlay a 3x3 dot at (4,4)
    gray = np.full((8, 8), 120, dtype=np.uint8)
    img = Image.fromarray(gray).convert('RGB')
    candidates = [{"x": 4, "z": 4}]
    color = (255, 210, 0)  # resource_point gold
    result = overlay_candidates(img, candidates, color, dot_radius=1)
    arr = np.array(result)
    # center pixel should match color
    assert tuple(arr[4, 4]) == color

def test_main_produces_png():
    H, W = 10, 10
    height_grid = np.zeros((H, W), dtype=np.int32)
    water_mask  = np.zeros((H, W), dtype=np.uint8)
    water_type  = np.zeros((H, W), dtype=np.int8)
    spatial = {"resource_points": [{"x": 5, "z": 5}],
               "monster_lairs": [], "dungeon_entrances": [], "bridge_candidates": []}
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "gray_context.png"
        brightness_to_png(height_grid, water_mask, water_type, spatial, str(out))
        assert out.exists()
        img = Image.open(str(out))
        assert img.size == (W, H)
        img.close()
