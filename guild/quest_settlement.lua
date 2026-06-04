-- guild/quest_settlement.lua
-- 结算模块：处理5种结算分支，更新冒险者忠诚度/经验/存活状态
local AdvData   = require 'guild.adventurer_data'
local QuestData = require 'guild.quest_data'
local Dispatch  = require 'guild.quest_dispatch'

local M = {}

-- 赏金倍率 → 忠诚度变化（成功时）
local LOYALTY_BY_MULT = {
    [0.5]=0, [0.75]=2, [1.0]=5, [1.25]=10, [1.5]=15
}

-- 任务基础经验奖励（按任务等级整数值）
local BASE_XP = {
    [1]=100, [2]=200, [3]=450, [4]=900, [5]=1800, [6]=3500, [7]=7000
}

---@class SettlementResult
---@field outcome string          "success"|"light_fail"|"heavy_fail"|"wipe"|"abort"
---@field gold_reward integer     玩家获得金币（仅 success 时有值）
---@field lost_adv_ids string[]   永久失去的冒险者 ID 列表
---@field lost_equip_ids string[] 损毁装备 ID 列表
---@field loyalty_changes table<string,integer>  adv_id → loyalty delta（净变化）

--- 计算装备平均等级整数值（占位实现：无装备返回0，有装备返回 fallback_rank）
--- TODO: 对接物品库后，从每个 eq_id 查询等级整数值，求平均
---@param equip_ids string[]
---@param fallback_rank integer  无法查询时的兜底值（同级装备）
---@return integer
local function calc_equip_avg_rank(equip_ids, fallback_rank)
    if #equip_ids == 0 then return 0 end
    return fallback_rank  -- 占位：返回任务等级（同级无修正）
end

--- 执行结算，根据 outcome 分支处理冒险者状态
---@param quest_id string
---@param outcome string  "success"|"light_fail"|"heavy_fail"|"wipe"|"abort"
---@return SettlementResult
function M.settle(quest_id, outcome)
    local quest = QuestData.get(quest_id)
    local result = {
        outcome         = outcome,
        gold_reward     = 0,
        lost_adv_ids    = {},
        lost_equip_ids  = {},
        loyalty_changes = {},
    }
    if not quest then return result end

    local dispatched = quest.dispatched_ids
    local equip_ids  = quest.equipment_ids

    -- ── 成功结算 ──────────────────────────────────────────────────────────
    if outcome == "success" then
        result.gold_reward = QuestData.total_reward(quest_id)
        local loyalty_gain = LOYALTY_BY_MULT[quest.bounty_mult] or 5

        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then
                AdvData.reset_idle(adv_id)        -- 归来时重置闲置计数
                adv.is_on_quest = false
                AdvData.change_loyalty(adv_id, loyalty_gain)
                result.loyalty_changes[adv_id] = loyalty_gain

                -- 专属奖励：任务类型匹配专长时额外 +5 忠诚度
                for _, specialty in ipairs(adv.specialties or {}) do
                    if specialty == quest.quest_type then
                        AdvData.change_loyalty(adv_id, 5)
                        result.loyalty_changes[adv_id] = (result.loyalty_changes[adv_id] or 0) + 5
                        break
                    end
                end

                -- 经验奖励（按经验倍率，多人平均分配）
                local xp_base = BASE_XP[quest.rank] or 100
                local mult = AdvData.xp_multiplier(quest.rank, adv.rank)
                AdvData.add_xp(adv_id, math.floor(xp_base * mult))
            end
        end
        QuestData.set_status(quest_id, QuestData.STATUS.SUCCEEDED)

    -- ── 轻度失败 / 召回（abort）─────────────────────────────────────────
    elseif outcome == "light_fail" or outcome == "abort" then
        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then
                AdvData.reset_idle(adv_id)
                adv.is_on_quest = false
                AdvData.change_loyalty(adv_id, -10)
                result.loyalty_changes[adv_id] = -10
                -- ⚠️ 失败路径才调用 check_departure（成功路径禁止调用）
                if AdvData.check_departure(adv_id) then
                    result.lost_adv_ids[#result.lost_adv_ids+1] = adv_id
                    AdvData.remove(adv_id)
                end
            end
        end
        QuestData.set_status(quest_id, QuestData.STATUS.FAILED)

    -- ── 重度失败 ──────────────────────────────────────────────────────────
    elseif outcome == "heavy_fail" then
        local equip_avg = calc_equip_avg_rank(equip_ids, quest.rank)
        local prob = Dispatch.calc_final_fail_prob(quest.rank, dispatched, equip_avg)

        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then
                if math.random() < prob.heavy then
                    -- 概率阵亡
                    result.lost_adv_ids[#result.lost_adv_ids+1] = adv_id
                    AdvData.remove(adv_id)
                else
                    -- 幸存者处理
                    AdvData.reset_idle(adv_id)
                    adv.is_on_quest = false
                    AdvData.change_loyalty(adv_id, -20)
                    result.loyalty_changes[adv_id] = -20
                    -- ⚠️ -20 可能推入动摇区，必须检查离队（失败路径）
                    if AdvData.check_departure(adv_id) then
                        result.lost_adv_ids[#result.lost_adv_ids+1] = adv_id
                        AdvData.remove(adv_id)
                    end
                end
            end
        end
        -- 装备损毁（与重度失败概率相同）
        for _, eq_id in ipairs(equip_ids) do
            if math.random() < prob.heavy then
                result.lost_equip_ids[#result.lost_equip_ids+1] = eq_id
            end
        end
        QuestData.set_status(quest_id, QuestData.STATUS.FAILED)

    -- ── 全灭 ──────────────────────────────────────────────────────────────
    elseif outcome == "wipe" then
        -- 所有派遣冒险者永久失去
        for _, adv_id in ipairs(dispatched) do
            result.lost_adv_ids[#result.lost_adv_ids+1] = adv_id
            AdvData.remove(adv_id)
        end
        result.lost_equip_ids = equip_ids

        -- 全灭事件对公会其他成员（未派遣的）造成 -20 士气
        local dispatched_set = {}
        for _, did in ipairs(dispatched) do dispatched_set[did] = true end

        for _, adv in ipairs(AdvData.get_all()) do
            if not dispatched_set[adv.id] then
                AdvData.change_loyalty(adv.id, -20)
                result.loyalty_changes[adv.id] = -20
            end
        end
        -- TODO(follow-up): 若旁观成员忠诚度跌至 0，按 spec 3.2 触发离队检查（后续迭代补充）
        QuestData.set_status(quest_id, QuestData.STATUS.FAILED)
    end

    return result
end

return M
