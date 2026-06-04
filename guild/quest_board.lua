-- guild/quest_board.lua
-- 报名 AI 模块：冒险者自主决定是否报名，基于等级/闲置/忠诚度三重门槛
local AdvData   = require 'guild.adventurer_data'
local QuestData = require 'guild.quest_data'

local M = {}

-- 按忠诚度决定最低可接受赏金倍率
-- 80~100 → 0.5x，60~79 → 0.75x，40~59 → 1.0x，21~39 → 1.25x，≤20 → 1.5x
local function min_acceptable_mult(loyalty)
    if loyalty >= 80 then return 0.5  end
    if loyalty >= 60 then return 0.75 end
    if loyalty >= 40 then return 1.0  end
    if loyalty >= 21 then return 1.25 end
    return 1.5  -- 动摇状态（≤20）极度挑剔
end

--- 对一个已挂牌任务执行报名 AI
--- 三重门槛：① 等级够（adv.rank >= quest.rank）② 空闲（not is_on_quest）③ 赏金达意愿
--- 结果写入 quest.registered_ids 并返回
---@param quest_id string
---@return string[]  愿意报名的冒险者 ID 列表
function M.collect_registrations(quest_id)
    local quest = QuestData.get(quest_id)
    if not quest or quest.status ~= QuestData.STATUS.POSTED then
        return {}
    end

    local pool = {}
    for _, adv in ipairs(AdvData.get_all()) do
        -- 条件1：技术门槛（等级够，高等级可接低等级任务，低等级不可接高等级任务）
        if adv.rank < quest.rank then goto continue end
        -- 条件2：空闲检查（当前无任务）
        if adv.is_on_quest then goto continue end
        -- 条件3：赏金门槛（忠诚度决定最低可接受倍率）
        local min_mult = min_acceptable_mult(adv.loyalty)
        if quest.bounty_mult < min_mult then goto continue end

        pool[#pool+1] = adv.id
        ::continue::
    end

    quest.registered_ids = pool
    return pool
end

--- 查询某任务的当前报名池（不重新计算）
---@param quest_id string
---@return string[]
function M.get_pool(quest_id)
    local quest = QuestData.get(quest_id)
    if not quest then return {} end
    return quest.registered_ids
end

return M
