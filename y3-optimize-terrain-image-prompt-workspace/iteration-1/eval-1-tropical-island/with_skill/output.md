# Y3 图片转地形提示词优化结果

**原始用户描述：**
> 生成一个热带岛屿，有环形沙滩，岛中心是火山，东边有小村庄，西边有沼泽。

**目标文生图模型：** Midjourney

---

## 优化后的正向提示词

一张用于游戏编辑器图片转地形的俯视正交地形规划图，主题为：热带岛屿。地图内容必须填满整个画布，地图边界与图片边界严格对齐，无倾斜、无透视、无留白、无装饰边框。

地图布局：岛屿整体呈椭圆形，四周被深蓝色深海包围，近岛岸线为青蓝色浅海；岛屿外圈一整圈为浅黄色沙滩（环形沙滩），沙滩内侧为浅绿色热带平原与深绿色热带丛林；岛屿中心为高耸的火山区域，使用黑灰色表示火山基岩，中心火山口用深红橙色标示；岛屿东侧边缘靠近沙滩内圈分布一小块浅棕色区域，代表简洁的小型村庄聚落，以简单色块区分，不使用复杂建筑图标；岛屿西侧分布暗绿偏蓝的不规则色块，代表沼泽地带，边界模糊且低洼。

使用清晰、低噪声、机器可读的色块表达地形：深蓝色表示深海，青蓝色表示浅海，浅黄色表示环形沙滩，浅绿色表示热带平原，深绿色表示热带丛林，橄榄绿或浅棕色表示丘陵坡地，棕色和黑灰色表示火山山地，深红橙色标示火山口，暗绿偏蓝表示西部沼泽，浅棕色表示东部村庄区域。各地貌区域边界清晰，颜色稳定，避免复杂纹理。

高度通过明确的离散高度色带表达：深海最低，浅海次低，沙滩略高，平原和丛林适中，丘陵坡地逐步升高，火山主体最高；火山区域从外圈棕色丘陵向中心逐渐过渡为黑灰色高地，中心火山口为最高点，形成清晰可识别的高度层级。西部沼泽保持低洼地势，东部村庄区域为平坦低地。

道路、村庄、森林、火山等元素以简洁色块或线条表达，不使用复杂图标。整体风格为简洁战略地图、平面地形规划图、低纹理噪声、清晰区域分割，适合后续计算机视觉进行水域识别、岛屿轮廓分割、纹理分配、高度推断和装饰物识别。

---

## 负向提示词

不要透视视角，不要斜视角，不要3D场景，不要电影感光照，不要强烈阴影，不要写实摄影，不要景深，不要云雾，不要复杂纹理，不要过度细节，不要随机噪点，不要模糊边界，不要文字，不要数字，不要地名标签，不要图例，不要罗盘，不要UI面板，不要水印，不要装饰边框，不要人物，不要怪物，不要车辆，不要大量小图标，不要复杂建筑插画，不要让丛林由大量独立树冠图标组成，不要让火山变成写实风景插画，不要让沙滩出现椰子树等复杂装饰物，不要让村庄出现复杂建筑细节，不要强烈的火山喷发特效或岩浆流，不要画面倾斜或留有白边。

---

## 设计保真说明

- 保留了：热带岛屿主题、环形沙滩（岛屿外圈一整圈浅黄色沙滩）、岛中心火山（黑灰色+深红橙色火山口）、东侧小村庄（东部浅棕色简洁区域）、西侧沼泽（暗绿偏蓝低洼区域）、岛屿与海洋的整体空间关系。
- 没有改变：各区域的方位关系（东村庄、西沼泽、中心火山、外圈沙滩）、地貌类型（未替换任何用户指定的地形元素）、岛屿整体形态。
- 只是增强了：色彩语义（每种地貌使用固定颜色，方便CV聚类）、高度表达（从深海到火山顶的离散色带层级）、机器可读约束（低噪声、无文字、无复杂图标）、俯视正交要求（确保图片转地形时坐标映射准确）。

---

## 为什么更适合图片转地形

- 俯视正交视角：去除透视和斜视角，确保图片坐标与编辑器地图网格 1:1 对应，避免地形变形。
- 色彩语义固定：每种地貌（深海/浅海/沙滩/平原/丛林/沼泽/火山/村庄）使用固定颜色，便于 `y3-gen-terrain-from-image` 通过颜色聚类精准识别各区域。
- 边界清晰：各地貌区域边界明确，水陆分割、岛屿轮廓提取、内部区域分割都更准确。
- 高度层级明确：从深海到火山顶使用离散色带，高度推断算法可以直接从颜色映射高度值，无需额外推断。
- 低噪声低装饰：去除写实纹理、复杂图标、阴影、云雾等视觉元素，减少CV识别中的噪点干扰。
- 填满画布：地图边界与图片边界对齐，确保整张图片都有效参与地形转换，无无效留白区域。
- 沼泽与火山的颜色独特性：沼泽（暗绿偏蓝）和火山（黑灰+红橙）颜色与其他地貌差异显著，易于单独识别和提取。

---

## 可选参数建议

- 画幅：1:1（方形画布，与目标地图比例保持一致；如地图为矩形可调整为 4:3 或 16:9）
- 风格：flat map / orthographic terrain planning map / game map sketch（避免 photorealistic、painterly、cinematic）
- 细节：中低（避免过度细节导致噪点增加）
- 随机性：中低（--stylize 50 以下，避免风格化过度破坏色彩语义）
- Midjourney 专项推荐：`--style raw --ar 1:1 --stylize 30 --chaos 0`（raw 模式更忠实于提示词，chaos 0 保持构图稳定性，stylize 低值避免艺术化过度）

---

## 风险提醒

- Midjourney 对"俯视正交地形规划图"的理解可能仍偏向艺术化风景，建议多生成几张，选择色块最简洁、边界最清晰的一张交给 `y3-gen-terrain-from-image`。
- 火山区域颜色（黑灰+红橙）与沼泽（暗绿偏蓝）差异较大，但如果 Midjourney 将火山口渲染为强烈的岩浆喷发特效，可能引入大量红橙噪点，干扰颜色聚类；如出现此情况，可在负向提示词中追加"no lava eruption, no fire effects"。
- 沙滩与浅黄色平原颜色可能相近，导致 CV 识别时沙滩与平原边界模糊；可在正向提示词中强调"沙滩颜色明显浅于内陆平原，形成清晰的环形色带"。
- 东部村庄区域面积较小，Midjourney 可能将其渲染为复杂建筑图标；如出现此情况，选择只有简单浅棕色色块的生成结果。
- 如果最终生成图片不够理想，可以在 `y3-gen-terrain-from-image` 流程中手动调整色彩映射参数，弥补图片质量不足。

---

---

## English Positive Prompt

A top-down orthographic terrain planning map for game-editor image-to-terrain generation, theme: tropical island. The map content must fill the entire canvas, with the map boundary strictly aligned to the image boundary. No tilt, no perspective, no blank margins, no decorative frame.

Map layout: The island is oval-shaped, surrounded by dark blue deep ocean, with cyan-blue shallow water near the shoreline. A complete ring of pale yellow sandy beach wraps around the outer edge of the island (circular beach). Inside the beach ring, there are light green tropical plains and dark green tropical jungle. The center of the island features a volcanic mountain: dark gray-black represents the volcanic rock base, and a deep red-orange patch marks the volcano crater at the highest point. The eastern edge of the island, within the inner beach zone, contains a small flat area in light brown representing a simple village settlement, expressed as a clean color region without complex building icons. The western side of the island has irregular dark greenish-blue patches at low elevation, representing swampland.

Use clean, low-noise, machine-readable color regions to represent terrain types: dark blue for deep ocean, cyan blue for shallow water, pale yellow for the circular sandy beach, light green for tropical plains, dark green for tropical jungle, olive green or light brown for hillside slopes, brown and dark gray-black for the volcanic mountain body, deep red-orange for the volcano crater, dark greenish-blue for the western swamp, and light brown for the eastern village area. All terrain region boundaries must be clear and colors stable, with minimal texture noise.

Represent elevation with clear discrete elevation color bands: deep ocean is the lowest, shallow water is slightly higher, sandy beach is low, plains and jungle are moderate, hillside slopes gradually rise, and the volcanic mountain is the highest feature. The volcanic area transitions from outer brown hills toward the center into dark gray-black high ground, with the volcano crater as the peak — forming a clearly identifiable elevation hierarchy. The western swamp stays at low elevation. The eastern village area is flat lowland.

Roads, villages, forests, and volcanoes should be represented as simple color regions or lines, not complex icons. Overall style: clean strategy map, flat terrain planning map, low texture noise, clear region segmentation, suitable for later computer vision processing such as water detection, island contour segmentation, texture assignment, elevation inference, and decoration recognition.

---

## English Negative Prompt

No perspective view, no tilted view, no 3D scene, no cinematic lighting, no strong shadows, no photorealistic rendering, no depth of field, no fog, no clouds, no complex textures, no excessive details, no random noise, no blurry boundaries, no text, no numbers, no place labels, no legend, no compass, no UI panels, no watermark, no decorative border, no characters, no monsters, no vehicles, no many small icons, no complex building illustrations, do not represent jungle as many individual tree crown icons, do not turn the volcano into a realistic landscape illustration, no lava eruption effects, no fire effects, no coconut trees or beach decorations, no complex village building details, no image tilt, no blank margins.
