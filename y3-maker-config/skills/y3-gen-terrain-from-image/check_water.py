import numpy as np
from PIL import Image
import cv2

gray = np.array(Image.open('output/08/gray_context.png').convert('L'))
deco = np.array(Image.open('output/08/decoration_design_01.png').convert('RGB'))
wm   = np.load('output/08/water_mask_grid.npy').astype(bool)

H, W = wm.shape
scale = gray.shape[0] // H  # 8

deco_hsv = cv2.cvtColor(deco, cv2.COLOR_RGB2HSV)

water_green = 0
land_green  = 0
water_green_cells = []

for r in range(H):
    for c in range(W):
        block = deco_hsv[r*scale:(r+1)*scale, c*scale:(c+1)*scale]
        h_vals = block[:,:,0].flatten()
        s_vals = block[:,:,1].flatten()
        green_px = int(np.sum((h_vals >= 35) & (h_vals <= 85) & (s_vals > 40)))
        if green_px > 20:
            if wm[r, c]:
                water_green += 1
                water_green_cells.append((c, r, green_px))
            else:
                land_green += 1

total_water = int(wm.sum())
print(f'水域格总数: {total_water}')
print(f'水域中有植被的格子: {water_green} ({water_green/total_water*100:.1f}%)')
print(f'陆地中有植被的格子: {land_green}')
print()
print('水域植被格位置（前15个）:')
for gx, gz, px in water_green_cells[:15]:
    print(f'  格({gx},{gz}) 绿色像素={px}/64')

# 生成对比热力图
overlay = deco.copy()
for gx, gz, _ in water_green_cells:
    x0, y0 = gx*scale, gz*scale
    overlay[y0:y0+scale, x0:x0+scale] = [255, 0, 0]  # 红色标记水域植被

Image.fromarray(overlay).save('output/08/water_violation_overlay.png')
print('\n已生成 water_violation_overlay.png（红色=水域中的植被）')
