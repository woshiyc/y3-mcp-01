-- guild_test.lua
-- 调试快捷键绑定 & 单元测试入口
local AdvData = require 'guild.adventurer_data'
local QuestData = require 'guild.quest_data'
local QuestBoard = require 'guild.quest_board'
local Dispatch = require 'guild.quest_dispatch'
local Execution = require 'guild.quest_execution'
local Settlement = require 'guild.quest_settlement'
local EventCards = require 'guild.event_cards'
local TraitSystem = require 'guild.trait_system'
local Casualty = require 'guild.casualty'

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
    assert_eq("create.xp", adv.xp, 0)

    -- 2. 经验升级 (F→E 需300)
    local ranked_up = AdvData.add_xp(adv.id, 300)
    assert_eq("rank_up to E", ranked_up, true)
    assert_eq("rank after up", AdvData.get(adv.id).rank, 2)

    -- 3. 经验倍率
    assert_eq("xp_mult same rank", AdvData.xp_multiplier(3, 3), 1.0)
    assert_eq("xp_mult -1 rank",   AdvData.xp_multiplier(2, 3), 0.5)
    assert_eq("xp_mult -3 rank",   AdvData.xp_multiplier(1, 4), 0.1)

    -- V2 field tests
    local adv_v2 = AdvData.create("V2Test", "mage", "C")
    assert_eq("v2: has traits list", type(adv_v2.traits) == "table", true)
    assert_eq("v2: traits empty", #adv_v2.traits, 0)
    assert_eq("v2: resting_days=0", adv_v2.resting_days, 0)
    assert_eq("v2: vacation_days=0", adv_v2.vacation_days, 0)
    assert_eq("v2: heartbroken_days_left=0", adv_v2.heartbroken_days_left, 0)
    assert_eq("v2: no loyalty field", adv_v2.loyalty, nil)

    -- tick_daily: resting decrements
    adv_v2.resting_days = 3
    AdvData.tick_daily()
    assert_eq("v2: resting_days decrements", AdvData.get(adv_v2.id).resting_days, 2)

    -- tick_daily: vacation decrements (only when not resting)
    adv_v2.resting_days = 0
    adv_v2.vacation_days = 2
    AdvData.tick_daily()
    assert_eq("v2: vacation_days decrements", AdvData.get(adv_v2.id).vacation_days, 1)

    -- is_available
    adv_v2.resting_days = 1
    adv_v2.vacation_days = 0
    assert_eq("v2: not available while resting", AdvData.is_available(adv_v2.id), false)
    adv_v2.resting_days = 0
    adv_v2.vacation_days = 1
    assert_eq("v2: not available on vacation", AdvData.is_available(adv_v2.id), false)
    adv_v2.vacation_days = 0
    adv_v2.is_on_quest = false
    assert_eq("v2: available when free", AdvData.is_available(adv_v2.id), true)

    -- tick_daily: heartbroken_days_left decrements
    local adv_hb = AdvData.create("HBTest", "warrior", "C")
    adv_hb.heartbroken_days_left = 2
    AdvData.tick_daily()
    assert_eq("v2: heartbroken_days_left decrements", AdvData.get(adv_hb.id).heartbroken_days_left, 1)

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
    log.info("=== Quest Board V2 Tests ===")
    AdvData.reset()
    QuestData.reset()
    QuestBoard.set_difficulty(2)  -- 普通: tolerance=3

    -- S-rank on normal: min=7-3=4(C), should accept C task
    local adv_s = AdvData.create("SRank", "warrior", "S")
    local q_c = QuestData.create("C任务", 4, QuestData.TYPE.HUNT, nil)
    QuestData.post(q_c.id, 1.0)
    local pool = QuestBoard.collect_registrations(q_c.id)
    local found = false; for _, id in ipairs(pool) do if id == adv_s.id then found = true end end
    assert_eq("S accepts C on normal", found, true)

    -- S-rank on hell (tolerance=0): only S task
    QuestBoard.set_difficulty(5)
    pool = QuestBoard.collect_registrations(q_c.id)
    found = false; for _, id in ipairs(pool) do if id == adv_s.id then found = true end end
    assert_eq("S rejects C on hell", found, false)

    -- F-rank can accept S task (no upper limit)
    QuestBoard.set_difficulty(2)
    AdvData.reset(); QuestData.reset()
    local adv_f = AdvData.create("FRank", "ranger", "F")
    local q_s = QuestData.create("S任务", 7, QuestData.TYPE.HUNT, nil)
    QuestData.post(q_s.id, 1.0)
    pool = QuestBoard.collect_registrations(q_s.id)
    found = false; for _, id in ipairs(pool) do if id == adv_f.id then found = true end end
    assert_eq("F accepts S (no upper cap)", found, true)

    -- cowardly: C-rank cannot accept S task
    AdvData.reset(); QuestData.reset()
    local adv_c = AdvData.create("Coward", "mage", "C")
    TraitSystem.add_trait(adv_c.id, "cowardly")
    local q_s2 = QuestData.create("S任务2", 7, QuestData.TYPE.HUNT, nil)
    QuestData.post(q_s2.id, 1.0)
    pool = QuestBoard.collect_registrations(q_s2.id)
    found = false; for _, id in ipairs(pool) do if id == adv_c.id then found = true end end
    assert_eq("cowardly C rejects S", found, false)

    -- traumatized rejects hunt
    AdvData.reset(); QuestData.reset()
    local adv_t = AdvData.create("Trauma", "warrior", "S")
    TraitSystem.add_trait(adv_t.id, "traumatized")
    local q_hunt = QuestData.create("讨伐", 5, QuestData.TYPE.HUNT, nil)
    QuestData.post(q_hunt.id, 1.0)
    pool = QuestBoard.collect_registrations(q_hunt.id)
    found = false; for _, id in ipairs(pool) do if id == adv_t.id then found = true end end
    assert_eq("traumatized rejects hunt", found, false)

    -- resting adventurer cannot register
    AdvData.reset(); QuestData.reset()
    local adv_r = AdvData.create("Resting", "warrior", "C")
    adv_r.resting_days = 2
    local q_e = QuestData.create("探索", 3, QuestData.TYPE.EXPLORE, nil)
    QuestData.post(q_e.id, 1.0)
    pool = QuestBoard.collect_registrations(q_e.id)
    found = false; for _, id in ipairs(pool) do if id == adv_r.id then found = true end end
    assert_eq("resting cannot register", found, false)

    -- Bounty weight: hunt_specialist gets higher pool priority for hunt quest
    AdvData.reset(); QuestData.reset()
    local adv_spec = AdvData.create("Spec", "warrior", "S")
    TraitSystem.add_trait(adv_spec.id, "hunt_specialist")
    local adv_norm = AdvData.create("Norm", "warrior", "S")
    local q_h = QuestData.create("高赏金讨伐", 5, QuestData.TYPE.HUNT, nil)
    QuestData.post(q_h.id, 1.5)
    pool = QuestBoard.collect_registrations(q_h.id)
    local spec_pos, norm_pos = nil, nil
    for i, id in ipairs(pool) do
        if id == adv_spec.id then spec_pos = i end
        if id == adv_norm.id then norm_pos = i end
    end
    assert_eq("hunt_specialist ranked higher", spec_pos ~= nil and norm_pos ~= nil and spec_pos < norm_pos, true)

    log.info("=== Quest Board V2 Tests Done ===")
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

    -- V2: probability functions must not exist
    assert_eq("calc_base_fail_prob removed", Dispatch.calc_base_fail_prob, nil)
    assert_eq("calc_equip_delta removed", Dispatch.calc_equip_delta, nil)
    assert_eq("calc_final_fail_prob removed", Dispatch.calc_final_fail_prob, nil)
    -- Core functions still exist
    assert_eq("dispatch still exists", type(Dispatch.dispatch) == "function", true)
    assert_eq("calc_party_avg_rank still exists", type(Dispatch.calc_party_avg_rank) == "function", true)
    log.info("=== Task 4 Tests Done ===")
end

local function run_execution_tests()
    log.info("=== Task 5: Execution Tests ===")
    -- 执行模块主要依赖游戏运行时（单位创建、事件监听），此处只记录手动验证项
    log.info("[MANUAL] Task 5: 需要在游戏中验证以下行为：")
    log.info("  - 派遣后，冒险者单位出现在地图上并向目标移动")
    log.info("  - 按 R 键召回，单位消失，任务以 abort 结算")
    log.info("  - 单位全部死亡时，触发 wipe 结算")
    -- V2 API checks
    assert_eq("mark_success exists", type(Execution.mark_success) == "function", true)
    assert_eq("recall exists", type(Execution.recall) == "function", true)
    assert_eq("mark_fail removed in V2", Execution.mark_fail, nil)
    log.info("=== Task 5 Tests Done ===")
end

local function run_settlement_tests()
    log.info("=== Settlement V2 Tests ===")
    AdvData.reset(); QuestData.reset()

    -- Test 1: success — gold rewarded, xp added, adv freed, no lost_adv_ids
    local adv1 = AdvData.create("Hero", "warrior", "C")
    adv1.is_on_quest = true
    local q1 = QuestData.create("成功任务", 3, QuestData.TYPE.HUNT, nil)
    QuestData.post(q1.id, 1.0)
    q1.dispatched_ids = {adv1.id}; q1.equipment_ids = {}
    QuestData.set_status(q1.id, QuestData.STATUS.DISPATCHED)

    local r1 = Settlement.settle(q1.id, "success")
    assert_eq("success: outcome", r1.outcome, "success")
    assert_eq("success: gold > 0", r1.gold_reward > 0, true)
    assert_eq("success: adv freed", AdvData.get(adv1.id).is_on_quest, false)
    assert_eq("success: xp added", AdvData.get(adv1.id).xp > 0, true)
    assert_eq("success: no losses", #r1.lost_adv_ids, 0)
    assert_eq("success: no loyalty_changes", r1.loyalty_changes, nil)

    -- Test 2: abort — no gold, adv freed
    AdvData.reset(); QuestData.reset()
    local adv2 = AdvData.create("Quitter", "ranger", "B")
    adv2.is_on_quest = true
    local q2 = QuestData.create("放弃任务", 4, QuestData.TYPE.EXPLORE, nil)
    QuestData.post(q2.id, 1.0)
    q2.dispatched_ids = {adv2.id}; q2.equipment_ids = {}
    QuestData.set_status(q2.id, QuestData.STATUS.DISPATCHED)

    local r2 = Settlement.settle(q2.id, "abort")
    assert_eq("abort: outcome", r2.outcome, "abort")
    assert_eq("abort: no gold", r2.gold_reward, 0)
    assert_eq("abort: adv freed", AdvData.get(adv2.id).is_on_quest, false)
    assert_eq("abort: no lost_adv_ids", #r2.lost_adv_ids, 0)
    assert_eq("abort: status=ABORTED", QuestData.get(q2.id).status, QuestData.STATUS.ABORTED)

    -- Test 3: wipe — all dispatched permanently removed, equip lost, bystander untouched
    AdvData.reset(); QuestData.reset()
    local adv3a = AdvData.create("Martyr1", "warrior", "C")
    local adv3b = AdvData.create("Martyr2", "mage", "C")
    local bystander = AdvData.create("Watcher", "ranger", "F")
    adv3a.is_on_quest = true; adv3b.is_on_quest = true
    local q3 = QuestData.create("全灭任务", 5, QuestData.TYPE.HUNT, nil)
    QuestData.post(q3.id, 1.0)
    q3.dispatched_ids = {adv3a.id, adv3b.id}; q3.equipment_ids = {"eq_001"}
    QuestData.set_status(q3.id, QuestData.STATUS.DISPATCHED)

    local r3 = Settlement.settle(q3.id, "wipe")
    assert_eq("wipe: 2 lost", #r3.lost_adv_ids, 2)
    assert_eq("wipe: equip lost", #r3.lost_equip_ids, 1)
    assert_eq("wipe: martyr1 removed", AdvData.get(adv3a.id), nil)
    assert_eq("wipe: martyr2 removed", AdvData.get(adv3b.id), nil)
    assert_eq("wipe: bystander alive", AdvData.get(bystander.id) ~= nil, true)
    assert_eq("wipe: no loyalty_changes", r3.loyalty_changes, nil)

    log.info("=== Settlement V2 Tests Done ===")
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

local function run_trait_system_tests()
    log.info("=== TraitSystem Tests ===")

    -- 1. add_trait and has_trait
    AdvData.reset()
    local adv = AdvData.create("TraitTester", "warrior", "C")
    local ok = TraitSystem.add_trait(adv.id, "battle_veteran")
    assert_eq("add_trait returns true", ok, true)
    assert_eq("has_trait after add", TraitSystem.has_trait(adv.id, "battle_veteran"), true)

    -- 2. duplicate prevention
    local ok2 = TraitSystem.add_trait(adv.id, "battle_veteran")
    assert_eq("duplicate blocked", ok2, false)

    -- 3. cap=6, all non-removable → 7th blocked
    AdvData.reset()
    local adv2 = AdvData.create("CapTest", "mage", "B")
    for _, tid in ipairs({"battle_veteran","brave","near_death_survivor","inspiring","tenacious","guardian_instinct"}) do
        TraitSystem.add_trait(adv2.id, tid)
    end
    local ok3 = TraitSystem.add_trait(adv2.id, "explorer")
    assert_eq("blocked when all 6 non-removable", ok3, false)

    -- 4. cap=6 with removable traits → 7th evicts one removable
    AdvData.reset()
    local adv3 = AdvData.create("EvictTest", "ranger", "A")
    for _, tid in ipairs({"traumatized","cowardly","alcoholic","suspicious","fragile","heartbroken"}) do
        TraitSystem.add_trait(adv3.id, tid)
    end
    local adv3data = AdvData.get(adv3.id)
    assert_eq("6 traits before eviction", #adv3data.traits, 6)
    local ok4 = TraitSystem.add_trait(adv3.id, "proud")
    assert_eq("add succeeds with eviction", ok4, true)
    assert_eq("still 6 traits after eviction", #adv3data.traits, 6)

    -- 5. get_level_min_offset: proud(+1) + greedy(-1) = 0
    AdvData.reset()
    local adv4 = AdvData.create("OffsetTest", "warrior", "S")
    TraitSystem.add_trait(adv4.id, "proud")
    TraitSystem.add_trait(adv4.id, "greedy")
    assert_eq("net offset=0", TraitSystem.get_level_min_offset(adv4.id), 0)

    -- 6. get_max_rank_cap: cowardly caps at own rank
    AdvData.reset()
    local adv5 = AdvData.create("CowardTest", "ranger", "C")
    assert_eq("no cap without cowardly", TraitSystem.get_max_rank_cap(adv5.id), nil)
    TraitSystem.add_trait(adv5.id, "cowardly")
    assert_eq("cap=own rank with cowardly", TraitSystem.get_max_rank_cap(adv5.id), adv5.rank)

    -- 7. rejects_quest_type: traumatized rejects hunt
    AdvData.reset()
    local adv6 = AdvData.create("PhobiaTest", "mage", "D")
    TraitSystem.add_trait(adv6.id, "traumatized")
    assert_eq("traumatized rejects hunt", TraitSystem.rejects_quest_type(adv6.id, "hunt"), true)
    assert_eq("traumatized allows explore", TraitSystem.rejects_quest_type(adv6.id, "explore"), false)

    -- 7b. rejects_quest_type: heartbroken rejects all when days_left > 0
    AdvData.reset()
    local adv6b = AdvData.create("HeartbrokenTest", "mage", "C")
    TraitSystem.add_trait(adv6b.id, "heartbroken")
    -- heartbroken_days_left = 0 → should NOT reject
    assert_eq("heartbroken no days left: allows hunt", TraitSystem.rejects_quest_type(adv6b.id, "hunt"), false)
    -- heartbroken_days_left > 0 → should reject ALL quest types
    adv6b.heartbroken_days_left = 2
    assert_eq("heartbroken with days left: rejects hunt", TraitSystem.rejects_quest_type(adv6b.id, "hunt"), true)
    assert_eq("heartbroken with days left: rejects explore", TraitSystem.rejects_quest_type(adv6b.id, "explore"), true)

    -- 8. get_signup_weight: hunt_specialist gets bonus for hunt quest
    AdvData.reset()
    local adv7 = AdvData.create("SpecialistTest", "warrior", "B")
    local base_weight = TraitSystem.get_signup_weight(adv7.id, "hunt", 1.0)
    TraitSystem.add_trait(adv7.id, "hunt_specialist")
    local spec_weight = TraitSystem.get_signup_weight(adv7.id, "hunt", 1.0)
    assert_eq("hunt_specialist has higher hunt weight", spec_weight > base_weight, true)

    -- 9. trigger rolls return boolean
    AdvData.reset()
    local adv8 = AdvData.create("RollTest", "warrior", "F")
    assert_eq("neg roll returns bool", type(TraitSystem.trigger_negative_roll(adv8.id)) == "boolean", true)
    assert_eq("pos roll returns bool", type(TraitSystem.trigger_positive_roll(adv8.id)) == "boolean", true)

    -- 10. get_stat_value: _bonus key returns sum, other keys return 1.0+sum
    AdvData.reset()
    local adv9 = AdvData.create("StatTest", "warrior", "C")
    -- No traits: casualty_roll_bonus = 0.0, hp_mult = 1.0
    assert_eq("no traits: casualty_roll_bonus=0", TraitSystem.get_stat_value(adv9.id, "casualty_roll_bonus"), 0.0)
    assert_eq("no traits: hp_mult=1.0", TraitSystem.get_stat_value(adv9.id, "hp_mult"), 1.0)
    -- Add near_death_survivor: casualty_roll_bonus +0.10, hp_mult +0.15
    TraitSystem.add_trait(adv9.id, "near_death_survivor")
    assert_eq("near_death_survivor: casualty_roll_bonus=0.10", TraitSystem.get_stat_value(adv9.id, "casualty_roll_bonus"), 0.10)
    assert_eq("near_death_survivor: hp_mult=1.15", TraitSystem.get_stat_value(adv9.id, "hp_mult"), 1.15)

    -- 11. trigger_negative_roll_at_rate: 100% rate must add a trait if pool not empty
    AdvData.reset()
    local adv10 = AdvData.create("RateTest", "warrior", "F")
    local added = TraitSystem.trigger_negative_roll_at_rate(adv10.id, 1.0)  -- 100% guaranteed
    assert_eq("rate=1.0 guarantees add (pool not empty)", added, true)
    assert_eq("adv has 1 negative trait after 100% roll", #AdvData.get(adv10.id).traits, 1)
    -- 0% rate must never add
    local adv11 = AdvData.create("ZeroRateTest", "ranger", "F")
    local not_added = TraitSystem.trigger_negative_roll_at_rate(adv11.id, 0.0)
    assert_eq("rate=0.0 never adds", not_added, false)

    log.info("=== TraitSystem Tests Done ===")
end

local function run_casualty_tests()
    log.info("=== Casualty Tests ===")
    AdvData.reset()

    -- 1. enter_rest sets resting_days in [2, 4]
    local adv = AdvData.create("RestTest", "warrior", "C")
    Casualty.enter_rest(adv.id)
    local rd = AdvData.get(adv.id).resting_days
    assert_eq("resting_days >= 2", rd >= 2, true)
    assert_eq("resting_days <= 4", rd <= 4, true)
    assert_eq("is_on_quest cleared", AdvData.get(adv.id).is_on_quest, false)

    -- 2. trigger_vacation_check sets vacation_days 0 or 1-2
    AdvData.reset()
    local adv2 = AdvData.create("VacTest", "ranger", "B")
    Casualty.trigger_vacation_check(adv2.id)
    local vd = AdvData.get(adv2.id).vacation_days
    assert_eq("vacation_days in [0,2]", vd >= 0 and vd <= 2, true)

    -- 3. do_casualty_roll returns boolean
    AdvData.reset()
    local adv3 = AdvData.create("CasTest", "warrior", "C")
    local survived = Casualty.do_casualty_roll(adv3.id, 4)
    assert_eq("casualty_roll returns bool", type(survived) == "boolean", true)

    -- 4. do_first_aid_roll returns boolean
    AdvData.reset()
    local cleric  = AdvData.create("Cleric", "priest", "C")
    local patient = AdvData.create("Patient", "warrior", "C")
    local aid_ok = Casualty.do_first_aid_roll(cleric.id, patient.id, 3)
    assert_eq("first_aid_roll returns bool", type(aid_ok) == "boolean", true)

    -- 5. process_party_casualty: no priest → direct casualty roll
    AdvData.reset()
    local warrior1 = AdvData.create("W1", "warrior", "C")
    local warrior2 = AdvData.create("W2", "warrior", "C")
    warrior1.is_on_quest = true
    warrior2.is_on_quest = true
    local result = Casualty.process_party_casualty(warrior1.id, {warrior1.id, warrior2.id}, 3)
    assert_eq("party_casualty (no priest) returns bool", type(result) == "boolean", true)

    -- 6. process_party_casualty: has priest → first-aid path
    AdvData.reset()
    local priest  = AdvData.create("Priest", "priest", "C")
    local patient2= AdvData.create("P2", "warrior", "C")
    priest.is_on_quest  = true
    patient2.is_on_quest= true
    local result2 = Casualty.process_party_casualty(patient2.id, {priest.id, patient2.id}, 3)
    assert_eq("party_casualty (with priest) returns bool", type(result2) == "boolean", true)

    -- 7. do_casualty_roll at rate=1.0 (guaranteed survival): enter_rest is called
    AdvData.reset()
    local adv_sure = AdvData.create("SureTest", "warrior", "S")
    -- S-rank vs rank-1 task: survival rate = 0.60 + 6*0.05 = 0.90 + trait bonuses
    -- Use a guaranteed approach: S-rank (7) vs F-task (1) → diff=6, rate=0.60+6*0.05=0.90
    -- We can't force math.random, but we CAN verify that if survived, resting_days is set
    -- Just verify the return type and that the adventurer is either resting or removed
    local alive_before = AdvData.get(adv_sure.id) ~= nil
    assert_eq("adv exists before roll", alive_before, true)
    Casualty.do_casualty_roll(adv_sure.id, 1)
    local adv_after = AdvData.get(adv_sure.id)
    -- Either resting (survived) or removed (dead) — check the state is consistent
    if adv_after then
        assert_eq("survived: resting_days > 0", adv_after.resting_days > 0, true)
        assert_eq("survived: is_on_quest=false", adv_after.is_on_quest, false)
    end
    -- (if adv_after is nil, the adventurer died — that's also valid)

    log.info("=== Casualty Tests Done ===")
end

-- 绑定快捷键 T = 运行测试
y3.game:event('游戏-初始化', function()
    y3.player.with_local(function(p)
        -- 按 T 键触发测试
        y3.game:event('按键-按下', function(_, key)
            if key == 'T' then
                run_adventurer_tests()
                run_trait_system_tests()
                run_casualty_tests()
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
