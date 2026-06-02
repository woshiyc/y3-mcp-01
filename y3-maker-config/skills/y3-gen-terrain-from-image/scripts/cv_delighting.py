#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cv_delighting.py — 光照去除脚本（De-lighting）

利用高度图推算法线贴图，自动估算光源方向，从地形图中消除光影影响，
输出干净的纹理贴图（Albedo），供后续 cv_cluster.py 使用。

原理（Lambertian 反射模型逆运算）:
  观测图像 = Albedo × Shading
  Shading  = ambient + (1 - ambient) × max(N · L, 0)
  Albedo   = 观测图像 / Shading

输入:
  terrain_map   — 原始地形图（有光影）
  height_map    — 配套灰度高度图（与地形图同构图，需空间对齐）

输出:
  albedo.png            — 去光影后的纹理贴图（→ cv_cluster.py）
  cast_shadow_mask.npy  — 投射阴影掩码（CV 聚类时可降权这些区域）
  shading_debug.png     — 计算出的光照模型（调试用）
  normal_map_debug.png  — 法线贴图可视化（调试用）
  delighting_meta.json  — 处理参数记录

用法:
  python cv_delighting.py <terrain_map> <height_map> --output-dir <dir>
  python cv_delighting.py terrain.png height.png --output-dir out/ --scale 8 --ambient 0.25
  python cv_delighting.py terrain.png height.png --output-dir out/ --light-az 135 --light-el 45
"""

import argparse
import json
import os
import sys

import numpy as np


# ──────────────────────────────────────────────────────────────────────────────
# 核心算法
# ──────────────────────────────────────────────────────────────────────────────

def linearize_gamma(img_uint8: np.ndarray, gamma: float = 2.2) -> np.ndarray:
    """sRGB gamma 解码：[0,255] uint8 → [0,1] float32 线性光"""
    return (img_uint8.astype(np.float32) / 255.0) ** gamma


def encode_gamma(img_linear: np.ndarray, gamma: float = 2.2) -> np.ndarray:
    """线性光 → sRGB gamma 编码：[0,1] float32 → [0,255] uint8"""
    return np.clip(img_linear ** (1.0 / gamma) * 255.0, 0, 255).astype(np.uint8)


def compute_normal_map(height_gray: np.ndarray, scale: float) -> np.ndarray:
    """从灰度高度图计算法线贴图。

    使用 Sobel 算子计算 x/y 梯度，归一化得到单位法线向量。

    Args:
        height_gray: (H, W) float32，归一化到 [0,1]
        scale:       地形陡峭系数，越大法线越陡

    Returns:
        normal_map: (H, W, 3) float32，每个像素为单位法线 [nx, ny, nz]
    """
    try:
        import cv2
        dx = cv2.Sobel(height_gray, cv2.CV_32F, 1, 0, ksize=3)
        dy = cv2.Sobel(height_gray, cv2.CV_32F, 0, 1, ksize=3)
    except ImportError:
        # numpy fallback
        kernel = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
        from scipy.signal import convolve2d
        dx = convolve2d(height_gray, kernel, mode='same')
        dy = convolve2d(height_gray, kernel.T, mode='same')

    nx = -dx * scale
    ny = -dy * scale
    nz = np.ones_like(nx)

    norm = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2) + 1e-8
    nx, ny, nz = nx / norm, ny / norm, nz / norm

    return np.stack([nx, ny, nz], axis=-1)


def light_vector(az_deg: float, el_deg: float) -> np.ndarray:
    """方位角 + 高度角 → 单位光源向量 [lx, ly, lz]。

    az_deg: 方位角（0=北, 90=东, 180=南, 270=西）
    el_deg: 高度角（0=地平线, 90=正上方）
    """
    az = np.radians(az_deg)
    el = np.radians(el_deg)
    lx = np.cos(el) * np.sin(az)
    ly = np.cos(el) * np.cos(az)
    lz = np.sin(el)
    return np.array([lx, ly, lz], dtype=np.float32)


def compute_shading(normal_map: np.ndarray,
                    az_deg: float,
                    el_deg: float,
                    ambient: float = 0.2) -> np.ndarray:
    """计算 Lambertian 光照强度图。

    Shading = ambient + (1 - ambient) × max(N · L, 0)

    Returns:
        shading: (H, W) float32，范围 [ambient, 1.0]
    """
    L = light_vector(az_deg, el_deg)
    N_dot_L = (normal_map * L).sum(axis=-1)
    shading = ambient + (1.0 - ambient) * np.clip(N_dot_L, 0.0, 1.0)
    return shading.astype(np.float32)


def calibrate_scale(height_gray: np.ndarray) -> float:
    """根据高度图的梯度统计自动校准 scale 参数。

    目标：让地形边缘处（高度变化区域）的法线梯度幅度在合理范围内（0.5~1.5）。
    """
    try:
        import cv2
        dx = cv2.Sobel(height_gray, cv2.CV_32F, 1, 0, ksize=3)
        dy = cv2.Sobel(height_gray, cv2.CV_32F, 0, 1, ksize=3)
    except ImportError:
        return 8.0

    grad_mag = np.sqrt(dx ** 2 + dy ** 2)
    # 只看梯度显著的边缘区域（前 5%）
    edge_pixels = grad_mag[grad_mag > np.percentile(grad_mag, 95)]
    if len(edge_pixels) == 0 or edge_pixels.mean() < 1e-6:
        return 5.0  # 全平地图

    # 目标：让 90 分位梯度乘以 scale 约等于 1.0
    p90 = float(np.percentile(edge_pixels, 90))
    scale = 1.0 / (p90 + 1e-8)
    return float(np.clip(scale, 3.0, 20.0))


def estimate_light_direction(normal_map: np.ndarray,
                              terrain_gray: np.ndarray,
                              ambient: float = 0.2,
                              water_mask: np.ndarray = None,
                              n_az: int = 24,
                              n_el: int = 7) -> tuple:
    """自动估算最优光源方向（粗搜索 + 细化）。

    策略：找到使"albedo 与 shading 的相关性"最小的光源方向。
    光源方向正确时，albedo 应该与光照无关，二者相关性接近 0。

    Args:
        normal_map:   (H, W, 3) 法线贴图
        terrain_gray: (H, W) float32 地形图灰度（gamma 线性化后）
        ambient:      环境光系数
        water_mask:   (H, W) bool，水域格子排除在外
        n_az:         方位角搜索步数
        n_el:         高度角搜索步数

    Returns:
        (best_az, best_el): 最优光源方向（度）
    """
    # 有效像素掩码（排除水域、极暗极亮区域——这些是噪声和投射阴影）
    valid = (terrain_gray > 0.08) & (terrain_gray < 0.93)
    if water_mask is not None:
        valid &= ~water_mask

    # 高梯度区域权重更高（边缘处光影对比更明显，判据更可靠）
    try:
        import cv2
        gray_uint8 = np.clip(terrain_gray * 255, 0, 255).astype(np.uint8)
        laplacian = np.abs(cv2.Laplacian(gray_uint8, cv2.CV_32F))
        weight = laplacian / (laplacian.max() + 1e-8)
    except Exception:
        weight = np.ones_like(terrain_gray)

    weight = weight * valid.astype(np.float32)
    weight_flat = weight.flatten()

    def score_direction(az_deg, el_deg):
        shading = compute_shading(normal_map, az_deg, el_deg, ambient)
        # tentative albedo（不做 gamma，只看相对值）
        albedo_gray = terrain_gray / (shading + 1e-6)

        s_flat = shading.flatten()
        a_flat = np.clip(albedo_gray, 0, 3).flatten()

        # 加权相关系数（越接近 0 越好）
        w = weight_flat
        w_sum = w.sum() + 1e-8
        s_mean = (s_flat * w).sum() / w_sum
        a_mean = (a_flat * w).sum() / w_sum
        cov = ((s_flat - s_mean) * (a_flat - a_mean) * w).sum() / w_sum
        s_std = np.sqrt(((s_flat - s_mean) ** 2 * w).sum() / w_sum)
        a_std = np.sqrt(((a_flat - a_mean) ** 2 * w).sum() / w_sum)
        corr = cov / (s_std * a_std + 1e-8)
        return -abs(corr)  # 最大化 → 最小化绝对相关性

    # 粗搜索
    az_list = np.linspace(0, 360, n_az, endpoint=False)
    el_list = np.linspace(15, 75, n_el)

    best_score = -np.inf
    best_az, best_el = 45.0, 45.0

    print(f"  粗搜索: {n_az} × {n_el} = {n_az * n_el} 个方向 ...")
    for az in az_list:
        for el in el_list:
            s = score_direction(az, el)
            if s > best_score:
                best_score = s
                best_az, best_el = az, el

    print(f"  粗搜索最优: az={best_az:.1f}° el={best_el:.1f}° (score={best_score:.4f})")

    # 细化搜索（在粗搜索最优点周围 ±20° 精细扫描）
    az_fine = np.linspace(best_az - 20, best_az + 20, 9)
    el_fine = np.linspace(max(5, best_el - 15), min(85, best_el + 15), 7)

    for az in az_fine:
        for el in el_fine:
            s = score_direction(az % 360, el)
            if s > best_score:
                best_score = s
                best_az, best_el = az % 360, el

    print(f"  细化最优: az={best_az:.1f}° el={best_el:.1f}° (score={best_score:.4f})")
    return float(best_az), float(best_el)


def detect_cast_shadows(observed_gray: np.ndarray,
                         predicted_shading: np.ndarray,
                         threshold: float = 0.45) -> np.ndarray:
    """检测投射阴影区域（无法通过 Lambertian 模型去除）。

    当观测亮度 << 预测亮度时，说明存在非本身朝向导致的投射阴影。

    Args:
        observed_gray:    (H, W) float32，地形图灰度（gamma 线性化）
        predicted_shading:(H, W) float32，Lambertian 预测光照
        threshold:        比值阈值，observed/predicted < threshold → 投射阴影

    Returns:
        cast_shadow_mask: (H, W) bool
    """
    ratio = observed_gray / (predicted_shading + 1e-6)
    cast_shadow_mask = ratio < threshold
    # 排除本身就很暗的区域（避免误判深色纹理）
    cast_shadow_mask &= (observed_gray < 0.3)
    return cast_shadow_mask


def apply_delighting(terrain_linear: np.ndarray,
                      shading: np.ndarray,
                      cast_shadow_mask: np.ndarray,
                      ambient: float) -> np.ndarray:
    """执行去光照：albedo = terrain / shading，投射阴影区域用估算值填充。

    Args:
        terrain_linear:   (H, W, 3) float32，gamma 线性化的地形图
        shading:          (H, W) float32，光照图
        cast_shadow_mask: (H, W) bool，投射阴影掩码
        ambient:          环境光系数（用于填充阴影区域的估算最大 albedo）

    Returns:
        albedo: (H, W, 3) float32，去光照后的纹理图，范围 [0, 1]
    """
    shading_3ch = shading[:, :, np.newaxis]
    albedo = terrain_linear / (shading_3ch + 1e-6)

    # 投射阴影区域：albedo 无法准确还原。
    # 策略：将这些区域的 albedo 设为"以最弱光照（ambient）能还原的最大值"，
    # 即 albedo = observed / ambient（过高时截断到 1）。
    if cast_shadow_mask.any():
        shadow_region = cast_shadow_mask[:, :, np.newaxis]
        albedo_shadow = terrain_linear / (ambient + 1e-6)
        albedo = np.where(shadow_region, albedo_shadow, albedo)

    return np.clip(albedo, 0.0, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# 调试图输出
# ──────────────────────────────────────────────────────────────────────────────

def save_shading_debug(shading: np.ndarray, path: str) -> None:
    """将光照图保存为灰度图（调试用）。"""
    try:
        import cv2
        img = np.clip(shading * 255, 0, 255).astype(np.uint8)
        cv2.imwrite(path, img)
    except ImportError:
        pass


def save_normal_debug(normal_map: np.ndarray, path: str) -> None:
    """将法线贴图保存为 RGB 图（调试用，法线向量映射到 [0,255]）。"""
    try:
        import cv2
        # 法线 [-1,1] → [0,255]，通道顺序 BGR
        nm_bgr = np.clip((normal_map + 1.0) / 2.0 * 255, 0, 255).astype(np.uint8)
        # 通道重排：[nx,ny,nz] → BGR [nz,ny,nx] for display
        nm_bgr = nm_bgr[:, :, [2, 1, 0]]
        cv2.imwrite(path, nm_bgr)
    except ImportError:
        pass


def save_comparison(original: np.ndarray,
                     albedo: np.ndarray,
                     cast_shadow_mask: np.ndarray,
                     path: str) -> None:
    """保存原图/albedo/阴影掩码三联对比图（调试用）。"""
    try:
        import cv2
        H, W = original.shape[:2]
        # 原图（gamma 编码）
        orig_out = original
        # albedo（转回 gamma 编码）
        albedo_out = encode_gamma(albedo)
        # 阴影掩码（红色高亮）
        mask_vis = orig_out.copy()
        mask_vis[cast_shadow_mask] = [0, 0, 200]

        gap = np.zeros((H, 4, 3), dtype=np.uint8)
        comparison = np.hstack([orig_out, gap, albedo_out, gap, mask_vis])
        cv2.imwrite(path, comparison)
    except ImportError:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="De-lighting — 用高度图消除地形图光影，输出干净纹理贴图"
    )
    parser.add_argument("terrain_map",  help="原始地形图路径（有光影）")
    parser.add_argument("height_map",   help="配套高度图路径（灰度，与地形图空间对齐）")
    parser.add_argument("--output-dir", default=".", help="输出目录")
    parser.add_argument("--scale",      type=float, default=None,
                        help="地形陡峭系数（默认自动校准）")
    parser.add_argument("--ambient",    type=float, default=0.22,
                        help="环境光系数 0~1（默认 0.22）")
    parser.add_argument("--gamma",      type=float, default=2.2,
                        help="图片 gamma 值（默认 2.2，标准 sRGB）")
    parser.add_argument("--light-az",   type=float, default=None,
                        help="手动指定光源方位角（0=北, 90=东），跳过自动估算")
    parser.add_argument("--light-el",   type=float, default=None,
                        help="手动指定光源高度角（0=地平线, 90=正上方），跳过自动估算")
    parser.add_argument("--shadow-threshold", type=float, default=0.45,
                        help="投射阴影检测阈值（默认 0.45，越小越保守）")
    parser.add_argument("--no-debug",   action="store_true",
                        help="不输出调试图（shading/normal/comparison）")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    try:
        import cv2
    except ImportError:
        print("[ERROR] 需要 opencv-python: pip install opencv-python")
        sys.exit(1)

    # ── Step 1: 加载图片 ─────────────────────────────────────────────────
    print("[Step 1] 加载图片 ...")
    terrain_bgr = cv2.imread(args.terrain_map)
    height_img  = cv2.imread(args.height_map, cv2.IMREAD_GRAYSCALE)

    if terrain_bgr is None:
        print(f"[ERROR] 无法读取地形图: {args.terrain_map}")
        sys.exit(1)
    if height_img is None:
        print(f"[ERROR] 无法读取高度图: {args.height_map}")
        sys.exit(1)

    tH, tW = terrain_bgr.shape[:2]
    hH, hW = height_img.shape[:2]
    print(f"  地形图: {tW}×{tH}")
    print(f"  高度图: {hW}×{hH}")

    # 对齐尺寸：将高度图缩放到与地形图一致
    if (hH, hW) != (tH, tW):
        print(f"  ⚠️  尺寸不一致，将高度图缩放至 {tW}×{tH}")
        height_img = cv2.resize(height_img, (tW, tH), interpolation=cv2.INTER_LINEAR)

    # ── Step 2: Gamma 线性化 ─────────────────────────────────────────────
    print(f"\n[Step 2] Gamma 线性化 (gamma={args.gamma}) ...")
    terrain_linear = linearize_gamma(terrain_bgr, args.gamma)  # (H,W,3) float32
    terrain_gray_linear = terrain_linear.mean(axis=2)           # (H,W) float32

    height_norm = height_img.astype(np.float32) / 255.0        # 归一化到 [0,1]

    # ── Step 3: 法线贴图 ─────────────────────────────────────────────────
    print("\n[Step 3] 计算法线贴图 ...")
    if args.scale is not None:
        scale = args.scale
        print(f"  使用手动 scale={scale}")
    else:
        scale = calibrate_scale(height_norm)
        print(f"  自动校准 scale={scale:.2f}")

    normal_map = compute_normal_map(height_norm, scale)
    print(f"  法线贴图: {normal_map.shape}, "
          f"nz 均值={normal_map[:,:,2].mean():.3f}")

    if not args.no_debug:
        normal_path = os.path.join(args.output_dir, "normal_map_debug.png")
        save_normal_debug(normal_map, normal_path)
        print(f"  ✅ 法线贴图: {normal_path}")

    # ── Step 4: 光源方向 ─────────────────────────────────────────────────
    print("\n[Step 4] 确定光源方向 ...")
    if args.light_az is not None and args.light_el is not None:
        best_az, best_el = args.light_az, args.light_el
        print(f"  使用手动光源: az={best_az}° el={best_el}°")
    else:
        best_az, best_el = estimate_light_direction(
            normal_map, terrain_gray_linear, args.ambient
        )
        print(f"  估算光源: az={best_az:.1f}° el={best_el:.1f}°")

    # ── Step 5: 计算光照图 ───────────────────────────────────────────────
    print("\n[Step 5] 计算光照图 (Shading) ...")
    shading = compute_shading(normal_map, best_az, best_el, args.ambient)
    print(f"  Shading 范围: [{shading.min():.3f}, {shading.max():.3f}]")
    print(f"  Shading 均值: {shading.mean():.3f}")

    if not args.no_debug:
        shading_path = os.path.join(args.output_dir, "shading_debug.png")
        save_shading_debug(shading, shading_path)
        print(f"  ✅ 光照图: {shading_path}")

    # ── Step 6: 投射阴影检测 ─────────────────────────────────────────────
    print("\n[Step 6] 检测投射阴影区域 ...")
    cast_shadow_mask = detect_cast_shadows(
        terrain_gray_linear, shading, threshold=args.shadow_threshold
    )
    shadow_pct = cast_shadow_mask.mean() * 100
    print(f"  投射阴影面积: {shadow_pct:.1f}%")
    if shadow_pct > 30:
        print(f"  ⚠️  投射阴影面积较大，可能影响识别精度；"
              f"建议使用无强阴影的地形图")

    shadow_path = os.path.join(args.output_dir, "cast_shadow_mask.npy")
    np.save(shadow_path, cast_shadow_mask)
    print(f"  ✅ 阴影掩码: {shadow_path}")

    # ── Step 7: 去光照 → Albedo ──────────────────────────────────────────
    print("\n[Step 7] 去光照计算 Albedo ...")
    albedo_linear = apply_delighting(
        terrain_linear, shading, cast_shadow_mask, args.ambient
    )
    albedo_uint8 = encode_gamma(albedo_linear, args.gamma)

    albedo_path = os.path.join(args.output_dir, "albedo.png")
    cv2.imwrite(albedo_path, albedo_uint8)
    print(f"  ✅ Albedo: {albedo_path}")

    # Albedo 统计（评估去光照效果）
    albedo_gray = albedo_linear.mean(axis=2)
    orig_gray   = terrain_gray_linear
    valid_mask  = ~cast_shadow_mask

    orig_std   = float(orig_gray[valid_mask].std())
    albedo_std = float(albedo_gray[valid_mask].std())
    reduction  = (1.0 - albedo_std / (orig_std + 1e-8)) * 100
    print(f"  亮度标准差: 原图={orig_std:.3f} → Albedo={albedo_std:.3f} "
          f"(光影减少 {reduction:.1f}%)")

    if not args.no_debug:
        comp_path = os.path.join(args.output_dir, "delighting_comparison.png")
        save_comparison(terrain_bgr, albedo_linear, cast_shadow_mask, comp_path)
        print(f"  ✅ 对比图: {comp_path}  (原图 | Albedo | 阴影掩码)")

    # ── Step 8: 元数据 ───────────────────────────────────────────────────
    meta = {
        "terrain_map":     args.terrain_map,
        "height_map":      args.height_map,
        "terrain_size":    {"width": tW, "height": tH},
        "scale":           round(scale, 3),
        "ambient":         args.ambient,
        "gamma":           args.gamma,
        "light_azimuth":   round(best_az, 1),
        "light_elevation": round(best_el, 1),
        "shadow_threshold": args.shadow_threshold,
        "cast_shadow_pct": round(shadow_pct, 2),
        "brightness_std":  {
            "original": round(orig_std, 4),
            "albedo":   round(albedo_std, 4),
            "reduction_pct": round(reduction, 1),
        },
    }
    meta_path = os.path.join(args.output_dir, "delighting_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\n✅ De-lighting 完成！")
    print(f"   albedo.png          → cv_cluster.py (替代原始地形图输入)")
    print(f"   cast_shadow_mask.npy → cv_cluster_analysis.py (降权不确定区域)")
    print(f"\n   建议：cv_cluster.py 的 --hsv-weights 可从默认 '2.0,1.0,0.3'")
    print(f"         调整为 '2.0,1.0,0.8'（光影已去除，V通道不再需要降权）")


if __name__ == "__main__":
    main()
