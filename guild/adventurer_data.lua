-- guild/adventurer_data.lua
-- 冒险者数据模块：等级/忠诚度/经验/闲置惩罚逻辑
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
        loyalty = 60,
        profession = profession,
        skills = {},
        specialties = {},   -- 专长任务类型，例如 {"hunt"} 或 {"explore","escort"}
        is_on_quest = false,
        idle_days = 0,
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

--- 修改忠诚度，自动钳制在 [0, 100]
---@param id string
---@param delta integer
function M.change_loyalty(id, delta)
    local adv = _adventurers[id]
    if not adv then return end
    adv.loyalty = math.max(0, math.min(100, adv.loyalty + delta))
end

--- 判断冒险者是否处于动摇状态
---@param id string
---@return boolean
function M.is_wavering(id)
    local adv = _adventurers[id]
    return adv ~= nil and adv.loyalty <= 20
end

--- 判断是否应该离队（仅在失败事件后调用，NOT 在成功时调用）
--- 规则：loyalty=0 必然离队；动摇状态(≤20)下有 30% 概率离队
--- ⚠️ 只在 settlement 的失败/abort 分支中调用，成功结算不触发
---@param id string
---@return boolean
function M.check_departure(id)
    local adv = _adventurers[id]
    if not adv then return false end
    if adv.loyalty == 0 then return true end   -- loyalty=0 必然离队
    if M.is_wavering(id) then
        -- 动摇状态下 30% 概率离队（仅失败路径触发）
        return math.random(100) <= 30
    end
    return false
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

--- 处理闲置惩罚（每游戏日结束时对所有冒险者调用）
--- 规则：不在任务中的冒险者，每满1游戏日扣3忠诚度（第1天结束时开始）
--- 在任务中的冒险者 idle_days 不增加（结算时由 reset_idle 重置）
function M.tick_idle_penalty()
    for _, adv in pairs(_adventurers) do
        if not adv.is_on_quest then
            adv.idle_days = adv.idle_days + 1
            -- 每满1游戏日扣3忠诚度（从第1天结束开始计）
            M.change_loyalty(adv.id, -3)
        end
        -- is_on_quest=true 时不操作 idle_days，由 reset_idle 在结算时重置
    end
end

--- 冒险者从任务归来时重置闲置计数（由 settlement 模块在解除 is_on_quest 前调用）
---@param id string
function M.reset_idle(id)
    local adv = _adventurers[id]
    if adv then adv.idle_days = 0 end
end

--- 重置所有冒险者数据（仅用于测试隔离）
function M.reset()
    _adventurers = {}
    _next_id = 1
end

return M
