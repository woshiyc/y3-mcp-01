# 优化后的地图生成提示词

## 正向提示词（Positive Prompt）

```
Top-down 2D strategy game map, four-player battleground, symmetric layout, center features a tall snow-capped mountain peak with glacial white terrain and rocky cliffs, surrounded by dense pine forests with dark green canopy, two winding rivers flowing from the mountain outward toward map edges, each river crossed by a stone arch bridge, four player spawn bases located at each corner of the map with clear flat ground and starting structures, mountain flanked by coniferous forest zones with varied tree density, river banks with sandy shores and vegetation, fog-of-war friendly design, warm autumnal forest tones contrasting with cold icy mountain center, detailed terrain texture, hand-painted fantasy style, bird's eye view, isometric-inspired 2D art, high detail, game-ready asset
```

## 负向提示词（Negative Prompt）

```
asymmetric layout, random terrain, missing bridges, no spawn points, urban environment, desert biome, tropical jungle, flat terrain, ocean, sea, swamp, lava, no snow, no mountain, photorealistic photo, 3D render, low quality, blurry, watermark, text overlay, single-player map, disconnected rivers, impassable terrain blocking all paths, missing forest, missing river
```

---

## 提示词解析说明

| 要素 | 提示词关键词 |
|------|------------|
| 地图类型 | `Top-down 2D strategy game map`, `four-player battleground`, `symmetric layout` |
| 雪山（中央） | `center features a tall snow-capped mountain peak`, `glacial white terrain`, `rocky cliffs` |
| 森林 | `dense pine forests`, `coniferous forest zones`, `varied tree density`, `forest biome` |
| 两条河流 | `two winding rivers flowing from the mountain outward`, `river banks with sandy shores` |
| 桥梁 | `each river crossed by a stone arch bridge` |
| 四角出生点 | `four player spawn bases located at each corner`, `clear flat ground`, `starting structures` |
| 风格 | `hand-painted fantasy style`, `bird's eye view`, `high detail`, `game-ready asset` |

---

## 备注

- 提示词以 **俯视视角（top-down / bird's eye view）** 为主，适合图片转地形工具识别地图区域划分。
- **对称布局（symmetric layout）** 确保四名玩家的初始公平性。
- 雪山位于 **中央（center）**，形成天然障碍与战略高地。
- 两条河流由山脉向外延伸，桥梁作为关键通道，提供战术卡点。
- 负向提示词排除了常见干扰元素（热带、沙漠、现代城市等），防止地形生成偏移主题。
```
