"""Tests for generate_terrain.py v2 additions."""
import json
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


# ---------------------------------------------------------------------------
# Task 3: analyze_terrain new fields
# ---------------------------------------------------------------------------
from analyze_terrain import analyze_terrain_layer


def _make_ws(H=32, W=32, seed=42):
    """Minimal world_state dict for testing."""
    from generate_terrain import (
        generate_fbm, apply_shaping, build_cliff_map, build_water_map,
        generate_rivers, generate_cracks, build_slope_map, classify_biomes,
    )
    gen = {"fbm_octaves": 3, "water_level": 0.32, "shallow_threshold": 0.06,
           "max_cliff_level": 3, "island_mode": False,
           "river_count": 1, "crack_count": 1, "crack_length": 5,
           "allow_cracks": True, "allow_slopes": True,
           "target_water_ratio": 0.25, "target_mountain_ratio": 0.20}
    hill = generate_fbm(W, H, seed)
    hill = apply_shaping(hill, gen)
    cliff = build_cliff_map(hill, gen)
    water = build_water_map(hill, gen)
    _, water = generate_rivers(hill, water, gen, seed)
    crack = generate_cracks(hill, water, gen, seed)
    slope = build_slope_map(cliff, water, gen)
    biome = classify_biomes(hill, water, cliff, gen)
    return {
        "width": W, "height": H, "seed": seed, "era": "terrain", "iteration": 0,
        "hill_map": hill.tolist(), "cliff_map": cliff.tolist(),
        "water_map": water.tolist(), "slope_map": slope.tolist(),
        "crack_map": crack.tolist(), "biome_map": biome.tolist(),
    }


def test_analyze_has_mountain_chain_count():
    ws = _make_ws()
    summary = analyze_terrain_layer(ws)
    assert "mountain_chain_count" in summary
    assert isinstance(summary["mountain_chain_count"], int)
    assert summary["mountain_chain_count"] >= 0


def test_analyze_has_mountain_chain_avg_length():
    ws = _make_ws()
    summary = analyze_terrain_layer(ws)
    assert "mountain_chain_avg_length" in summary
    assert summary["mountain_chain_avg_length"] >= 0.0


def test_analyze_has_river_validity_ratio():
    ws = _make_ws()
    summary = analyze_terrain_layer(ws)
    assert "river_validity_ratio" in summary
    r = summary["river_validity_ratio"]
    assert 0.0 <= r <= 1.0


def test_analyze_has_coastal_avg_width():
    ws = _make_ws()
    summary = analyze_terrain_layer(ws)
    assert "coastal_avg_width" in summary
    assert summary["coastal_avg_width"] >= 0.0


# ---------------------------------------------------------------------------
# Task 4: A* 4-connectivity
# ---------------------------------------------------------------------------
from generate_civilization import astar_road


def test_astar_4connectivity_no_diagonal():
    """A* 不走对角线——路径中相邻两格的行或列差必须为 0。"""
    H, W = 20, 20
    passable = np.ones((H, W), dtype=bool)
    cost_map = np.ones((H, W), dtype=np.float64)
    path = astar_road((0, 0), (5, 5), passable, cost_map, H, W)
    assert path is not None
    for (y1, x1), (y2, x2) in zip(path[:-1], path[1:]):
        assert abs(y2-y1) + abs(x2-x1) == 1, f"Diagonal: ({y1},{x1})->({y2},{x2})"


def test_astar_avoids_high_cliff_cost():
    """A* 应绕过高 cost 单格，选择经过其他行的较长但总代价更低的路径。
    直线路径代价 = 8 + 100 = 108；绕行路径代价约 11。A* 应选绕行。
    """
    H, W = 10, 10
    passable = np.ones((H, W), dtype=bool)
    cost_map = np.ones((H, W), dtype=np.float64)
    cost_map[0, 5] = 100.0  # 单点高 cost（不是全列，有绕行路径）
    path = astar_road((0, 0), (0, 9), passable, cost_map, H, W)
    assert path is not None
    # A* 应绕过 (0,5) 走其他行
    assert (0, 5) not in path


# ---------------------------------------------------------------------------
# Task 5: mcp_writer.py Pass A/B/C 分组
# ---------------------------------------------------------------------------
from mcp_writer import PASS_A, PASS_B, PASS_C, PASS_GROUP, PASS_NAMES, get_progress_file


def test_pass_a_contains_only_terrain_passes():
    """Pass A 只含地形骨架相关 pass，不含纹理、植被、斜坡、实体。"""
    terrain_only = {"hill_lift", "cliff_height", "crack", "deep_water", "shallow_water", "plain_water"}
    assert set(PASS_A) == terrain_only


def test_pass_b_contains_only_textures():
    assert PASS_B == ["textures"]


def test_pass_c_order_vegetation_before_slopes_before_entities():
    """Pass C 中 vegetation < slopes < entities（斜坡必须在植被和实体之间）。"""
    assert PASS_C.index("vegetation") < PASS_C.index("slopes")
    assert PASS_C.index("slopes") < PASS_C.index("entities")


def test_pass_group_covers_all_pass_names():
    """PASS_A + PASS_B + PASS_C 合并后等于 PASS_NAMES（无遗漏，无重复）。"""
    combined = PASS_A + PASS_B + PASS_C
    assert sorted(combined) == sorted(PASS_NAMES)
    assert len(combined) == len(PASS_NAMES)


def test_pass_progress_files_are_independent(tmp_path):
    """不同 pass 的进度文件路径不同，互不干扰。"""
    path_a = get_progress_file("A", str(tmp_path))
    path_b = get_progress_file("B", str(tmp_path))
    path_c = get_progress_file("C", str(tmp_path))
    assert path_a != path_b
    assert path_b != path_c
    assert "A" in path_a
    assert "B" in path_b
    assert "C" in path_c


# ---------------------------------------------------------------------------
# Task 6: preview_server.py
# ---------------------------------------------------------------------------
import threading
import urllib.request
import urllib.error

from preview_server import TerrainHandler, run as run_preview


def _start_preview_server(output_dir, port):
    """在后台线程启动预览服务器，返回线程。"""
    t = threading.Thread(target=run_preview,
                         kwargs={"output_dir": output_dir, "port": port},
                         daemon=True)
    t.start()
    import time; time.sleep(0.3)  # 等待服务器就绪
    return t


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def _post(url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def test_preview_server_get_world_state(tmp_path):
    """GET /world_state 返回 world_state.json 内容。"""
    ws = {"width": 4, "height": 4, "seed": 1}
    (tmp_path / "world_state.json").write_text(json.dumps(ws), encoding="utf-8")
    _start_preview_server(str(tmp_path), 19877)
    status, body = _get("http://127.0.0.1:19877/world_state")
    assert status == 200
    assert body["width"] == 4


def test_preview_server_get_missing_file(tmp_path):
    """GET /ecology 在文件不存在时返回 404。"""
    _start_preview_server(str(tmp_path), 19878)
    try:
        _get("http://127.0.0.1:19878/ecology")
        assert False, "应返回 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_preview_server_screenshot_roundtrip(tmp_path):
    """POST /screenshot 存储 base64，GET /last_screenshot 取回同一值。"""
    TerrainHandler._last_screenshot_b64 = None  # 确保初始干净
    _start_preview_server(str(tmp_path), 19879)
    # 先确认初始为 null
    _, before = _get("http://127.0.0.1:19879/last_screenshot")
    assert before["image_b64"] is None
    # 上传截图
    _post("http://127.0.0.1:19879/screenshot", {"image_b64": "abc123=="})
    _, after = _get("http://127.0.0.1:19879/last_screenshot")
    assert after["image_b64"] == "abc123=="
