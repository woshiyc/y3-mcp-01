# tests/test_cv_decoration_extract.py
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

PROTOCOL_PATH = os.path.join(os.path.dirname(__file__), '..', 'references', 'color_protocol_v1.json')

from cv_decoration_extract import load_protocol, is_gray, classify_pixel, preprocess_image
import cv2, tempfile
from PIL import Image

def _make_png(arr_rgb: np.ndarray, path: str):
    """Save RGB numpy array as PNG."""
    Image.fromarray(arr_rgb.astype(np.uint8)).save(path)

def test_load_protocol():
    proto = load_protocol(PROTOCOL_PATH)
    assert 'elements' in proto
    assert 'forest_medium' in proto['elements']
    assert proto['elements']['forest_medium']['shape'] == 'area'

def test_is_gray():
    assert is_gray(128, 128, 128, threshold=25)   # pure gray
    assert is_gray(130, 128, 129, threshold=25)   # near gray
    assert not is_gray(20, 160, 20, threshold=25) # green

def test_classify_pixel_exact():
    proto = load_protocol(PROTOCOL_PATH)
    elem_type, dist = classify_pixel(20, 160, 20, proto)
    assert elem_type == 'forest_medium'
    assert dist < 5

def test_classify_pixel_unknown():
    proto = load_protocol(PROTOCOL_PATH)
    elem_type, dist = classify_pixel(128, 128, 40, proto)  # olive-ish
    assert dist > 0  # distance is always positive

def test_preprocess_resizes():
    # Create 20x20 image, request 10x10
    arr = np.zeros((20, 20, 3), dtype=np.uint8)
    arr[0:10, 0:10] = [20, 160, 20]  # green patch
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        _make_png(arr, f.name)
        result = preprocess_image(f.name, target_w=10, target_h=10)
    assert result.shape == (10, 10, 3)

from cv_decoration_extract import extract_area_clusters

def test_area_cluster_finds_patch():
    # 100 pixels forming a 10x10 patch
    coords = [(r, c) for r in range(5, 15) for c in range(5, 15)]
    clusters = extract_area_clusters(coords, eps=4, min_samples=6, min_cluster_pixels=16)
    assert len(clusters) == 1
    cx, cz, radius = clusters[0]
    assert 5 <= cx <= 15
    assert 5 <= cz <= 15
    assert radius > 0

def test_area_cluster_rejects_small():
    # Only 9 pixels — below min_cluster_pixels=16
    coords = [(r, c) for r in range(3) for c in range(3)]
    clusters = extract_area_clusters(coords, eps=4, min_samples=6, min_cluster_pixels=16)
    assert len(clusters) == 0

def test_area_cluster_two_separate_patches():
    coords  = [(r, c) for r in range(0,  10) for c in range(0,  10)]
    coords += [(r, c) for r in range(20, 30) for c in range(20, 30)]
    clusters = extract_area_clusters(coords, eps=4, min_samples=6, min_cluster_pixels=16)
    assert len(clusters) == 2

from cv_decoration_extract import extract_point_elements, extract_path_elements

def test_point_finds_single_blob():
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[5:8, 5:8] = 1  # 9 pixels
    points = extract_point_elements(mask, min_pixels=4)
    assert len(points) == 1
    cx, cz = points[0]
    assert 5 <= cx <= 8
    assert 5 <= cz <= 8

def test_point_rejects_tiny():
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[5, 5] = 1  # single pixel
    points = extract_point_elements(mask, min_pixels=4)
    assert len(points) == 0

def test_path_finds_horizontal_line():
    mask = np.zeros((20, 30), dtype=np.uint8)
    mask[10, 5:25] = 1  # 20px horizontal line
    waypoints = extract_path_elements(mask, min_pixels=10)
    assert len(waypoints) >= 2
    for (px, pz) in waypoints:
        assert abs(pz - 10) <= 1

def test_path_rejects_short():
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[10, 5:9] = 1  # only 4 pixels
    waypoints = extract_path_elements(mask, min_pixels=10)
    assert len(waypoints) == 0

import json, tempfile, pathlib
from cv_decoration_extract import run_extraction

def test_end_to_end_extracts_forest():
    # 40x40 image: 12x12 green patch (rows 2-13, cols 2-13) = forest_medium
    arr = np.full((40, 40, 3), 128, dtype=np.uint8)  # gray background
    arr[2:14, 2:14] = [20, 160, 20]  # forest_medium 12x12 (144 pixels, well above min=16)

    with tempfile.TemporaryDirectory() as tmp:
        img_path  = str(pathlib.Path(tmp) / 'deco.png')
        out_path  = str(pathlib.Path(tmp) / 'manifest.json')
        proto_path = PROTOCOL_PATH
        catalog_path = os.path.join(os.path.dirname(__file__), '..', 'references',
                                    'decoration_model_catalog.json')
        Image.fromarray(arr).save(img_path)

        run_extraction(
            img_path=img_path,
            texture_grid=np.zeros((40, 40), dtype=np.int32),
            protocol_path=proto_path,
            catalog_path=catalog_path,
            output_path=out_path,
            grid_w=40, grid_h=40,
            theme='default'
        )

        manifest = json.loads(pathlib.Path(out_path).read_text())
        assert manifest['meta']['total_elements'] >= 1
        types = [e['type'] for e in manifest['elements']]
        assert 'forest_medium' in types
