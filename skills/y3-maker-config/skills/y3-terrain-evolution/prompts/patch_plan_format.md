# Patch Plan 格式规范

## 核心原则

- LLM 只输出**区域级指令**，不输出格子坐标
- 脚本负责将区域指令翻译为具体格子操作
- 每个 action 必须有明确的 `reason`

## 区域名称

```
northwest | north | northeast
west      | center | east
southwest | south | southeast
all       | edge  | interior
```

## 操作列表

### 地形操作（地质时代可用）

```json
{"op": "raise_height", "region": "northwest", "intensity": 0.3}
// intensity: 0.1=微调, 0.3=明显, 0.5=显著, 0.8=大幅
// 效果: 提升该区域 hill_map 值，增加山地/丘陵比例

{"op": "lower_height", "region": "southwest", "intensity": 0.2}
// 效果: 降低该区域高度，更可能变成平原或水域

{"op": "add_water", "region": "center", "water_type": "plain", "intensity": 0.4}
// water_type: deep | shallow | plain
// 效果: 在该区域低洼处填入水域

{"op": "remove_water", "region": "east", "intensity": 0.3}
// 效果: 抬高该区域水域格子高度，使其变为陆地

{"op": "add_river", "from": "north", "to": "south_lake", "width": 1}
// from/to: 区域名称或 "center_lake" / "south_lake" 等语义名称
// width: 1=窄河, 2=宽河
// 效果: 生成从 from 流向 to 的河流路径

{"op": "add_cracks", "region": "east", "count": 2, "length": 15}
// 效果: 在该区域添加 N 条裂隙

{"op": "remove_cracks", "region": "center", "intensity": 0.5}
// 效果: 删除该区域一半的裂隙格子

{"op": "add_slopes", "region": "all", "intensity": 0.3}
// 效果: 在悬崖边缘重新计算斜坡，intensity 控制斜坡生成阈值

{"op": "smooth_terrain", "region": "south", "passes": 2}
// 效果: 对该区域 hill_map 做高斯平滑，减少突变

{"op": "steepen_terrain", "region": "northwest", "intensity": 0.3}
// 效果: 增大该区域高度梯度，使地形更崎岖
```

### 生态操作（生态时代可用）

```json
{"op": "adjust_biome", "region": "north", "from_biome": "plain", "to_biome": "forest"}
// 效果: 将该区域 plain 格子重新标记为 forest

{"op": "increase_vegetation", "region": "center", "density": 0.4}
// 效果: 提高该区域植被放置密度

{"op": "reduce_vegetation", "region": "east", "density": 0.3}
// 效果: 降低植被密度

{"op": "add_monster_zone", "region": "northeast", "danger_level": 3}
// danger_level: 1-5
// 效果: 在该区域标记怪物区域

{"op": "adjust_danger", "region": "south", "delta": -1}
// delta: 正数=提高危险度, 负数=降低
```

### 文明操作（文明时代可用）

```json
{"op": "add_settlement", "region": "center_plain", "size": "village"}
// size: hamlet | village | town | fortress
// 效果: 在该区域可建造地块选择聚落位置

{"op": "add_road", "from": "northwest_settlement", "to": "center_settlement"}
// 效果: A* 寻路连接两个聚落

{"op": "remove_settlement", "region": "east", "reason": "地形不合适"}
```

## 完整 Patch Plan 示例

```json
{
  "reason": "西北角山地不足，中央平原过于单调，水域连通性差",
  "actions": [
    {
      "op": "raise_height",
      "region": "northwest",
      "intensity": 0.35,
      "reason": "西北角需要形成山脉，提供地形多样性"
    },
    {
      "op": "add_river",
      "from": "northwest",
      "to": "south",
      "width": 1,
      "reason": "添加从西北山脉流向南部的河流，改善水域连通"
    },
    {
      "op": "steepen_terrain",
      "region": "northwest",
      "intensity": 0.3,
      "reason": "配合高度提升，使山脉轮廓更明显"
    },
    {
      "op": "add_cracks",
      "region": "east",
      "count": 1,
      "length": 20,
      "reason": "东部地形过于平整，添加裂隙增加探索元素"
    }
  ]
}
```
