--- map_layout.lua — 每局随机地图布局生成器
---
--- 功能：给定种子，在已有地形数据上随机选择：
---   1. 首都（capital）     — 平地连通面积大、远离水域和边缘
---   2. 玩家起点（start）   — 与首都保持一定距离且陆地可达
---   3. 敌人刷新区（enemy） — 首都和起点确认后，在对侧外围放置
---   4. 资源点（resource）  — 中间环形带均匀分扇区放置
---   5. 装饰物位置按纹理规则重新随机化（树/石）
---
--- 地形数据格式（terrain 参数）：
---   terrain.W           — 格子宽度
---   terrain.H           — 格子高度
---   terrain.height[z][x]— 每格高度（0/2/4/6），水域为 -1
---   terrain.water[z][x] — bool，true=水域
---
--- 用法：
---   local MapRng    = require('map_rng')
---   local MapLayout = require('map_layout')
---
---   local rng    = MapRng.new(seed)
---   local layout = MapLayout.generate(terrain, rng, options)
---   -- layout.capital     = {x, z, h}
---   -- layout.start_point = {x, z, h}
---   -- layout.enemy_zones = [{x,z,h}, ...]
---   -- layout.resources   = [{x,z,h}, ...]
---   -- layout.lairs       = [{x,z,h}, ...]
---   -- layout.ruins       = [{x,z,h}, ...]

---@class MapLayout
local MapLayout = {}

-- ─────────────────────────────────────────────────────────────────────────────
-- 内部工具函数
-- ─────────────────────────────────────────────────────────────────────────────

local function dist2(ax, az, bx, bz)
    return (ax - bx)^2 + (az - bz)^2
end

local function dist(ax, az, bx, bz)
    return math.sqrt(dist2(ax, az, bx, bz))
end

---BFS 计算从 (sx,sz) 出发的陆地连通面积
---@return integer connected_area, table reachable_cells
local function bfs_land_area(terrain, sx, sz, max_area)
    local W, H = terrain.W, terrain.H
    local water = terrain.water
    local visited = {}
    local queue = {{sx, sz}}
    local area = 0
    local cells = {}
    visited[sz * W + sx] = true

    local qi = 1
    while qi <= #queue do
        local cx, cz = queue[qi][1], queue[qi][2]
        qi = qi + 1
        area = area + 1
        cells[area] = {x = cx, z = cz}
        if max_area and area >= max_area then break end

        for _, d in ipairs({{-1,0},{1,0},{0,-1},{0,1}}) do
            local nx, nz = cx + d[1], cz + d[2]
            if nx >= 0 and nx < W and nz >= 0 and nz < H then
                local key = nz * W + nx
                if not visited[key] and not water[nz][nx] then
                    visited[key] = true
                    queue[#queue + 1] = {nx, nz}
                end
            end
        end
    end
    return area, cells
end

---BFS 距离场：从起点出发，只走陆地，返回每个陆地格的最短距离
---@return table dist_map[z][x] = distance（水域和不可达格为 math.huge）
local function bfs_distance(terrain, sx, sz)
    local W, H = terrain.W, terrain.H
    local water = terrain.water
    local d = {}
    for z = 0, H-1 do
        d[z] = {}
        for x = 0, W-1 do d[z][x] = math.huge end
    end
    d[sz][sx] = 0
    local queue = {{sx, sz, 0}}
    local qi = 1
    while qi <= #queue do
        local cx, cz, cd = queue[qi][1], queue[qi][2], queue[qi][3]
        qi = qi + 1
        for _, dv in ipairs({{-1,0},{1,0},{0,-1},{0,1}}) do
            local nx, nz = cx + dv[1], cz + dv[2]
            if nx >= 0 and nx < W and nz >= 0 and nz < H then
                if not water[nz][nx] and d[nz][nx] == math.huge then
                    d[nz][nx] = cd + 1
                    queue[#queue + 1] = {nx, nz, cd + 1}
                end
            end
        end
    end
    return d
end

---格子 (x,z) 与最近水域的距离（仅4邻格扩散，返回步数）
local function dist_to_water(terrain, x, z, max_check)
    local W, H = terrain.W, terrain.H
    local water = terrain.water
    local visited = {}
    local queue = {{x, z, 0}}
    local qi = 1
    visited[z * W + x] = true
    while qi <= #queue do
        local cx, cz, cd = queue[qi][1], queue[qi][2], queue[qi][3]
        qi = qi + 1
        if water[cz][cx] then return cd end
        if cd >= (max_check or 10) then return cd end
        for _, d in ipairs({{-1,0},{1,0},{0,-1},{0,1}}) do
            local nx, nz = cx + d[1], cz + d[2]
            if nx >= 0 and nx < W and nz >= 0 and nz < H then
                local key = nz * W + nx
                if not visited[key] then
                    visited[key] = true
                    queue[#queue + 1] = {nx, nz, cd + 1}
                end
            end
        end
    end
    return max_check or 10
end

---判断 (x,z) 与地图边缘的距离
local function dist_to_edge(terrain, x, z)
    return math.min(x, z, terrain.W - 1 - x, terrain.H - 1 - z)
end

---计算所有格子与目标点的角度（弧度）
local function angle_from(ax, az, bx, bz)
    return math.atan(bz - az, bx - ax)
end

-- ─────────────────────────────────────────────────────────────────────────────
-- 候选池构建
-- ─────────────────────────────────────────────────────────────────────────────

local DEFAULT_OPT = {
    -- 首都条件
    capital_min_edge   = 8,    -- 离地图边缘最小格数
    capital_min_water  = 4,    -- 离最近水域最小格数
    capital_min_area   = 40,   -- 首都所在平地连通面积下限
    capital_h          = 0,    -- 首都必须在高度0的格子

    -- 起点条件（与首都相对关系）
    start_min_dist     = 20,   -- 与首都最小距离（格）
    start_max_dist     = 70,   -- 与首都最大距离（格）
    start_min_edge     = 6,
    start_min_water    = 3,
    start_h            = 0,    -- 起点必须在高度0的格子

    -- 敌人刷新区条件
    enemy_min_dist_from_capital = 50,   -- 与首都最小格数距离
    enemy_angle_gap    = 90,            -- 敌人区域在起点反向 ±angle_gap 度内
    enemy_count        = 8,
    enemy_h_max        = 2,             -- 刷新点最大高度（≤ 此值）

    -- 资源点
    resource_min_dist  = 15,   -- 与首都最小距离
    resource_max_dist  = 55,   -- 与首都最大距离
    resource_sectors   = 8,    -- 扇区数（保证分布均匀）
    resource_per_sector= 1,    -- 每扇区取几个资源点
    resource_h_max     = 2,

    -- 精英/巢穴
    lair_min_dist      = 40,
    lair_max_dist      = 80,
    lair_count         = 6,

    -- 遗迹/地牢
    ruin_count         = 8,
    dungeon_count      = 3,

    -- 节点最小间距（同类节点之间）
    min_spacing        = 8,
}

---从候选格列表中移除已放置点附近的格子
local function filter_spacing(candidates, placed, min_d)
    if #placed == 0 then return candidates end
    local result = {}
    for _, c in ipairs(candidates) do
        local ok = true
        for _, p in ipairs(placed) do
            if dist2(c.x, c.z, p.x, p.z) < min_d * min_d then
                ok = false; break
            end
        end
        if ok then result[#result+1] = c end
    end
    return result
end

-- ─────────────────────────────────────────────────────────────────────────────
-- 主生成函数
-- ─────────────────────────────────────────────────────────────────────────────

---生成一局的完整地图布局
---@param terrain table 地形数据（含 W,H,height,water）
---@param rng MapRng 已初始化的随机生成器
---@param options table|nil 可选，覆盖默认参数
---@return table layout 含 capital, start_point, enemy_zones, resources, lairs, ruins
function MapLayout.generate(terrain, rng, options)
    local opt = {}
    for k, v in pairs(DEFAULT_OPT) do opt[k] = v end
    if options then
        for k, v in pairs(options) do opt[k] = v end
    end

    local W, H = terrain.W, terrain.H
    local height = terrain.height
    local water  = terrain.water

    -- ── 步骤1：构建首都候选池 ────────────────────────────────────────────
    local capital_candidates = {}
    for z = opt.capital_min_edge, H - 1 - opt.capital_min_edge do
        for x = opt.capital_min_edge, W - 1 - opt.capital_min_edge do
            if not water[z][x] and height[z][x] == opt.capital_h then
                local dw = dist_to_water(terrain, x, z, opt.capital_min_water + 1)
                if dw >= opt.capital_min_water then
                    capital_candidates[#capital_candidates+1] = {x=x, z=z, h=0}
                end
            end
        end
    end

    -- 按平地面积评分，取 top 20% 的点
    local scored = {}
    for _, c in ipairs(capital_candidates) do
        local area = bfs_land_area(terrain, c.x, c.z, opt.capital_min_area + 50)
        scored[#scored+1] = {x=c.x, z=c.z, h=0, score=area}
    end
    table.sort(scored, function(a,b) return a.score > b.score end)
    local top_n = math.max(1, math.floor(#scored * 0.2))
    local top_capitals = {}
    for i = 1, top_n do top_capitals[i] = scored[i] end

    -- 随机选首都
    local capital = rng:choice(top_capitals) or {x=W//2, z=H//2, h=0}

    -- ── 步骤2：BFS 距离场（从首都出发，仅走陆地）────────────────────────
    local dist_map = bfs_distance(terrain, capital.x, capital.z)
    local max_dist = 0
    for z = 0, H-1 do
        for x = 0, W-1 do
            if dist_map[z][x] < math.huge and dist_map[z][x] > max_dist then
                max_dist = dist_map[z][x]
            end
        end
    end

    -- ── 步骤3：构建起点候选池 ─────────────────────────────────────────────
    local start_candidates = {}
    for z = opt.start_min_edge, H - 1 - opt.start_min_edge do
        for x = opt.start_min_edge, W - 1 - opt.start_min_edge do
            if not water[z][x] and height[z][x] == opt.start_h then
                local d = dist_map[z][x]
                if d >= opt.start_min_dist and d <= opt.start_max_dist then
                    local dw = dist_to_water(terrain, x, z, opt.start_min_water + 1)
                    if dw >= opt.start_min_water then
                        start_candidates[#start_candidates+1] = {x=x, z=z, h=0}
                    end
                end
            end
        end
    end
    rng:shuffle(start_candidates)
    local start_point = start_candidates[1] or capital

    -- ── 步骤4：敌人刷新区（在起点对侧外围）──────────────────────────────
    -- 计算"禁止方向"：首都→起点方向，敌人放在 ±(180-angle_gap) 范围
    local start_angle = angle_from(capital.x, capital.z, start_point.x, start_point.z)
    local enemy_angle_center = start_angle + math.pi  -- 正对侧
    local half_gap = math.rad(opt.enemy_angle_gap)

    local enemy_candidates = {}
    for z = 0, H-1 do
        for x = 0, W-1 do
            if not water[z][x] and height[z][x] <= opt.enemy_h_max then
                local d = dist_map[z][x]
                if d >= opt.enemy_min_dist_from_capital and d < math.huge then
                    local ang = angle_from(capital.x, capital.z, x, z)
                    -- 角度差（限制在 [-pi, pi]）
                    local diff = ang - enemy_angle_center
                    while diff >  math.pi do diff = diff - 2*math.pi end
                    while diff < -math.pi do diff = diff + 2*math.pi end
                    if math.abs(diff) <= half_gap then
                        enemy_candidates[#enemy_candidates+1] = {x=x, z=z, h=height[z][x]}
                    end
                end
            end
        end
    end
    rng:shuffle(enemy_candidates)

    local placed_all = {capital, start_point}
    local enemy_zones = {}
    for _, c in ipairs(enemy_candidates) do
        if #enemy_zones >= opt.enemy_count then break end
        local ok = true
        for _, p in ipairs(placed_all) do
            if dist2(c.x, c.z, p.x, p.z) < opt.min_spacing^2 then ok=false; break end
        end
        if ok then
            enemy_zones[#enemy_zones+1] = c
            placed_all[#placed_all+1] = c
        end
    end

    -- ── 步骤5：资源点（按扇区均匀分布）──────────────────────────────────
    local resources = {}
    local sector_size = 2 * math.pi / opt.resource_sectors

    for s = 0, opt.resource_sectors - 1 do
        local angle_min = -math.pi + s * sector_size
        local angle_max = angle_min + sector_size
        local sector_candidates = {}

        for z = 0, H-1 do
            for x = 0, W-1 do
                if not water[z][x] and height[z][x] <= opt.resource_h_max then
                    local d = dist_map[z][x]
                    if d >= opt.resource_min_dist and d <= opt.resource_max_dist then
                        local ang = angle_from(capital.x, capital.z, x, z)
                        if ang >= angle_min and ang < angle_max then
                            sector_candidates[#sector_candidates+1] = {x=x,z=z,h=height[z][x]}
                        end
                    end
                end
            end
        end

        rng:shuffle(sector_candidates)
        local picked = 0
        for _, c in ipairs(sector_candidates) do
            if picked >= opt.resource_per_sector then break end
            local ok = true
            for _, p in ipairs(placed_all) do
                if dist2(c.x, c.z, p.x, p.z) < opt.min_spacing^2 then ok=false; break end
            end
            if ok then
                resources[#resources+1] = c
                placed_all[#placed_all+1] = c
                picked = picked + 1
            end
        end
    end

    -- ── 步骤6：巢穴（外圈）──────────────────────────────────────────────
    local lair_candidates = {}
    for z = 0, H-1 do
        for x = 0, W-1 do
            if not water[z][x] then
                local d = dist_map[z][x]
                if d >= opt.lair_min_dist and d <= opt.lair_max_dist and d < math.huge then
                    lair_candidates[#lair_candidates+1] = {x=x,z=z,h=height[z][x]}
                end
            end
        end
    end
    rng:shuffle(lair_candidates)
    local lairs = {}
    for _, c in ipairs(lair_candidates) do
        if #lairs >= opt.lair_count then break end
        local ok = true
        for _, p in ipairs(placed_all) do
            if dist2(c.x,c.z,p.x,p.z) < opt.min_spacing^2 then ok=false; break end
        end
        if ok then lairs[#lairs+1]=c; placed_all[#placed_all+1]=c end
    end

    -- ── 步骤7：遗迹（全图散布）──────────────────────────────────────────
    local ruin_candidates = {}
    for z = 0, H-1 do
        for x = 0, W-1 do
            if not water[z][x] and dist_map[z][x] >= 10 and dist_map[z][x] < math.huge then
                ruin_candidates[#ruin_candidates+1] = {x=x,z=z,h=height[z][x]}
            end
        end
    end
    rng:shuffle(ruin_candidates)
    local ruins = {}
    for _, c in ipairs(ruin_candidates) do
        if #ruins >= opt.ruin_count then break end
        local ok = true
        for _, p in ipairs(placed_all) do
            if dist2(c.x,c.z,p.x,p.z) < opt.min_spacing^2 then ok=false; break end
        end
        if ok then ruins[#ruins+1]=c; placed_all[#placed_all+1]=c end
    end

    return {
        seed        = rng._state,   -- 记录当前 RNG 状态，便于调试
        capital     = capital,
        start_point = start_point,
        enemy_zones = enemy_zones,
        resources   = resources,
        lairs       = lairs,
        ruins       = ruins,
        -- 便于统计
        summary = {
            capital    = 1,
            start      = 1,
            enemy      = #enemy_zones,
            resource   = #resources,
            lair       = #lairs,
            ruin       = #ruins,
        }
    }
end

-- ─────────────────────────────────────────────────────────────────────────────
-- 工具：从 Y3 GameAPI 构建 terrain 数据结构
-- ─────────────────────────────────────────────────────────────────────────────

---从 Y3 地形 API 读取地形数据，构建 terrain 表
---（仅在游戏运行时 GameAPI 可用时调用）
---@param W integer 地图宽度（格）
---@param H integer 地图高度（格）
---@return table terrain
function MapLayout.build_terrain_from_gameapi(W, H)
    local terrain = {W=W, H=H, height={}, water={}}
    for z = 0, H-1 do
        terrain.height[z] = {}
        terrain.water[z]  = {}
        for x = 0, W-1 do
            local block = GameAPI.terrain_get_block(x, z)
            local has_water = block and block.has_water or false
            local h = block and block.terrain_height or 0
            terrain.water[z][x]  = has_water
            terrain.height[z][x] = has_water and -1 or h
        end
    end
    return terrain
end

---从已有 CSV 数据（Python 生成的 terrain_grid.csv 解析结果）构建 terrain 表
---cells 格式：cells[z][x] = {type="ground"|"deep_water"|..., h=0|2|4|6}
---@param cells table
---@param W integer
---@param H integer
---@return table terrain
function MapLayout.build_terrain_from_csv(cells, W, H)
    local terrain = {W=W, H=H, height={}, water={}}
    for z = 0, H-1 do
        terrain.height[z] = {}
        terrain.water[z]  = {}
        local row = cells[z] or {}
        for x = 0, W-1 do
            local cell = row[x] or {type="ground", h=0}
            local is_water = (cell.type == "deep_water" or cell.type == "shallow_water" or cell.type == "plain_water")
            terrain.water[z][x]  = is_water
            terrain.height[z][x] = is_water and -1 or (cell.h or 0)
        end
    end
    return terrain
end

return MapLayout
