"""Tests for generate_terrain.py v2 additions."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import numpy as np
import pytest
from generate_terrain import (
    generate_voronoi_layout,
    generate_ridged_noise,
    apply_domain_warping,
    generate_fbm,
)


def test_voronoi_layout_returns_correct_shape():
    mask = generate_voronoi_layout("forest_valley", seed=42, W=64, H=64)
    assert mask.shape == (64, 64)
    assert mask.dtype == np.float64


def test_voronoi_layout_values_in_range():
    mask = generate_voronoi_layout("lake_plain", seed=1, W=32, H=32)
    assert mask.min() >= -1.0
    assert mask.max() <= 1.0


def test_voronoi_forest_valley_center_lower():
    """forest_valley: center should be lower than edges"""
    mask = generate_voronoi_layout("forest_valley", seed=42, W=64, H=64)
    center = mask[28:36, 28:36].mean()
    edge_top = mask[:5, :].mean()
    edge_bot = mask[-5:, :].mean()
    assert center < (edge_top + edge_bot) / 2


def test_ridged_noise_shape_and_range():
    noise = generate_ridged_noise(W=64, H=64, seed=42, octaves=4)
    assert noise.shape == (64, 64)
    assert noise.min() >= 0.0
    assert noise.max() <= 1.0


def test_domain_warping_changes_map():
    base = generate_fbm(64, 64, seed=42)
    warped = apply_domain_warping(64, 64, seed=42, octaves=4, base_scale=8)
    assert warped.shape == (64, 64)
    diff = np.abs(base - warped)
    assert diff.mean() > 0.01


def test_world_state_has_theme_and_layout_map(tmp_path):
    """End-to-end: generate_terrain writes theme + layout_map fields."""
    import json, subprocess
    config = {
        "seed": 1, "map_width": 32, "map_height": 32, "theme": "lake_plain",
        "generation_rules": {
            "fbm_octaves": 3, "water_level": 0.32, "shallow_threshold": 0.06,
            "max_cliff_level": 3, "island_mode": False,
            "river_count": 1, "crack_count": 1, "crack_length": 5,
            "allow_cracks": True, "allow_slopes": True,
            "target_water_ratio": 0.25, "target_mountain_ratio": 0.20,
        },
        "era_thresholds": {"terrain_advance_score": 70, "ecology_advance_score": 65,
                           "civilization_advance_score": 60, "max_iterations_per_era": 8,
                           "max_visual_iterations": 3},
        "mcp": {"server_url": "http://localhost:8765", "timeout_seconds": 300, "batch_size": 100}
    }
    cfg_path = tmp_path / "world_config.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/generate_terrain.py",
         "--config", str(cfg_path), "--output-dir", str(tmp_path)],
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), '..')
    )
    assert result.returncode == 0, result.stderr
    ws = json.loads((tmp_path / "world_state.json").read_text(encoding="utf-8"))
    assert "theme" in ws
    assert ws["theme"] == "lake_plain"
    assert "layout_map" in ws
    assert len(ws["layout_map"]) == 32
