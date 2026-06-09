-- guild/quest_ui.lua
-- UI 绑定层：连接公会逻辑与 Y3 UI 系统
-- 注：实际面板 JSON 需在 Y3 编辑器中创建并与此脚本配合使用
local GuildManager = require 'guild.quest_manager'
local QuestData    = require 'guild.quest_data'
local AdvData      = require 'guild.adventurer_data'
local Dispatch     = require 'guild.quest_dispatch'

local M = {}

-- UI 面板名称（与编辑器中的面板 ID 对应）
local PANEL_QUEST_BOARD  = "QuestBoardPanel"
local PANEL_DISPATCH     = "DispatchPanel"
local PANEL_SETTLEMENT   = "SettlementPanel"

-- 当前选择状态
local _current_quest_id    = nil
local _selected_adv_ids    = {}
local _selected_equip_ids  = {}

--- 显示任务公告板（列出已发布任务和报名池）
function M.show_quest_board()
    y3.player.with_local(function(player)
        local board = y3.ui.get_ui(player, PANEL_QUEST_BOARD)
        if not board then
            log.error("[GuildUI] QuestBoardPanel 未找到")
            return
        end
        -- 更新任务列表（框架占位：实际需绑定列表组件）
        local posted = QuestData.get_by_status(QuestData.STATUS.POSTED)
        log.info("[GuildUI] 公告板刷新，当前挂牌任务数: " .. #posted)
        board:set_visible(true)
    end)
end

--- 显示派遣选人面板
---@param quest_id string
function M.show_dispatch_panel(quest_id)
    _current_quest_id = quest_id
    _selected_adv_ids = {}
    _selected_equip_ids = {}

    y3.player.with_local(function(player)
        local panel = y3.ui.get_ui(player, PANEL_DISPATCH)
        if not panel then
            log.error("[GuildUI] DispatchPanel 未找到")
            return
        end

        local quest = QuestData.get(quest_id)
        if not quest then return end

        -- 显示任务信息（占位）
        local title_widget = y3.ui.get_ui(player, PANEL_DISPATCH .. ".quest_title")
        if title_widget then
            title_widget:set_text(quest.title)
        end

        -- 显示失败概率（占位）
        local pool = quest.registered_ids or {}
        local prob = Dispatch.calc_final_fail_prob(quest.rank, pool, 0)
        log.info("[GuildUI] 派遣面板 - 失败概率: heavy=" .. (prob.heavy * 100) .. "% wipe=" .. (prob.wipe * 100) .. "%")

        -- 绑定确认派遣按钮
        local confirm_btn = y3.ui.get_ui(player, PANEL_DISPATCH .. ".confirm_btn")
        if confirm_btn then
            confirm_btn:add_fast_event('左键-按下', function()
                if #_selected_adv_ids == 0 then
                    log.info("[GuildUI] 请先选择至少一名冒险者")
                    return
                end
                -- 使用固定目标点（实际应由地图触发器提供）
                local target = {x = 0, z = 0}
                GuildManager.dispatch_quest(_current_quest_id, _selected_adv_ids, _selected_equip_ids, target)
                panel:set_visible(false)
            end)
        end

        panel:set_visible(true)
    end)
end

--- 显示结算面板
---@param result SettlementResult
function M.show_settlement(result)
    y3.player.with_local(function(player)
        local panel = y3.ui.get_ui(player, PANEL_SETTLEMENT)
        if not panel then
            log.error("[GuildUI] SettlementPanel 未找到")
            return
        end

        -- 结算信息（占位显示）
        local outcome_widget = y3.ui.get_ui(player, PANEL_SETTLEMENT .. ".outcome_label")
        if outcome_widget then
            local status_text = result.outcome == "success" and "✅ 成功" or "❌ " .. result.outcome
            outcome_widget:set_text(status_text)
        end

        local reward_widget = y3.ui.get_ui(player, PANEL_SETTLEMENT .. ".reward_label")
        if reward_widget then
            reward_widget:set_text("奖励: +" .. result.gold_reward .. " 金币")
        end

        -- 确认关闭按钮
        local ok_btn = y3.ui.get_ui(player, PANEL_SETTLEMENT .. ".ok_btn")
        if ok_btn then
            ok_btn:add_fast_event('左键-按下', function()
                panel:set_visible(false)
            end)
        end

        panel:set_visible(true)
        log.info("[GuildUI] 结算面板已显示: " .. result.outcome)
    end)
end

--- 初始化 UI 系统（在游戏-初始化后调用）
function M.init()
    log.info("[GuildUI] UI 系统已初始化")
end

return M
