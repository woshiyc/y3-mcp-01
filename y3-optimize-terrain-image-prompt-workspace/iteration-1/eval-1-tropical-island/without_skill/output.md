# 热带岛屿地形图 - Midjourney 优化提示词

## 优化后的提示词（英文）

```
aerial top-down satellite view of a tropical island terrain map, perfect circular ring-shaped white sandy beach surrounds the entire island coastline, massive active volcano at the center of the island with dark rocky crater and lava flows, small fishing village with wooden huts and docks on the eastern shore, dense dark green swamp and mangrove wetlands on the western side, lush tropical jungle covering inland slopes, turquoise shallow lagoon inside the beach ring, deep blue ocean surrounding the island, highly detailed topographic texture, birds-eye view orthographic projection, game map style, natural color terrain, 4k resolution --ar 1:1 --style raw --v 6
```

---

## 提示词结构说明

| 模块 | 内容 | 作用 |
|------|------|------|
| 视角 | `aerial top-down satellite view`, `birds-eye view orthographic projection` | 确保生成俯视图，适合转地形 |
| 整体地形 | `tropical island terrain map` | 锚定主题为地形图 |
| 海滩 | `perfect circular ring-shaped white sandy beach surrounds the entire island coastline` | 明确环形沙滩位置与形态 |
| 火山 | `massive active volcano at the center of the island with dark rocky crater and lava flows` | 岛中心火山，有细节纹理 |
| 村庄 | `small fishing village with wooden huts and docks on the eastern shore` | 东岸村庄，色彩与纹理区分 |
| 沼泽 | `dense dark green swamp and mangrove wetlands on the western side` | 西侧沼泽，颜色深暗区分于丛林 |
| 植被 | `lush tropical jungle covering inland slopes` | 内陆坡面丛林填充 |
| 水体 | `turquoise shallow lagoon inside the beach ring, deep blue ocean surrounding the island` | 内外水体颜色区分，便于高度图识别 |
| 画质 | `highly detailed topographic texture`, `natural color terrain`, `4k resolution` | 保证细节丰富，适合后续处理 |
| 参数 | `--ar 1:1 --style raw --v 6` | 正方形比例适合地形，raw 保留真实纹理 |

---

## 备用变体（更强调地形高度感）

```
top-down orthographic map view of a tropical volcanic island, circular sandy beach ring around the coastline, tall central volcano peak with rocky summit and lava streams, eastern coastal village settlement, western mangrove swamp wetlands, tropical rainforest terrain texture, height map color gradient from deep ocean blue to mountain peak white, clean topographic illustration, detailed land use zones, isometric map, game asset style --ar 1:1 --style raw --v 6
```

---

## 优化思路

1. **视角固定为俯视**：地形图生成需要正交俯视角，避免透视变形影响高度图提取。
2. **方位词明确**：eastern / western 替代模糊的"东边/西边"，Midjourney 对英文方位词理解更稳定。
3. **颜色区分各区域**：沼泽用 `dark green`，村庄用建筑纹理，火山用 `dark rocky`，便于后处理时区分地物。
4. **使用 `--style raw`**：减少 Midjourney 的艺术化处理，保留更真实的地貌纹理，适合转地形。
5. **比例 `--ar 1:1`**：正方形输出适合大多数地形编辑器的导入格式。
