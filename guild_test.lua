-- guild_test.lua
-- 调试快捷键绑定 & 单元测试入口
local AdvData = require 'guild.adventurer_data'
local QuestData = require 'guild.quest_data'
local QuestBoard = require 'guild.quest_board'
local Dispatch = require 'guild.quest_dispatch'
local Execution = require 'guild.quest_execution'
local Settlement = require 'guild.quest_settlement'
local EventCards = require 'guild.event_cards'

local function assert_eq(label, a, b)
    if a ~= b then
        log.error("[TEST FAIL] " .. label .. " expected=" .. tostring(b) .. " got=" .. tostring(a))
    else
        log.info("[TEST PASS] " .. label)
    end
end

local function run_adventurer_tests()
    log.info("=== Task 1: Adventurer Data Tests ===")

    -- 1. 创建冒险者
    local adv = AdvData.create("Aria", "ranger", "F")
    assert_eq("create.rank", adv.rank, 1)
    assert_eq("create.loyalty", adv.loyalty, 60)
    assert_eq("create.xp", adv.xp, 0)

    -- 2. 忠诚度变更与钳制
    AdvData.change_loyalty(adv.id, 50)
    assert_eq("loyalty+50 clamped", AdvData.get(adv.id).loyalty, 100)
    AdvData.change_loyalty(adv.id, -200)
    assert_eq("loyalty-200 clamped", AdvData.get(adv.id).loyalty, 0)

    -- 3. 动摇判断
    AdvData.change_loyalty(adv.id, 15) -- loyalty=15
    assert_eq("wavering at 15", AdvData.is_wavering(adv.id), true)
    AdvData.change_loyalty(adv.id, 10) -- loyalty=25
    assert_eq("not wavering at 25", AdvData.is_wavering(adv.id), false)

    -- 4. 经验升级 (F→E 需300)
    local ranked_up = AdvData.add_xp(adv.id, 300)
    assert_eq("rank_up to E", ranked_up, true)
    assert_eq("rank after up", AdvData.get(adv.id).rank, 2)

    -- 5. 经验倍率
    assert_eq("xp_mult same rank", AdvData.xp_multiplier(3, 3), 1.0)
    assert_eq("xp_mult -1 rank",   AdvData.xp_multiplier(2, 3), 0.5)
    assert_eq("xp_mult -3 rank",   AdvData.xp_multiplier(1, 4), 0.1)

    log.info("=== Task 1 Tests Done ===")
end

local function run_quest_data_tests()
    log.info("=== Task 2: Quest Data Tests ===")

    local q = QuestData.create("讨伐哥布林", 2, QuestData.TYPE.HUNT, 3)
    assert_eq("quest.rank", q.rank, 2)
    assert_eq("quest.status", q.status, QuestData.STATUS.PENDING)
    assert_eq("quest.reward_base E", q.reward_base, 150)

    -- 发布任务
    QuestData.post(q.id, 1.25)
    local q2 = QuestData.get(q.id)
    assert_eq("post status", q2.status, QuestData.STATUS.POSTED)
    assert_eq("total_reward 1.25x E", QuestData.total_reward(q.id), 187) -- floor(150*1.25)

    -- 无效倍率不生效（0.9 不在有效集合中）
    local q3 = QuestData.create("测试任务", 1, QuestData.TYPE.STRATEGIC, nil)
    QuestData.post(q3.id, 0.9)
    assert_eq("invalid mult rejected", QuestData.get(q3.id).status, QuestData.STATUS.PENDING)

    -- get_by_status
    local posted_list = QuestData.get_by_status(QuestData.STATUS.POSTED)
    local found = false
    for _, pq in ipairs(posted_list) do
        if pq.id == q.id then found = true end
    end
    assert_eq("get_by_status POSTED", found, true)

    log.info("=== Task 2 Tests Done ===")
end

local function run_quest_board_tests()
    log.info("=== Task 3: Quest Board Tests ===")
    AdvData.reset()  -- 清除前面测试创建的冒险者，避免状态污染

    -- 准备：3个冒险者
    local adv_high     = AdvData.create("Alice",  "warrior", "C")  -- rank=4, loyalty=60
    local adv_low      = AdvData.create("Bob",    "mage",    "D")  -- rank=3, loyalty=60
    local adv_wavering = AdvData.create("Carol",  "ranger",  "B")  -- rank=5, loyalty=60
    AdvData.change_loyalty(adv_wavering.id, -45)                    -- loyalty→15（动摇）

    -- 任务：D级(3)，倍率1.0
    local q = QuestData.create("D级讨伐", 3, QuestData.TYPE.HUNT, nil)
    QuestData.post(q.id, 1.0)

    local pool = QuestBoard.collect_registrations(q.id)
    -- Alice(C≥D, loyal=60, min=0.75, 1.0≥0.75) → 报名
    -- Bob  (D≥D, loyal=60, min=0.75, 1.0≥0.75) → 报名
    -- Carol(B≥D, loyal=15, min=1.5,  1.0<1.5)  → 不报名
    assert_eq("pool size at 1.0x", #pool, 2)

    -- 换成1.5x，Carol也报名
    q.bounty_mult = 1.5
    local pool2 = QuestBoard.collect_registrations(q.id)
    assert_eq("pool size at 1.5x (Carol joins)", #pool2, 3)

    -- F级冒险者不可接D级任务（等级不够）
    local adv_f = AdvData.create("Newbie", "warrior", "F")  -- rank=1
    q.bounty_mult = 1.5
    local pool3 = QuestBoard.collect_registrations(q.id)
    assert_eq("F-rank excluded from D quest", #pool3, 3)  -- Newbie 仍不在

    -- 在任务中的冒险者不报名
    adv_high.is_on_quest = true
    local pool4 = QuestBoard.collect_registrations(q.id)
    assert_eq("on-quest adv excluded", #pool4, 2)
    adv_high.is_on_quest = false  -- 恢复

    log.info("=== Task 3 Tests Done ===")
end

local function run_dispatch_tests()
    log.info("=== Task 4: Dispatch Tests ===")
    AdvData.reset()

    -- 平均等级计算
    local a1 = AdvData.create("D1", "warrior", "D")  -- rank=3
    local a2 = AdvData.create("B1", "mage",    "B")  -- rank=5
    local a3 = AdvData.create("C1", "ranger",  "C")  -- rank=4
    -- 平均 = (3+5+4)/3 = 4.0 → round → 4 (C)
    local avg = Dispatch.calc_party_avg_rank({a1.id, a2.id, a3.id})
    assert_eq("party avg {D,B,C}=C", avg, 4)

    -- 基础失败概率
    local p1 = Dispatch.calc_base_fail_prob(3, 3)  -- diff=0
    assert_eq("base_fail diff=0 heavy", p1.heavy, 0.10)
    assert_eq("base_fail diff=0 wipe",  p1.wipe,  0.01)

    local p2 = Dispatch.calc_base_fail_prob(5, 3)  -- diff=2
    assert_eq("base_fail diff=2 heavy", p2.heavy, 0.50)

    local p3 = Dispatch.calc_base_fail_prob(6, 3)  -- diff>=3
    assert_eq("base_fail diff=3 heavy", p3.heavy, 0.80)

    -- 装备修正
    assert_eq("equip_delta +1 tier", Dispatch.calc_equip_delta(4, 3), -0.10)
    assert_eq("equip_delta same",    Dispatch.calc_equip_delta(3, 3),  0.00)
    assert_eq("equip_delta -1 tier", Dispatch.calc_equip_delta(2, 3),  0.05)
    assert_eq("equip_delta -2 tier", Dispatch.calc_equip_delta(1, 3),  0.15)

    -- 最终概率（钳制到0.95）
    local p4 = Dispatch.calc_final_fail_prob(6, {a1.id}, 0)
    -- diff=6-3=3→heavy=0.80, equip_delta(0,6)=0.15, final=0.95
    assert_eq("final prob clamped to 0.95", p4.heavy, 0.95)

    -- 派遣流程
    local q = QuestData.create("测试派遣", 3, QuestData.TYPE.HUNT, nil)
    QuestData.post(q.id, 1.0)
    -- 手动设置报名池
    q.registered_ids = {a1.id, a2.id}

    local ok = Dispatch.dispatch(q.id, {a1.id}, {})
    assert_eq("dispatch success", ok, true)
    assert_eq("quest status dispatched", q.status, QuestData.STATUS.DISPATCHED)
    assert_eq("adv on quest", AdvData.get(a1.id).is_on_quest, true)

    -- 不在报名池中的冒险者不可派遣
    local q2 = QuestData.create("第二个任务", 2, QuestData.TYPE.EXPLORE, nil)
    QuestData.post(q2.id, 1.0)
    q2.registered_ids = {a2.id}
    local ok2 = Dispatch.dispatch(q2.id, {a3.id}, {})  -- a3 不在报名池
    assert_eq("dispatch fails for non-pool member", ok2, false)

    log.info("=== Task 4 Tests Done ===")
end

local function run_execution_tests()
    log.info("=== Task 5: Execution Tests ===")
    -- 执行模块主要依赖游戏运行时（单位创建、事件监听），此处只记录手动验证项
    log.info("[MANUAL] Task 5: 需要在游戏中验证以下行为：")
    log.info("  - 派遣后，冒险者单位出现在地图上并向目标移动")
    log.info("  - 按 R 键召回，单位消失，任务以 abort 结算")
    log.info("  - 单位全部死亡时，触发 wipe 结算")
    log.info("=== Task 5 Tests Done ===")
end

local function run_settlement_tests()
    log.info("=== Task 6: Settlement Tests ===")
    AdvData.reset()

    -- 测试1: 成功结算
    local adv1 = AdvData.create("Hero", "warrior", "D")  -- rank=3
    local q1 = QuestData.create("成功测试", 3, QuestData.TYPE.HUNT, nil)
    QuestData.post(q1.id, 1.25)  -- reward_base=400, mult=1.25 → total=500
    q1.dispatched_ids = {adv1.id}
    q1.equipment_ids  = {}
    adv1.is_on_quest = true

    local r1 = Settlement.settle(q1.id, "success")
    assert_eq("success gold", r1.gold_reward, 500)  -- floor(400*1.25)=500
    assert_eq("success no lost adv", #r1.lost_adv_ids, 0)
    assert_eq("success loyalty gain", r1.loyalty_changes[adv1.id], 10)
    assert_eq("success adv freed", AdvData.get(adv1.id).is_on_quest, false)
    assert_eq("success status", q1.status, QuestData.STATUS.SUCCEEDED)

    -- 测试2: 专属奖励（任务类型匹配专长）
    local adv_spec = AdvData.create("Specialist", "ranger", "D")
    adv_spec.specialties = {"hunt"}  -- 专长讨伐
    local q_spec = QuestData.create("专长测试", 3, QuestData.TYPE.HUNT, nil)
    QuestData.post(q_spec.id, 1.0)  -- mult=1.0 → loyalty+5
    q_spec.dispatched_ids = {adv_spec.id}
    q_spec.equipment_ids = {}
    adv_spec.is_on_quest = true

    local r_spec = Settlement.settle(q_spec.id, "success")
    -- loyalty: 1.0x → +5, specialty → +5 = total +10
    assert_eq("specialty bonus total", r_spec.loyalty_changes[adv_spec.id], 10)

    -- 测试3: 全灭结算
    local adv2 = AdvData.create("Martyr", "ranger", "C")
    local bystander = AdvData.create("Watcher", "warrior", "F")
    local q2 = QuestData.create("全灭测试", 3, QuestData.TYPE.HUNT, nil)
    QuestData.post(q2.id, 1.0)
    q2.dispatched_ids = {adv2.id}
    q2.equipment_ids  = {"eq_001"}
    adv2.is_on_quest = true

    local r2 = Settlement.settle(q2.id, "wipe")
    assert_eq("wipe adv lost count", #r2.lost_adv_ids, 1)
    assert_eq("wipe equip lost count", #r2.lost_equip_ids, 1)
    assert_eq("wipe adv removed", AdvData.get(adv2.id), nil)
    assert_eq("wipe bystander morale -20", r2.loyalty_changes[bystander.id], -20)

    log.info("=== Task 6 Tests Done ===")
end

local function run_event_card_tests()
    log.info("=== Task 8: Event Card Tests ===")

    -- draw_cards 返回空池的任务类型（如 strategic）
    local cards_none = EventCards.draw_cards("strategic")
    assert_eq("no cards for unknown type", #cards_none, 0)

    -- draw_cards 对 hunt 类型返回 0~2 张
    local cards_hunt = EventCards.draw_cards("hunt")
    local ok_range = (cards_hunt ~= nil and #cards_hunt >= 0 and #cards_hunt <= 2)
    assert_eq("hunt cards in range [0,2]", ok_range, true)

    -- draw_cards 不重复（抽2张时两张不同）
    -- 多次采样验证无重复（hunt 有2张卡，抽2张时必须各不同）
    local seen_duplicates = false
    for _ = 1, 20 do
        local sample = EventCards.draw_cards("hunt")
        if #sample == 2 and sample[1].id == sample[2].id then
            seen_duplicates = true
            break
        end
    end
    assert_eq("no duplicate cards in draw", seen_duplicates, false)

    -- 卡牌结构完整性
    local explore_cards = EventCards.draw_cards("explore")
    if #explore_cards > 0 then
        local card = explore_cards[1]
        assert_eq("card has id", type(card.id) == "string", true)
        assert_eq("card has text", type(card.text) == "string", true)
        assert_eq("card has options", type(card.options) == "table", true)
    end

    log.info("=== Task 8 Tests Done ===")
end

-- 绑定快捷键 T = 运行测试
y3.game:event('游戏-初始化', function()
    y3.player.with_local(function(p)
        -- 按 T 键触发测试
        y3.game:event('按键-按下', function(_, key)
            if key == 'T' then
                run_adventurer_tests()
                run_quest_data_tests()
                run_quest_board_tests()
                run_dispatch_tests()
                run_execution_tests()
                run_settlement_tests()
                run_event_card_tests()
                log.info("=== All Guild System Tests Complete ===")
                log.info("[MANUAL] 在游戏中验证:")
                log.info("  1. 游戏启动 → 日志: [Guild] 冒险者公会任务系统已初始化")
                log.info("  2. 调用 GuildManager.post_quest(...) 发布任务")
                log.info("  3. 调用 GuildManager.dispatch_quest(...) 派遣")
                log.info("  4. 按 R 键召回 → 结算日志出现")
            end
            if key == 'R' then
                -- 召回第一个 DISPATCHED 任务（调试用）
                local dispatched = QuestData.get_by_status(QuestData.STATUS.DISPATCHED)
                if dispatched[1] then
                    Execution.recall(dispatched[1].id)
                    log.info("[DEBUG] 召回任务: " .. dispatched[1].id)
                end
            end
        end)
    end)
end)
