-- guild/adventurer_data.lua
-- 冒险者数据模块 V2：等级/经验/特质/修养/休假状态逻辑（V2 删除忠诚度系统）
---@class AdventurerData
local M = {}

-- 等级整数值映射
M.RANK_INT = { F=1, E=2, D=3, C=4, B=5, A=6, S=7 }
M.INT_RANK = { [1]="F", [2]="E", [3]="D", [4]="C", [5]="B", [6]="A", [7]="S" }

-- 升级所需经验
M.XP_TO_NEXT = { [1]=300, [2]=800, [3]=2000, [4]=5000, [5]=12000 }
-- rank 6(A)→7(S) 升级仅通过随机事件触发，不通过经验

-- 存储所有冒险者的全局表
local _adventurers = {} ---@type table<string, AdventurerData>
local _next_id = 1

--- 创建新冒险者
---@param name string
---@param profession string
---@param rank_str string|nil 默认 "F"
---@return AdventurerData
function M.create(name, profession, rank_str)
    local id = "adv_" .. string.format("%03d", _next_id)
    _next_id = _next_id + 1
    local rank_val = M.RANK_INT[rank_str or "F"]
    assert(rank_val, "invalid rank_str: " .. tostring(rank_str))
    local adv = {
        id = id,
        name = name,
        rank = rank_val,
        xp = 0,
        traits = {},
        resting_days = 0,
        vacation_days = 0,
        heartbroken_days_left = 0,
        profession = profession,
        skills = {},
        specialties = {},   -- 专长任务类型，例如 {"hunt"} 或 {"explore","escort"}
        is_on_quest = false,
    }
    _adventurers[id] = adv
    return adv
end

--- 获取冒险者
---@param id string
---@return AdventurerData|nil
function M.get(id)
    return _adventurers[id]
end

--- 获取所有冒险者
---@return AdventurerData[]
function M.get_all()
    local result = {}
    for _, adv in pairs(_adventurers) do
        result[#result+1] = adv
    end
    return result
end

--- 移除冒险者（离队/阵亡）
---@param id string
function M.remove(id)
    _adventurers[id] = nil
end

--- 给予经验，自动触发升级（S 级不可经验升级）
---@param id string
---@param xp_amount integer
---@return boolean rank_up 是否升级
function M.add_xp(id, xp_amount)
    local adv = _adventurers[id]
    if not adv then return false end
    if adv.rank >= 6 then return false end -- A 级以上不可普通升级

    adv.xp = adv.xp + xp_amount
    local rank_up = false
    while true do
        local required = M.XP_TO_NEXT[adv.rank]
        if not required or adv.xp < required then break end
        adv.xp = adv.xp - required
        adv.rank = adv.rank + 1
        rank_up = true
        if adv.rank >= 6 then break end -- 升到 A 级后停止（S 级不可经验触发）
    end
    return rank_up
end

--- 计算任务经验倍率
--- task_rank_int: 任务等级整数值
--- adv_rank_int:  冒险者等级整数值
---@param task_rank_int integer
---@param adv_rank_int integer
---@return number multiplier
function M.xp_multiplier(task_rank_int, adv_rank_int)
    local diff = task_rank_int - adv_rank_int
    if diff >= 0 then return 1.0 end      -- 等级相符（diff=0）或更高（不可能发生但防御）
    if diff == -1 then return 0.5 end
    if diff == -2 then return 0.25 end
    return 0.1                            -- diff <= -3
end

--- Returns true if adventurer can accept quests right now
---@param id string
---@return boolean
function M.is_available(id)
    local adv = _adventurers[id]
    if not adv then return false end
    if adv.is_on_quest then return false end
    if adv.resting_days > 0 then return false end
    if adv.vacation_days > 0 then return false end
    return true
end

--- Called once per game day. Decrements rest/vacation counters for all adventurers.
function M.tick_daily()
    for _, adv in pairs(_adventurers) do
        if adv.resting_days > 0 then
            adv.resting_days = adv.resting_days - 1
        elseif adv.vacation_days > 0 then
            adv.vacation_days = adv.vacation_days - 1
        end
        if adv.heartbroken_days_left > 0 then
            adv.heartbroken_days_left = adv.heartbroken_days_left - 1
        end
    end
end

--- 重置所有冒险者数据（仅用于测试隔离）
function M.reset()
    _adventurers = {}
    _next_id = 1
end

return M
