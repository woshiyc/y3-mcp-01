-- guild/quest_settlement.lua
-- 结算模块 V2：三分支结算（success/abort/wipe），触发特质判定
-- 注：V2 删除 light_fail/heavy_fail 概率分支，伤亡由 casualty.lua 实时处理
local AdvData     = require 'guild.adventurer_data'
local QuestData   = require 'guild.quest_data'
local TraitSystem = require 'guild.trait_system'
local Casualty    = require 'guild.casualty'

local M = {}

local BASE_XP = { [1]=100,[2]=200,[3]=450,[4]=900,[5]=1800,[6]=3500,[7]=7000 }

---@class SettlementResult
---@field outcome string           "success"|"abort"|"wipe"
---@field gold_reward integer
---@field lost_adv_ids string[]
---@field lost_equip_ids string[]

local function run_post_settlement_trait_rolls(adv_ids, is_success, is_abort)
    for _, adv_id in ipairs(adv_ids) do
        if AdvData.get(adv_id) then
            if is_success then
                TraitSystem.trigger_positive_roll(adv_id)
                TraitSystem.trigger_negative_roll(adv_id)
            elseif is_abort then
                -- Single roll at 60% (higher than combat failure's 40%), per spec §3.3
                TraitSystem.trigger_negative_roll_at_rate(adv_id, 0.60)
            else
                TraitSystem.trigger_negative_roll(adv_id)  -- 40% rate
            end
            local adv = AdvData.get(adv_id)
            if adv and adv.resting_days > 0 then
                -- Extra roll for resting adventurers (50% rate)
                TraitSystem.trigger_negative_roll_at_rate(adv_id, 0.50)
                Casualty.trigger_vacation_check(adv_id)
            end
        end
    end
end

---@param quest_id string
---@param outcome string  "success"|"abort"|"wipe"
---@return SettlementResult
function M.settle(quest_id, outcome)
    local quest = QuestData.get(quest_id)
    local result = { outcome=outcome, gold_reward=0, lost_adv_ids={}, lost_equip_ids={} }
    if not quest then return result end

    local dispatched = quest.dispatched_ids
    local equip_ids  = quest.equipment_ids

    if outcome == "success" then
        result.gold_reward = QuestData.total_reward(quest_id)
        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then
                adv.is_on_quest = false
                local xp_base = BASE_XP[quest.rank] or 100
                local mult    = AdvData.xp_multiplier(quest.rank, adv.rank)
                AdvData.add_xp(adv_id, math.floor(xp_base * mult))
            end
        end
        run_post_settlement_trait_rolls(dispatched, true, false)
        QuestData.set_status(quest_id, QuestData.STATUS.SUCCEEDED)

    elseif outcome == "abort" then
        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then adv.is_on_quest = false end
        end
        run_post_settlement_trait_rolls(dispatched, false, true)
        QuestData.set_status(quest_id, QuestData.STATUS.ABORTED)

    elseif outcome == "wipe" then
        for _, adv_id in ipairs(dispatched) do
            result.lost_adv_ids[#result.lost_adv_ids+1] = adv_id
            AdvData.remove(adv_id)
        end
        result.lost_equip_ids = equip_ids
        local dispatched_set = {}
        for _, did in ipairs(dispatched) do dispatched_set[did] = true end
        for _, adv in ipairs(AdvData.get_all()) do
            if not dispatched_set[adv.id] then
                TraitSystem.trigger_negative_roll(adv.id)
            end
        end
        QuestData.set_status(quest_id, QuestData.STATUS.FAILED)
    end

    return result
end

return M
