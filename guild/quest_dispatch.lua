-- guild/quest_dispatch.lua
-- 派遣模块 V2：队伍平均等级计算、报名资格验证、执行派遣
-- 注：V2 删除概率失败计算层，任务成败由实时执行和 casualty.lua 决定
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
