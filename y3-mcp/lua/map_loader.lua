--- map_loader.lua — 加载预生成地形数据并写入 Y3
---
--- 负责读取 Python 流程产出的静态 JSON/CSV 文件，结合 map_layout 生成的
--- 每局随机布局，调用 Y3 GameAPI 写入实体和节点。
---
--- 依赖：
---   require('map_rng')     — 随机数生成器
---   require('map_layout')  — 布局算法
---
--- 典型用法（游戏初始化时）：
---   local loader = require('map_loader')
---
---   -- 1. 加载预生成静态数据
---   local plan       = loader.load_json('path/to/postprocess_plan.json')
---   local decorations= loader.load_json('path/to/decoration_entities.json')
---   local terrain_csv= loader.load_terrain_csv('path/to/terrain_grid.csv')
---
---   -- 2. 用种子生成本局随机布局（覆盖静态方案中的首都/起点/敌人位置）
---   local seed   = loader.get_or_create_seed()    -- 从游戏房间参数或随机生成
---   local layout = loader.generate_layout(terrain_csv, plan.map_size, seed)
---
---   -- 3. 写入 Y3 世界
---   loader.apply_decorations(decorations, {seed=seed})  -- 装饰物（树/石，带随机性）
---   loader.apply_nodes(layout)                          -- 节点（首都/资源/敌人等）
---   loader.apply_roads(plan.road_grid)                  -- 道路纹理覆盖（可选）

---@class MapLoader
local MapLoader = {}

local MapRng    = require('map_rng')
local MapLayout = require('map_layout')

-- ─────────────────────────────────────────────────────────────────────────────
-- JSON/CSV 文件读取
-- ─────────────────────────────────────────────────────────────────────────────

---读取 JSON 文件并解析为 Lua 表
--- 注意：Y3 Lua 可能需要通过 GameAPI.read_file() 代替 io.open
---  如果 io.open 不可用，请改为 GameAPI.read_game_config(path)
---@param path string 相对于地图目录的路径
---@return table|nil
function MapLoader.load_json(path)
    -- 尝试标准 Lua IO
    local f = io.open(path, 'r')
    if not f then
        -- Y3 备选方案：通过游戏 API 读取
        -- local content = GameAPI.read_file(path)
        -- if content then return json.decode(content) end
        error('MapLoader.load_json: 无法打开文件 ' .. path)
        return nil
    end
    local content = f:read('*all')
    f:close()

    -- 简单 JSON 解析（Y3 环境中推荐使用已有的 json 库）
    -- 若 Y3 内置 json 库：return json.decode(content)
    local ok, result = pcall(function()
        -- 使用 Y3 自带 json 解析（路径视具体版本而定）
        local json = require('json')  -- 或 require('dkjson') 等
        return json.decode(content)
    end)
    if ok then return result end

    -- Fallback：提示用户手动注册 JSON 库
    error('MapLoader: 需要 json 库，请 require("json") 或使用 Y3 内置解析器')
    return nil
end

---读取 terrain_grid.csv，返回 cells[z][x] = {type, h, cid}
---@param path string
---@return table cells, integer W, integer H
function MapLoader.load_terrain_csv(path)
    local f = io.open(path, 'r')
    if not f then error('MapLoader.load_terrain_csv: 无法打开 ' .. path) end

    local cells = {}
    local H = 0
    local W = 0

    for line in f:lines() do
        local row = {}
        local x = 0
        -- 处理带引号的 CSV（Python csv.writer 输出格式："type,h,cid"）
        for cell in (line .. ','):gmatch('"([^"]*)",' ) do
            local parts = {}
            for p in (cell .. ','):gmatch('([^,]*),') do parts[#parts+1] = p end
            row[x] = {
                type = parts[1] or 'ground',
                h    = tonumber(parts[2]) or 0,
                cid  = tonumber(parts[3]) or 0,
            }
            x = x + 1
        end
        -- 处理无引号 CSV（兼容简单格式）
        if x == 0 then
            for cell in (line .. ','):gmatch('([^,]+),') do
                -- 单值格式（如 texture_grid.csv）
                row[x] = {type='ground', h=0, cid=tonumber(cell) or 0}
                x = x + 1
            end
        end
        cells[H] = row
        W = math.max(W, x)
        H = H + 1
    end
    f:close()
    return cells, W, H
end

-- ─────────────────────────────────────────────────────────────────────────────
-- 种子管理
-- ─────────────────────────────────────────────────────────────────────────────

---获取或创建本局种子
--- 优先从游戏房间自定义参数读取（支持主播/玩家指定种子复现游戏）
--- 没有时用 Y3 随机种子
---@return integer seed
function MapLoader.get_or_create_seed()
    -- 尝试从房间参数获取（Y3 自定义开局参数）
    local ok, room_seed = pcall(function()
        return GameAPI.get_game_custom_data('map_seed')
    end)
    if ok and room_seed and room_seed ~= 0 then
        return room_seed
    end
    -- 用 Y3 引擎随机种子（每局不同，但可从日志复现）
    local seed = os.time() % 100000  -- 简单方案：时间戳后5位
    -- 或使用 GameAPI.get_random_seed() 如果 Y3 提供
    return seed
end

-- ─────────────────────────────────────────────────────────────────────────────
-- 布局生成（整合 map_layout）
-- ─────────────────────────────────────────────────────────────────────────────

---用种子生成本局布局（每局随机，相同种子完全复现）
---@param cells table  terrain_grid.csv 解析结果
---@param map_size table {width, height}
---@param seed integer
---@param options table|nil 可覆盖 map_layout 默认参数
---@return table layout
function MapLoader.generate_layout(cells, map_size, seed, options)
    local W = map_size.width
    local H = map_size.height
    local rng     = MapRng.new(seed)
    local terrain = MapLayout.build_terrain_from_csv(cells, W, H)
    return MapLayout.generate(terrain, rng, options)
end

-- ─────────────────────────────────────────────────────────────────────────────
-- Y3 世界写入
-- ─────────────────────────────────────────────────────────────────────────────

-- Y3 坐标转换：格子 (x,z) → 世界坐标 (wx, wz)
-- world_x = grid_x * 2 - (W - 1)
local function grid_to_world(gx, gz, W, H)
    return gx * 2 - (W - 1), gz * 2 - (H - 1)
end

---节点类型 → 模型 ID 映射（可由项目覆盖）
---使用 decoration_catalog.json 中的真实模型 ID
MapLoader.NODE_MODELS = {
    capital    = nil,     -- 首都由游戏逻辑处理，不放摆件
    start_point= nil,     -- 起点由出生点逻辑处理
    resource   = 201669,  -- 资源点：国风灰色景观石（占位）
    lair       = 100001,  -- 怪物巢穴：枯树（占位）
    dungeon    = 202028,  -- 地牢：黑色景观石（占位）
    ruin       = 201671,  -- 遗迹：灰色景观石3（占位）
    enemy      = 100001,  -- 敌人刷新区：枯树（占位）
}

---写入游戏节点（资源点、巢穴、遗迹、敌人刷新区）
---@param layout table map_layout.generate 的返回值
---@param map_size table {width, height}
function MapLoader.apply_nodes(layout, map_size)
    local W, H = map_size.width, map_size.height

    local function place(node_list, node_type)
        local mid = MapLoader.NODE_MODELS[node_type]
        if not mid or not node_list then return end
        for _, node in ipairs(node_list) do
            local wx, wz = grid_to_world(node.x, node.z, W, H)
            -- Y3 实体创建
            GameAPI.entity_create({
                type           = 16777216,  -- RESOURCE_MODEL
                pos            = {wx, 0, wz},
                model_id       = mid,
                yaw            = 0, pitch = 0, roll = 0,
                scale          = {2.5, 2.5, 2.5},
                stick_to_ground= true,
            })
        end
    end

    place(layout.resources,   'resource')
    place(layout.lairs,       'lair')
    place(layout.ruins,       'ruin')
    place(layout.enemy_zones, 'enemy')

    -- 设置首都出生点（Y3 出生点 API）
    if layout.capital then
        local wx, wz = grid_to_world(layout.capital.x, layout.capital.z, W, H)
        pcall(function()
            GameAPI.set_born_point(1, wx, wz)  -- 玩家1出生点
        end)
    end

    -- 起点（可用于多人游戏不同起点）
    if layout.start_point then
        local wx, wz = grid_to_world(layout.start_point.x, layout.start_point.z, W, H)
        pcall(function()
            GameAPI.set_born_point(2, wx, wz)
        end)
    end
end

---写入装饰实体（树木/山石），支持用种子重新随机化位置和模型
---@param entities table decoration_entities.json 解析结果
---@param opts table {seed=integer, skip_tags=table, scale_mult=number}
function MapLoader.apply_decorations(entities, opts)
    opts = opts or {}
    local skip = {}
    for _, tag in ipairs(opts.skip_tags or {}) do skip[tag] = true end

    local rng = opts.seed and MapRng.new(opts.seed) or nil
    local scale_mult = opts.scale_mult or 1.0

    for _, ent in ipairs(entities) do
        if not skip[ent._tag] then
            local scale = ent.scale or {1,1,1}
            local yaw   = ent.yaw or 0

            -- 如果提供了种子，随机化旋转角度（保持位置不变）
            if rng then
                yaw = rng:int(0, 359)
                local s = scale[1] * scale_mult * rng:float(0.85, 1.15)
                scale = {s, s, s}
            end

            pcall(function()
                GameAPI.entity_create({
                    type            = ent.type or 16777216,
                    pos             = ent.pos,
                    model_id        = ent.model_id,
                    yaw             = yaw, pitch = 0, roll = 0,
                    scale           = scale,
                    stick_to_ground = true,
                })
            end)
        end
    end
end

---写入道路（纹理覆盖），road_grid 为 128x128 bool 表
---@param road_grid table road_grid[z][x] = bool
---@param road_texture_id integer 道路纹理 ID
---@param map_size table {width, height}
function MapLoader.apply_roads(road_grid, road_texture_id, map_size)
    road_texture_id = road_texture_id or 141  -- 鹅卵石路（默认）
    local W, H = map_size.width, map_size.height
    local cells = {}
    for z = 0, H-1 do
        if road_grid[z] then
            for x = 0, W-1 do
                if road_grid[z][x] then
                    cells[#cells+1] = {x=x, z=z, texture_id=road_texture_id}
                end
            end
        end
    end
    if #cells > 0 then
        pcall(function()
            GameAPI.terrain_cover_draw_block({cells=cells})
        end)
    end
end

-- ─────────────────────────────────────────────────────────────────────────────
-- 一键初始化（整合上述所有步骤）
-- ─────────────────────────────────────────────────────────────────────────────

---完整初始化：读取数据 → 生成布局 → 写入 Y3
---@param data_dir string  数据目录（含 postprocess_plan.json, decoration_entities.json, terrain_grid.csv）
---@param seed integer|nil 指定种子（nil = 自动生成）
---@param options table|nil map_layout 参数覆盖
function MapLoader.init(data_dir, seed, options)
    local sep = data_dir:sub(-1) == '/' and '' or '/'
    local base = data_dir .. sep

    -- 1. 读取静态数据
    local plan        = MapLoader.load_json(base .. 'postprocess_plan.json')
    local decorations = MapLoader.load_json(base .. 'decoration_entities.json')
    local cells, W, H = MapLoader.load_terrain_csv(base .. 'terrain_grid.csv')

    -- 2. 确定种子
    seed = seed or MapLoader.get_or_create_seed()
    print(string.format('[MapLoader] 本局种子: %d', seed))

    -- 3. 生成随机布局
    local map_size = plan and plan.map_size or {width=W, height=H}
    local layout   = MapLoader.generate_layout(cells, map_size, seed, options)

    print(string.format('[MapLoader] 布局: 首都(%d,%d) 起点(%d,%d) 资源×%d 巢穴×%d 遗迹×%d 敌人×%d',
        layout.capital.x, layout.capital.z,
        layout.start_point.x, layout.start_point.z,
        #layout.resources, #layout.lairs, #layout.ruins, #layout.enemy_zones))

    -- 4. 写入 Y3
    MapLoader.apply_nodes(layout, map_size)
    MapLoader.apply_decorations(decorations, {seed=seed, skip_tags={'resource','lair','ruin','enemy'}})

    return layout
end

return MapLoader
