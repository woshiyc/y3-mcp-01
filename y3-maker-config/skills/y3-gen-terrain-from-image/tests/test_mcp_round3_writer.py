import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from mcp_round3_writer import poisson_disk_positions, interpolate_path

def test_poisson_positions_count():
    import math
    positions = poisson_disk_positions(center_x=50, center_z=50,
                                        radius=8, density='medium', min_spacing=1.5)
    expected_n = int(math.pi * 8**2 * 0.30)
    # Allow ±50% due to Poisson packing randomness
    assert len(positions) > expected_n * 0.5
    assert len(positions) < expected_n * 2.0

def test_poisson_min_spacing():
    positions = poisson_disk_positions(50, 50, radius=5, density='dense', min_spacing=1.5)
    for i, (x1, z1) in enumerate(positions):
        for j, (x2, z2) in enumerate(positions):
            if i != j:
                dist = ((x1-x2)**2 + (z1-z2)**2) ** 0.5
                assert dist >= 1.3, f"Positions too close: {dist:.2f}"

def test_interpolate_path_spacing():
    waypoints = [{'x': 0, 'z': 0}, {'x': 10, 'z': 0}, {'x': 20, 'z': 0}]
    tiles = interpolate_path(waypoints, width=2, tile_spacing=1)
    xs = [t['x'] for t in tiles]
    assert min(xs) == 0
    assert max(xs) == 20

def test_interpolate_path_empty():
    assert interpolate_path([], width=2, tile_spacing=1) == []
