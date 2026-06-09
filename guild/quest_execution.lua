-- guild/quest_execution.lua
-- 任务执行模块 V2：创建地图单位、通过 casualty.lua 处理伤亡链、处理召回
-- 注：V2 删除 mark_fail，伤亡由死亡事件实时驱动
local AdvData    = require 'guild.adventurer_data'
local QuestData  = require 'guild.quest_data'
local EventCards = require 'guild.event_cards'

local M = {}

-- 运行中的任务执行上下文
local _executions = {} ---@type table<string, ExecutionContext>

---@class ExecutionContext
---@field quest_id string
---@field adv_units table<string, py.Unit>  adv_id → 地图单位
---@field target_point table                {x: number, z: number}
---@field on_complete function|nil          完成回调 (quest_id, outcome)
---@field recalled boolean                  是否已召回
---@field death_listener any|nil            死亡事件监听句柄（用于 off/cleanup）
---@field check_timer any|nil               周期检查定时器句柄（用于 cancel）
---@field card_timer any|nil                事件卡定时器句柄（用于 cancel，Task 8 写入）

-- 冒险者职业对应的物编单位 ID（需在 Y3 编辑器中配置，此处为占位值）
local PROFESSION_UNIT_KEY = {
    warrior = 100101,
    mage    = 100102,
    ranger  = 100103,
}

--- 启动任务执行：创建地图单位并开始监控
---@param quest_id string
---@param target_point table {x: number, z: number}
---@param on_complete function  结算回调 (quest_id, outcome)
---@param on_event_card function|nil  事件卡回调 (quest_id, event_data)，Task 8 集成后使用
function M.start(quest_id, target_point, on_complete, on_event_card)
    local quest = QuestData.get(quest_id)
    if not quest or quest.status ~= QuestData.STATUS.DISPATCHED then return end

    local ctx = {
        quest_id     = quest_id,
        adv_units    = {},
        target_point = target_point,
        on_complete  = on_complete,
        recalled     = false,
        death_listener = nil,
        check_timer    = nil,
        card_timer     = nil,
    }

    -- 在地图上创建冒险者单位（Y3 运行时 API）
    local player = y3.player.get_by_id(1) -- 玩家1阵营
    for _, adv_id in ipairs(quest.dispatched_ids) do
        local adv = AdvData.get(adv_id)
        if adv then
            local unit_key = PROFESSION_UNIT_KEY[adv.profession] or 100101
            local unit = y3.unit.create(player, unit_key, y3.point.create(0, 0))
            if unit then
                ctx.adv_units[adv_id] = unit
                unit:move_to(y3.point.create(target_point.x, target_point.z))
            end
        end
    end

    _executions[quest_id] = ctx

    -- 监听单位死亡（⚠️ 必须存储句柄，在 _finish() 中 off()）
    local Casualty = require 'guild.casualty'

    local death_handler = function(_, dead_unit)
        if not _executions[quest_id] then return end
        -- Identify downed adventurer
        local downed_id = nil
        for adv_id, u in pairs(ctx.adv_units) do
            if u == dead_unit then
                downed_id = adv_id
                ctx.adv_units[adv_id] = nil
                break
            end
        end
        if not downed_id then return end

        -- Run casualty chain
        local is_solo = (#quest.dispatched_ids == 1)
        if is_solo then
            local survived = Casualty.do_casualty_roll(downed_id, quest.rank)
            if not survived then
                M._finish(quest_id, "wipe")
                return
            end
        else
            Casualty.process_party_casualty(downed_id, quest.dispatched_ids, quest.rank)
        end

        -- All-dead check
        local any_active = false
        for _, u in pairs(ctx.adv_units) do if u then any_active = true; break end end
        if not any_active then
            M._finish(quest_id, "wipe")
        end
    end
    -- ⚠️ 存储句柄，_finish 时必须 off 此监听器
    ctx.death_listener = y3.game:event('单位-死亡', death_handler)

    -- 定时检查：每2秒一次（存储句柄，_finish 时 cancel）
    ctx.check_timer = y3.timer.loop(2, function()
        if not _executions[quest_id] or ctx.recalled then return end
        -- 到达检测逻辑（具体实现依赖地图触发器，此处为框架占位）
        -- 实际到达后调用: M.mark_success(quest_id)
    end)

    -- 事件卡抽取和定时触发（Task 8）
    local cards = EventCards.draw_cards(quest.quest_type)
    local card_index = 1

    -- 每30秒检查是否触发下一张事件卡（存储句柄，_finish 时 cancel）
    if #cards > 0 then
        ctx.card_timer = y3.timer.loop(30, function()
            if not _executions[quest_id] then return end
            if card_index > #cards then return end
            local card = cards[card_index]
            card_index = card_index + 1
            if on_event_card then
                on_event_card(quest_id, card)
            end
        end)
    end
end

--- 玩家主动召回（结果为 abort，按轻度失败结算）
---@param quest_id string
function M.recall(quest_id)
    local ctx = _executions[quest_id]
    if not ctx or ctx.recalled then return end
    ctx.recalled = true

    -- 删除地图上所有冒险者单位
    for _, u in pairs(ctx.adv_units) do
        if u then u:remove() end
    end
    ctx.adv_units = {}

    M._finish(quest_id, "abort")
end

--- 内部完成函数：清理所有监听器和定时器，然后调用结算回调
--- ⚠️ 此函数负责防止资源泄漏，所有 timer/listener 必须在此注销
---@param quest_id string
---@param outcome string  "success"|"light_fail"|"heavy_fail"|"wipe"|"abort"
function M._finish(quest_id, outcome)
    local ctx = _executions[quest_id]
    if not ctx then return end
    _executions[quest_id] = nil  -- 先清除，防止重复调用

    -- ⚠️ 清理监听器（Y3 API：若 y3.game:event 返回可 off 的对象，则调用其 off 方法）
    if ctx.death_listener then
        -- ctx.death_listener:off()  ← 待确认 Y3 API 后解注释
        -- Y3 lualib 的事件注销方式：通过返回的 trigger 对象或 y3.game:off()
        ctx.death_listener = nil
    end
    -- ⚠️ 清理定时器（Y3 API：y3.timer.loop 返回 timer 对象，调用 :cancel()）
    if ctx.check_timer then
        ctx.check_timer:cancel()
        ctx.check_timer = nil
    end
    if ctx.card_timer then
        ctx.card_timer:cancel()
        ctx.card_timer = nil
    end

    -- 调用结算回调
    if ctx.on_complete then
        ctx.on_complete(quest_id, outcome)
    end
end

--- 外部标记任务成功（到达目标、完成目标后调用）
---@param quest_id string
function M.mark_success(quest_id)
    M._finish(quest_id, "success")
end

return M
