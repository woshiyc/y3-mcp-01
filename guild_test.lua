-- guild_test.lua
-- 调试快捷键绑定 & 单元测试入口
local AdvData = require 'guild.adventurer_data'
local QuestData = require 'guild.quest_data'

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

-- 绑定快捷键 T = 运行测试
y3.game:event('游戏-初始化', function()
    y3.player.with_local(function(p)
        -- 按 T 键触发测试
        y3.game:event('按键-按下', function(_, key)
            if key == 'T' then
                run_adventurer_tests()
                run_quest_data_tests()
            end
        end)
    end)
end)
