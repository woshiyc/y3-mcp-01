-- guild/trait_system.lua
-- 特质系统 V2：特质库、触发判定、效果查询、报名权重计算
local AdvData = require 'guild.adventurer_data'

local M = {}

-- ── 特质库 ──────────────────────────────────────────────────────────────────
M.CATALOG = {
    -- 正面特质 (12)
    battle_veteran      = { id="battle_veteran",      name="战场老兵",   type="positive", removable=false, stat_effects={atk_mult=0.10, crit_bonus=0.05} },
    near_death_survivor = { id="near_death_survivor",  name="九死一生",   type="positive", removable=false, stat_effects={hp_mult=0.15, casualty_roll_bonus=0.10} },
    brave               = { id="brave",               name="勇猛",      type="positive", removable=false, stat_effects={boss_dmg_mult=0.15} },
    fearless            = { id="fearless",            name="无畏",      type="positive", removable=false, ignore_upper_cap=true },
    greedy              = { id="greedy",              name="贪财",      type="positive", removable=true,  level_min_offset=-1 },
    hunt_specialist     = { id="hunt_specialist",     name="讨伐专精",   type="positive", removable=false, prefer_quest_type="hunt",    stat_effects={hunt_atk_mult=0.10} },
    explorer            = { id="explorer",            name="探索者",    type="positive", removable=false, prefer_quest_type="explore",  stat_effects={explore_movespeed_mult=0.15} },
    guardian_instinct   = { id="guardian_instinct",   name="护卫直觉",   type="positive", removable=false, prefer_quest_type="escort",  stat_effects={escort_dmg_taken_mult=-0.10} },
    inspiring           = { id="inspiring",           name="鼓舞",      type="positive", removable=false, stat_effects={ally_atk_mult=0.05} },
    tenacious           = { id="tenacious",           name="坚韧",      type="positive", removable=false, stat_effects={first_aid_roll_bonus=0.15, casualty_roll_bonus=0.05} },
    fast_recovery       = { id="fast_recovery",       name="快速恢复",   type="positive", removable=true,  stat_effects={rest_duration_mult=-0.30} },
    lucky               = { id="lucky",               name="幸运",      type="positive", removable=true,  stat_effects={casualty_roll_bonus=0.05, positive_trigger_rate_bonus=0.10} },
    -- 负面特质 (16)
    heartbroken    = { id="heartbroken",    name="心灰意冷",  type="negative", removable=true,  reject_all_quests_days=3 },
    traumatized    = { id="traumatized",    name="怀疮",     type="negative", removable=true,  reject_quest_types={"hunt"} },
    acrophobia     = { id="acrophobia",     name="恐高",     type="negative", removable=true,  reject_quest_types={"mountain","aerial"} },
    social_anxiety = { id="social_anxiety", name="社恐",     type="negative", removable=true,  reject_quest_types={"escort","diplomatic"} },
    proud          = { id="proud",          name="骄傲",     type="negative", removable=true,  level_min_offset=1 },
    cowardly       = { id="cowardly",       name="懦弱",     type="negative", removable=true,  caps_at_own_rank=true },
    ptsd           = { id="ptsd",           name="应激障碍",  type="negative", removable=true,  stat_effects={triggered_combat_mult=-0.20} },
    fragile        = { id="fragile",        name="脆弱",     type="negative", removable=true,  stat_effects={hp_mult=-0.10, casualty_roll_bonus=-0.10} },
    alcoholic      = { id="alcoholic",      name="酗酒",     type="negative", removable=true,  stat_effects={skill_hit_mult=-0.05} },
    suspicious     = { id="suspicious",     name="多疑",     type="negative", removable=true,  signup_weight_mult=0.50 },
    coward_flee    = { id="coward_flee",    name="贪生怕死",  type="negative", removable=true,  flee_below_hp_pct=0.30 },
    paranoid       = { id="paranoid",       name="偏执",     type="negative", removable=false, stat_effects={triggered_combat_mult=-0.05} },
    quitter        = { id="quitter",        name="放弃癖",   type="negative", removable=true },
    shadow         = { id="shadow",         name="阴影",     type="negative", removable=true,  post_wipe_refuse_days=4 },
    self_doubt     = { id="self_doubt",     name="自我怀疑",  type="negative", removable=true,  stat_effects={skill_dmg_mult=-0.10} },
    trauma_response= { id="trauma_response",name="创伤应激",  type="negative", removable=true,  reject_last_failed_quest_type=true, stat_effects={related_combat_mult=-0.15} },
}

local POS_POOL, NEG_POOL = {}, {}
for id, t in pairs(M.CATALOG) do
    if t.type == "positive" then POS_POOL[#POS_POOL+1] = id
    else NEG_POOL[#NEG_POOL+1] = id end
end

local POSITIVE_RATE = 0.25
local NEGATIVE_RATE = 0.40

-- ── Internal ──────────────────────────────────────────────────────────────

local function find_removable_index(traits)
    for i, t in ipairs(traits) do
        if M.CATALOG[t] and M.CATALOG[t].removable then return i end
    end
    return nil
end

local function pick_random_new(pool, existing_set)
    local candidates = {}
    for _, id in ipairs(pool) do
        if not existing_set[id] then candidates[#candidates+1] = id end
    end
    if #candidates == 0 then return nil end
    return candidates[math.random(#candidates)]
end

-- ── Public API ────────────────────────────────────────────────────────────

function M.add_trait(adv_id, trait_id)
    local adv = AdvData.get(adv_id)
    if not adv or not M.CATALOG[trait_id] then return false end
    local existing = {}
    for _, t in ipairs(adv.traits) do existing[t] = true end
    if existing[trait_id] then return false end
    if #adv.traits >= 6 then
        local ri = find_removable_index(adv.traits)
        if not ri then return false end
        table.remove(adv.traits, ri)
    end
    adv.traits[#adv.traits+1] = trait_id
    return true
end

function M.has_trait(adv_id, trait_id)
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    for _, t in ipairs(adv.traits) do
        if t == trait_id then return true end
    end
    return false
end

function M.get_level_min_offset(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return 0 end
    local offset = 0
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def and def.level_min_offset then offset = offset + def.level_min_offset end
    end
    return offset
end

function M.get_max_rank_cap(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return nil end
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def and def.caps_at_own_rank then return adv.rank end
    end
    return nil
end

function M.rejects_quest_type(adv_id, quest_type)
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def then
            if def.reject_all_quests_days and (adv.heartbroken_days_left or 0) > 0 then
                return true
            end
            if def.reject_quest_types then
                for _, rt in ipairs(def.reject_quest_types) do
                    if rt == quest_type then return true end
                end
            end
        end
    end
    return false
end

--- Returns a signup weight multiplier for this adventurer on a given quest.
--- Base weight = bounty_mult. prefer_quest_type match adds 0.5. signup_weight_mult scales down.
---@param adv_id string
---@param quest_type string
---@param bounty_mult number
---@return number
function M.get_signup_weight(adv_id, quest_type, bounty_mult)
    local adv = AdvData.get(adv_id)
    if not adv then return 0 end
    local weight = bounty_mult
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def then
            if def.prefer_quest_type == quest_type then weight = weight + 0.5 end
            if def.signup_weight_mult then weight = weight * def.signup_weight_mult end
        end
    end
    return weight
end

function M.trigger_negative_roll(adv_id)
    return M.trigger_negative_roll_at_rate(adv_id, NEGATIVE_RATE)
end

--- Trigger a negative trait roll at a custom probability rate.
---@param adv_id string
---@param rate number  probability in [0,1]
---@return boolean
function M.trigger_negative_roll_at_rate(adv_id, rate)
    if math.random() > rate then return false end
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    local existing = {}
    for _, t in ipairs(adv.traits) do existing[t] = true end
    local chosen = pick_random_new(NEG_POOL, existing)
    if not chosen then return false end
    return M.add_trait(adv_id, chosen)
end

function M.trigger_positive_roll(adv_id)
    local rate = POSITIVE_RATE
    if M.has_trait(adv_id, "lucky") then
        rate = rate + (M.CATALOG.lucky.stat_effects.positive_trigger_rate_bonus or 0.10)
    end
    if math.random() > rate then return false end
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    local existing = {}
    for _, t in ipairs(adv.traits) do existing[t] = true end
    local chosen = pick_random_new(POS_POOL, existing)
    if not chosen then return false end
    return M.add_trait(adv_id, chosen)
end

--- Accumulate a numeric stat value from all traits.
--- For "_bonus" suffix keys: returns sum of all matching values.
--- For other keys: returns 1.0 + sum (multiplicative base).
---@param adv_id string
---@param stat_key string
---@return number
function M.get_stat_value(adv_id, stat_key)
    local adv = AdvData.get(adv_id)
    if not adv then return stat_key:find("_bonus$") and 0.0 or 1.0 end
    local total = 0.0
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def and def.stat_effects and def.stat_effects[stat_key] then
            total = total + def.stat_effects[stat_key]
        end
    end
    if stat_key:find("_bonus$") then return total end
    return 1.0 + total
end

return M
