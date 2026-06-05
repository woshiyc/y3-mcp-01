-- guild/casualty.lua
-- 伤亡判定链：存活/死亡判定、急救判定、修养/休假状态写入
local AdvData     = require 'guild.adventurer_data'
local TraitSystem = require 'guild.trait_system'

local M = {}

local BASE_SURVIVAL_RATE    = 0.60
local PER_RANK_BONUS        = 0.05
local BASE_FIRST_AID_RATE   = 0.50
local PER_CLERIC_RANK_BONUS = 0.10
local REST_MIN, REST_MAX    = 2, 4
local VACATION_CHANCE       = 0.50
local VACATION_MIN, VACATION_MAX = 1, 2

local function calc_survival_rate(adv_id, task_rank_int)
    local adv = AdvData.get(adv_id)
    if not adv then return 0 end
    local rate = BASE_SURVIVAL_RATE
    local rank_diff = adv.rank - task_rank_int
    if rank_diff > 0 then rate = rate + rank_diff * PER_RANK_BONUS end
    rate = rate + TraitSystem.get_stat_value(adv_id, "casualty_roll_bonus")
    return math.max(0, math.min(1, rate))
end

--- Perform the casualty survival roll.
--- Survived: calls enter_rest(). Dead: calls AdvData.remove().
---@param adv_id string
---@param task_rank_int integer
---@return boolean  true=survived (entered rest), false=permanently dead
function M.do_casualty_roll(adv_id, task_rank_int)
    local rate = calc_survival_rate(adv_id, task_rank_int)
    if math.random() <= rate then
        M.enter_rest(adv_id)
        return true
    else
        AdvData.remove(adv_id)
        return false
    end
end

--- Put adventurer into medical rest (resting_days = random [2,4]).
--- Marks is_on_quest = false.
---@param adv_id string
function M.enter_rest(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return end
    adv.is_on_quest = false
    adv.resting_days = math.random(REST_MIN, REST_MAX)
end

--- After rest ends: 50% chance of 1-2 vacation days.
---@param adv_id string
function M.trigger_vacation_check(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return end
    if math.random() <= VACATION_CHANCE then
        adv.vacation_days = math.random(VACATION_MIN, VACATION_MAX)
    end
end

local function calc_first_aid_rate(cleric_id, patient_id)
    local cleric  = AdvData.get(cleric_id)
    local patient = AdvData.get(patient_id)
    if not cleric or not patient then return 0 end
    local rate = BASE_FIRST_AID_RATE
    local rank_diff = cleric.rank - patient.rank
    if rank_diff > 0 then rate = rate + rank_diff * PER_CLERIC_RANK_BONUS end
    rate = rate + TraitSystem.get_stat_value(cleric_id, "first_aid_roll_bonus")
    return math.max(0, math.min(1, rate))
end

--- First-aid roll. Success → enter_rest(patient). Fail → casualty roll.
---@param cleric_id string
---@param patient_id string
---@param task_rank_int integer
---@return boolean  true=survived, false=dead
function M.do_first_aid_roll(cleric_id, patient_id, task_rank_int)
    if math.random() <= calc_first_aid_rate(cleric_id, patient_id) then
        M.enter_rest(patient_id)
        return true
    else
        return M.do_casualty_roll(patient_id, task_rank_int or 1)
    end
end

--- Process a downed adventurer in a party. Finds living priest or falls back to direct roll.
---@param patient_id string
---@param party_ids string[]
---@param task_rank_int integer
---@return boolean  true=survived, false=dead
function M.process_party_casualty(patient_id, party_ids, task_rank_int)
    local cleric_id = nil
    for _, id in ipairs(party_ids) do
        if id ~= patient_id then
            local adv = AdvData.get(id)
            if adv and adv.profession == "priest" and adv.is_on_quest then
                cleric_id = id; break
            end
        end
    end
    if cleric_id then
        return M.do_first_aid_roll(cleric_id, patient_id, task_rank_int)
    else
        return M.do_casualty_roll(patient_id, task_rank_int)
    end
end

return M
