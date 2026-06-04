-- guild/quest_dispatch.lua
-- 派遣模块：队伍等级计算、失败概率计算（含装备修正）、执行派遣
local AdvData   = require 'guild.adventurer_data'
local QuestData = require 'guild.quest_data'

local M = {}

--- 计算队伍平均等级整数值（四舍五入）
---@param adv_ids string[]
---@return integer avg_rank_int
function M.calc_party_avg_rank(adv_ids)
    if #adv_ids == 0 then return 0 end
    local total = 0
    for _, id in ipairs(adv_ids) do
        local adv = AdvData.get(id)
        if adv then total = total + adv.rank end
    end
    return math.floor(total / #adv_ids + 0.5) -- 四舍五入
end

--- 计算基础失败概率（重度失败 / 全灭）
--- 基于 (任务等级 − 队伍平均等级) 的差值
---@param task_rank_int integer
---@param party_avg_rank integer
---@return table { heavy: number, wipe: number }  值域 [0, 1]
function M.calc_base_fail_prob(task_rank_int, party_avg_rank)
    local diff = task_rank_int - party_avg_rank
    if diff <= 0 then return { heavy=0.10, wipe=0.01 } end
    if diff == 1 then return { heavy=0.25, wipe=0.05 } end
    if diff == 2 then return { heavy=0.50, wipe=0.20 } end
    return { heavy=0.80, wipe=0.50 } -- diff >= 3
end

--- 计算装备修正量（正数=降低概率对玩家有利，负数=提高概率对玩家不利）
--- 基于 (装备平均等级 − 任务等级) 的差值
---@param equip_avg_rank integer  装备平均等级整数值（0 = 无装备）
---@param task_rank_int integer
---@return number delta
function M.calc_equip_delta(equip_avg_rank, task_rank_int)
    local diff = equip_avg_rank - task_rank_int
    if diff >= 1  then return -0.10 end  -- 装备超出任务等级：降低10%
    if diff == 0  then return  0.00 end  -- 同级：无修正
    if diff == -1 then return  0.05 end  -- 低一级：提高5%
    return 0.15                          -- 低两级以上：提高15%
end

--- 计算最终失败概率（叠加装备修正，概率钳制在 [0, 0.95]）
---@param task_rank_int integer
---@param adv_ids string[]
---@param equip_avg_rank integer
---@return table { heavy: number, wipe: number }
function M.calc_final_fail_prob(task_rank_int, adv_ids, equip_avg_rank)
    local avg   = M.calc_party_avg_rank(adv_ids)
    local base  = M.calc_base_fail_prob(task_rank_int, avg)
    local delta = M.calc_equip_delta(equip_avg_rank, task_rank_int)
    return {
        heavy = math.max(0, math.min(0.95, base.heavy + delta)),
        wipe  = math.max(0, math.min(0.95, base.wipe  + delta)),
    }
end

--- 执行派遣：将选定冒险者标记为任务中，任务状态转为 DISPATCHED
--- 验证所有 selected_ids 都在 quest.registered_ids 中
---@param quest_id string
---@param selected_ids string[]  玩家选择的冒险者 ID（必须来自报名池）
---@param equip_ids string[]     借出装备 ID 列表
---@return boolean  true=成功派遣，false=验证失败或状态不对
function M.dispatch(quest_id, selected_ids, equip_ids)
    local quest = QuestData.get(quest_id)
    if not quest or quest.status ~= QuestData.STATUS.POSTED then
        return false
    end
    if #selected_ids == 0 then return false end

    -- 验证所有选定 ID 都在报名池中
    local pool_set = {}
    for _, id in ipairs(quest.registered_ids) do pool_set[id] = true end
    for _, id in ipairs(selected_ids) do
        if not pool_set[id] then return false end
    end

    -- 标记冒险者为任务中并重置闲置计数
    for _, id in ipairs(selected_ids) do
        local adv = AdvData.get(id)
        if adv then
            adv.is_on_quest = true
            adv.idle_days = 0
        end
    end

    quest.dispatched_ids = selected_ids
    quest.equipment_ids  = equip_ids or {}
    QuestData.set_status(quest_id, QuestData.STATUS.DISPATCHED)
    return true
end

return M
