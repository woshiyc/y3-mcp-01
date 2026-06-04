-- guild/quest_manager.lua
-- 协调器：串联所有公会模块，提供对外接口，驱动游戏日计时器
local AdvData    = require 'guild.adventurer_data'
local QuestData  = require 'guild.quest_data'
local QuestBoard = require 'guild.quest_board'
local Dispatch   = require 'guild.quest_dispatch'
local Execution  = require 'guild.quest_execution'
local Settlement = require 'guild.quest_settlement'

local M = {}

-- 游戏日时长（秒）= 600（10分钟）
local GAME_DAY_SECONDS = 600

--- 初始化系统（在游戏-初始化事件中调用一次）
--- 启动游戏日定时器，每 GAME_DAY_SECONDS 秒触发闲置惩罚
function M.init()
    y3.timer.loop(GAME_DAY_SECONDS, function()
        AdvData.tick_idle_penalty()
        log.info("[Guild] 游戏日结束，闲置惩罚已结算")
    end)
    log.info("[Guild] 冒险者公会任务系统已初始化")
end

--- 发布任务（领地事件触发 或 玩家主动创建）
--- 自动收集报名
---@param title string
---@param rank_int integer  1~7
---@param quest_type string  QuestData.TYPE 中的值
---@param bounty_mult number  0.5/0.75/1.0/1.25/1.5
---@param time_limit number|nil
---@return string quest_id
function M.post_quest(title, rank_int, quest_type, bounty_mult, time_limit)
    local q = QuestData.create(title, rank_int, quest_type, time_limit)
    QuestData.post(q.id, bounty_mult)
    QuestBoard.collect_registrations(q.id)
    log.info("[Guild] 任务已发布: " .. title .. " (id=" .. q.id .. ")")
    return q.id
end

--- 执行派遣（玩家从报名池中选人后调用）
---@param quest_id string
---@param selected_ids string[]  从报名池中选择的冒险者 ID
---@param equip_ids string[]     借出装备 ID 列表
---@param target_point table     {x: number, z: number}
---@return boolean  true=派遣成功
function M.dispatch_quest(quest_id, selected_ids, equip_ids, target_point)
    local ok = Dispatch.dispatch(quest_id, selected_ids, equip_ids)
    if not ok then
        log.error("[Guild] 派遣失败: " .. quest_id)
        return false
    end

    -- 启动实时执行，回调中进行结算
    Execution.start(quest_id, target_point, function(qid, outcome)
        local result = Settlement.settle(qid, outcome)
        M._on_settlement(qid, result)
    end, function(qid, card)
        -- 事件卡回调：记录日志，UI 层可在此扩展弹出选项卡
        log.info("[Guild] 事件卡触发: " .. card.id .. " — " .. card.text)
        -- TODO(Task 9): 通过 quest_ui 弹出选项卡，让玩家做选择
    end)

    log.info("[Guild] 任务已派遣: " .. quest_id)
    return true
end

--- 玩家主动召回任务
---@param quest_id string
function M.recall_quest(quest_id)
    Execution.recall(quest_id)
    log.info("[Guild] 召回任务: " .. quest_id)
end

--- 结算后处理：发放金币、广播消息
---@param quest_id string
---@param result SettlementResult
function M._on_settlement(quest_id, result)
    local quest = QuestData.get(quest_id)
    if not quest then return end

    local player = y3.player.get_by_id(1)

    -- 发放金币
    if result.gold_reward > 0 then
        player:add_money(result.gold_reward)
    end

    -- 广播结算消息
    local msg = "[公会] " .. (quest.title or quest_id) .. " — " .. result.outcome
    if #result.lost_adv_ids > 0 then
        msg = msg .. " (" .. #result.lost_adv_ids .. "名冒险者永久失去)"
    end
    player:display_message(msg, 5)
    -- 显示结算面板（如 quest_ui 已加载）
    local ok, quest_ui = pcall(require, 'guild.quest_ui')
    if ok then quest_ui.show_settlement(result) end
    log.info("[Guild] 结算完成: " .. msg)
end

return M
