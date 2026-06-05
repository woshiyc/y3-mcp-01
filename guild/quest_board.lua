-- guild/quest_board.lua
-- 报名 AI 模块 V2：难度容忍幅度等级范围 + 特质行为门槛 + 赏金意愿权重排序
local AdvData     = require 'guild.adventurer_data'
local QuestData   = require 'guild.quest_data'
local TraitSystem = require 'guild.trait_system'

local M = {}

-- 难度 → 容忍幅度（1=简单 2=普通 3=困难 4=噩梦 5=地狱）
local DIFFICULTY_TOLERANCE = { [1]=4, [2]=3, [3]=2, [4]=1, [5]=0 }
local _difficulty = 2

function M.set_difficulty(level)
    assert(DIFFICULTY_TOLERANCE[level], "invalid difficulty: " .. tostring(level))
    _difficulty = level
end

function M.get_tolerance()
    return DIFFICULTY_TOLERANCE[_difficulty] or 3
end

--- Compute [min_rank, max_rank] for an adventurer. max_rank=nil means no upper limit.
---@param adv_id string
---@return integer min_rank, integer|nil max_rank
function M.get_rank_range(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return 1, nil end
    local tolerance = M.get_tolerance()
    local offset    = TraitSystem.get_level_min_offset(adv_id)
    local min_rank  = math.max(1, adv.rank - tolerance + offset)
    local max_rank  = TraitSystem.get_max_rank_cap(adv_id)
    return min_rank, max_rank
end

--- Collect registrations for a posted quest, sorted by signup weight (highest first).
---@param quest_id string
---@return string[]
function M.collect_registrations(quest_id)
    local quest = QuestData.get(quest_id)
    if not quest or quest.status ~= QuestData.STATUS.POSTED then return {} end

    local candidates = {}
    for _, adv in ipairs(AdvData.get_all()) do
        -- Gate 1: availability (not on quest, not resting, not on vacation)
        if not AdvData.is_available(adv.id) then goto continue end
        -- Gate 2: level range
        local min_r, max_r = M.get_rank_range(adv.id)
        if quest.rank < min_r then goto continue end
        if max_r and quest.rank > max_r then goto continue end
        -- Gate 3: trait behavior
        if TraitSystem.rejects_quest_type(adv.id, quest.quest_type) then goto continue end
        -- Passed: compute signup weight for ordering
        local w = TraitSystem.get_signup_weight(adv.id, quest.quest_type, quest.bounty_mult)
        candidates[#candidates+1] = { id=adv.id, weight=w }
        ::continue::
    end

    -- Sort by weight descending
    table.sort(candidates, function(a, b) return a.weight > b.weight end)

    local pool = {}
    for _, c in ipairs(candidates) do pool[#pool+1] = c.id end
    quest.registered_ids = pool
    return pool
end

--- Query current registration pool (no recompute).
---@param quest_id string
---@return string[]
function M.get_pool(quest_id)
    local quest = QuestData.get(quest_id)
    if not quest then return {} end
    return quest.registered_ids or {}
end

return M
