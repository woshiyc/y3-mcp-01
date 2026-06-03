--- map_rng.lua — 可复现的种子随机数生成器
--- 使用 LCG（线性同余生成器），纯 Lua 实现，不依赖 GameAPI
--- 保证：相同 seed → 相同调用序列 → 完全相同的地图布局
---
--- 用法：
---   local rng = require('map_rng').new(seed)
---   rng:int(1, 10)       -- [1, 10] 整数
---   rng:float()          -- [0, 1) 浮点
---   rng:float(a, b)      -- [a, b) 浮点
---   rng:shuffle(t)       -- 原地打乱数组
---   rng:choice(t)        -- 从数组随机取一个
---   rng:weighted(t)      -- 按 weight 字段加权随机取一个

---@class MapRng
local MapRng = {}
MapRng.__index = MapRng

-- LCG 参数（Numerical Recipes 推荐值，32-bit）
local LCG_A = 1664525
local LCG_C = 1013904223
local LCG_M = 2147483648  -- 2^31

---创建一个新的随机数生成器
---@param seed integer 随机种子（整数），相同 seed 产生相同序列
---@return MapRng
function MapRng.new(seed)
    local self = setmetatable({}, MapRng)
    -- 初始化时做几次预热，避免低 seed 时初始质量差
    self._state = (seed or 42) % LCG_M
    for _ = 1, 8 do self:_advance() end
    return self
end

---内部：推进一步，返回 [0, LCG_M-1] 整数
---@return integer
function MapRng:_advance()
    self._state = (self._state * LCG_A + LCG_C) % LCG_M
    return self._state
end

---生成 [0, 1) 浮点数
---@return number
function MapRng:float(a, b)
    local v = self:_advance() / LCG_M
    if a == nil then return v end
    return a + v * (b - a)
end

---生成 [min, max] 整数（含两端）
---@param min integer
---@param max integer
---@return integer
function MapRng:int(min, max)
    if min == max then return min end
    return min + self:_advance() % (max - min + 1)
end

---以 50% 概率返回 true
---@return boolean
function MapRng:bool()
    return self:_advance() % 2 == 0
end

---以指定概率返回 true
---@param p number 概率 [0,1]
---@return boolean
function MapRng:chance(p)
    return self:float() < p
end

---原地 Fisher-Yates 洗牌
---@param t table 数组
function MapRng:shuffle(t)
    for i = #t, 2, -1 do
        local j = self:int(1, i)
        t[i], t[j] = t[j], t[i]
    end
end

---从数组随机取一个元素（不修改原数组）
---@param t table 非空数组
---@return any
function MapRng:choice(t)
    return t[self:int(1, #t)]
end

---加权随机选择（元素需有 weight 字段）
---@param t table 含 {weight=number, ...} 的数组
---@return table|nil
function MapRng:weighted(t)
    local total = 0
    for _, v in ipairs(t) do total = total + (v.weight or 1) end
    local r = self:float() * total
    for _, v in ipairs(t) do
        r = r - (v.weight or 1)
        if r <= 0 then return v end
    end
    return t[#t]
end

---从数组中取 n 个不重复元素（n <= #t）
---@param t table 数组
---@param n integer 取出数量
---@return table 新数组，长度为 min(n, #t)
function MapRng:sample(t, n)
    local copy = {}
    for i, v in ipairs(t) do copy[i] = v end
    self:shuffle(copy)
    local result = {}
    for i = 1, math.min(n, #copy) do result[i] = copy[i] end
    return result
end

return MapRng
