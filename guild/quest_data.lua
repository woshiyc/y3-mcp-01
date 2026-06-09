-- guild/quest_data.lua
-- 任务数据模块：状态机定义、创建/查询/状态转移、赏金计算
local M = {}

-- 任务状态机
M.STATUS = {
    PENDING     = "pending",      -- 已生成，未挂牌
    POSTED      = "posted",       -- 已挂牌，等待报名
    DISPATCHED  = "dispatched",   -- 已派遣，执行中
    SUCCEEDED   = "succeeded",    -- 成功结算
    FAILED      = "failed",       -- 失败结算
    ABORTED     = "aborted",      -- 玩家主动召回
}

-- 任务类型
M.TYPE = {
    HUNT        = "hunt",         -- 讨伐
    EXPLORE     = "explore",      -- 探索
    ESCORT      = "escort",       -- 护送/追剿
    INVESTIGATE = "investigate",  -- 调查
    STRATEGIC   = "strategic",    -- 战略任务（玩家主动）
}

local _quests = {} ---@type table<string, QuestData>
local _next_id = 1

---@class QuestData
---@field id string
---@field title string
---@field rank integer           -- 任务等级整数值 1~7
---@field quest_type string      -- M.TYPE 中的值
---@field reward_base integer    -- 基础赏金（金币）
---@field bounty_mult number     -- 赏金倍率 0.5/0.75/1.0/1.25/1.5
---@field status string          -- M.STATUS 中的值
---@field time_limit number|nil  -- 截止游戏日数，nil=无期限
---@field registered_ids string[] -- 已报名的冒险者 ID 列表
---@field dispatched_ids string[] -- 已派遣的冒险者 ID 列表
---@field equipment_ids string[]  -- 借出装备 ID 列表
---@field created_at number       -- 创建时的游戏时间戳

-- 基础赏金表（按任务等级整数值）
local BASE_REWARD = {
    [1]=50, [2]=150, [3]=400, [4]=1000, [5]=2500, [6]=6000, [7]=15000
}

-- 有效赏金倍率集合
local VALID_MULTS = { [0.5]=true, [0.75]=true, [1.0]=true, [1.25]=true, [1.5]=true }

--- 创建新任务
---@param title string
---@param rank_int integer  1(F)~7(S)
---@param quest_type string  M.TYPE 中的值
---@param time_limit number|nil
---@return QuestData
function M.create(title, rank_int, quest_type, time_limit)
    assert(BASE_REWARD[rank_int], "invalid rank_int: " .. tostring(rank_int))
    local id = "quest_" .. string.format("%04d", _next_id)
    _next_id = _next_id + 1
    local quest = {
        id = id,
        title = title,
        rank = rank_int,
        quest_type = quest_type,
        reward_base = BASE_REWARD[rank_int],
        bounty_mult = 1.0,
        status = M.STATUS.PENDING,
        time_limit = time_limit,
        registered_ids = {},
        dispatched_ids = {},
        equipment_ids = {},
        created_at = os.clock(),
    }
    _quests[id] = quest
    return quest
end

--- 获取任务
---@param id string
---@return QuestData|nil
function M.get(id)
    return _quests[id]
end

--- 获取所有处于指定状态的任务
---@param status string
---@return QuestData[]
function M.get_by_status(status)
    local result = {}
    for _, q in pairs(_quests) do
        if q.status == status then result[#result+1] = q end
    end
    return result
end

--- 设置赏金倍率并发布任务（PENDING → POSTED）
--- 无效倍率或非 PENDING 状态时静默忽略
---@param id string
---@param mult number  0.5/0.75/1.0/1.25/1.5
function M.post(id, mult)
    local q = _quests[id]
    if not q or q.status ~= M.STATUS.PENDING then return end
    if not VALID_MULTS[mult] then return end
    q.bounty_mult = mult
    q.status = M.STATUS.POSTED
end

--- 转移任务状态
---@param id string
---@param new_status string
function M.set_status(id, new_status)
    local q = _quests[id]
    if q then q.status = new_status end
end

--- 计算实际赏金总额（floor）
---@param id string
---@return integer
function M.total_reward(id)
    local q = _quests[id]
    if not q then return 0 end
    return math.floor(q.reward_base * q.bounty_mult)
end

return M
