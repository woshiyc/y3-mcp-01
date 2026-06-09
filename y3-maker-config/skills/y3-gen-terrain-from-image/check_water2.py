import sys
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image
import cv2, pathlib

os_dir = pathlib.Path('E:/pycode/y3-map/y3-maker-config/skills/y3-gen-terrain-from-image')

gray = np.array(Image.open(str(os_dir/'output/08/gray_context.png')).convert('L'))
deco = np.array(Image.open(str(os_dir/'output/08/decoration_design_01.png')).convert('RGB'))
wm   = np.load(str(os_dir/'output/08/water_mask_grid.npy')).astype(bool)

H, W = wm.shape
scale = gray.shape[0] // H

deco_hsv = cv2.cvtColor(deco, cv2.COLOR_RGB2HSV)

water_green = 0
land_green  = 0
violations  = []

for r in range(H):
    for c in range(W):
        block = deco_hsv[r*scale:(r+1)*scale, c*scale:(c+1)*scale]
        green_px = int(np.sum((block[:,:,0] >= 35) & (block[:,:,0] <= 85) & (block[:,:,1] > 40)))
        if green_px > 20:
            if wm[r, c]:
                water_green += 1
                violations.append((c, r, green_px))
            else:
                land_green += 1

out = []
out.append(f'Water cells total: {int(wm.sum())}')
out.append(f'Water cells with vegetation: {water_green} ({water_green/wm.sum()*100:.1f}%)')
out.append(f'Land cells with vegetation: {land_green}')
out.append('')
out.append('Top 20 water violation cells (grid x,z):')
for gx, gz, px in sorted(violations, key=lambda x: -x[2])[:20]:
    out.append(f'  grid({gx},{gz})  green_px={px}/64')

# Generate overlay image
overlay = deco.copy()
for gx, gz, _ in violations:
    x0, y0 = gx*scale, gz*scale
    overlay[y0:y0+scale, x0:x0+scale] = [255, 0, 0]
Image.fromarray(overlay).save(str(os_dir/'output/08/water_violation_overlay.png'))
out.append('')
out.append('Saved water_violation_overlay.png')

result = '\n'.join(out)
pathlib.Path(str(os_dir/'output/08/water_check_result.txt')).write_text(result, encoding='utf-8')
print(result)
