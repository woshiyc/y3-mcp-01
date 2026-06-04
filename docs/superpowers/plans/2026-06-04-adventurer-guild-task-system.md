# 冒险者公会任务系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Y3 引擎地图中实现完整的冒险者公会任务系统，包含冒险者数据管理、任务发布与报名 AI、玩家派遣决策、实时观战执行和结算逻辑。

**Architecture:** 按职责分为6个 Lua 模块，通过一个中央 `quest_manager.lua` 协调状态机流转。数据全部存储在运行时 Lua 表中（单局内有效）。UI 层通过 y3-ui-pipeline 独立实现，通过事件与逻辑层解耦。

**Tech Stack:** Lua 5.4 · Y3 引擎 y3-lualib · y3.timer · y3.unit · y3.game events · Y3 UI 系统

---

## ⚠️ 首次运行前置检查

在编写任何代码前，执行 y3-lua-pipeline 的脚本目录检测：

```
list_files_top_level("maps/EntryMap/script")
```

- 若返回包含 `y3` → 脚本目录为 `maps/EntryMap/script/`，require 路径无前缀
- 若未找到 → 检查 `global_script`，require 路径加 `map.` 前缀

**本计划中所有文件路径均以 `maps/EntryMap/script/` 为根目录。若实际不同，全部对应调整。**

---

## 文件结构

```
maps/EntryMap/script/
├── guild/
│   ├── adventurer_data.lua     # Phase 1：冒险者数据 + 等级/忠诚度逻辑
│   ├── quest_data.lua          # Phase 2：任务数据 + 状态机定义
│   ├── quest_board.lua         # Phase 3：报名 AI + 任务池管理
│   ├── quest_dispatch.lua      # Phase 4：派遣逻辑 + 失败概率计算
│   ├── quest_execution.lua     # Phase 5：实时观战 + 事件卡 + 召回
│   ├── quest_settlement.lua    # Phase 6：结算逻辑 + 奖励/损失处理
│   └── quest_manager.lua       # 协调器：串联各模块，暴露对外接口
├── guild_test.lua              # 调试/测试入口（绑定快捷键）
└── 可重载的代码.lua             # 现有入口文件，require quest_manager
```

---

## Task 1: 冒险者数据模块 (adventurer_data.lua)

**Files:**
- Create: `maps/EntryMap/script/guild/adventurer_data.lua`
- Modify: `maps/EntryMap/script/guild_test.lua` (后续创建)

### 数据结构

```lua
-- 冒险者数据原型
---@class AdventurerData
---@field id string           -- 唯一 ID，格式 "adv_001"
---@field name string         -- 显示名称
---@field rank integer        -- 等级整数值 1(F)~7(S)
---@field xp integer          -- 当前经验值
---@field loyalty integer     -- 忠诚度 0~100
---@field profession string   -- 职业名称 ("warrior"/"mage"/"ranger")
---@field skills string[]     -- 已解锁技能列表
---@field specialties string[] -- 专长任务类型列表（如 {"hunt","explore"}），对应专属奖励
---@field is_on_quest boolean  -- 是否在任务中
---@field idle_days number     -- 连续闲置游戏日数（仅完整天数，回任务后重置为0）
```

- [ ] **Step 1: 创建 guild/ 目录和 adventurer_data.lua 基础骨架**

```lua
-- maps/EntryMap/script/guild/adventurer_data.lua
---@class AdventurerData
local M = {}

-- 等级整数值映射
M.RANK_INT = { F=1, E=2, D=3, C=4, B=5, A=6, S=7 }
M.INT_RANK = { [1]="F", [2]="E", [3]="D", [4]="C", [5]="B", [6]="A", [7]="S" }

-- 升级所需经验
M.XP_TO_NEXT = { [1]=300, [2]=800, [3]=2000, [4]=5000, [5]=12000, [6]=nil }
-- rank 6(A) 无法升到 7(S)，S 级需随机触发

-- 存储所有冒险者的全局表
local _adventurers = {} ---@type table<string, AdventurerData>
local _next_id = 1

--- 创建新冒险者
---@param name string
---@param profession string
---@param rank_str string|nil 默认 "F"
---@return AdventurerData
function M.create(name, profession, rank_str)
    local id = "adv_" .. string.format("%03d", _next_id)
    _next_id = _next_id + 1
    local adv = {
        id = id,
        name = name,
        rank = M.RANK_INT[rank_str or "F"],
        xp = 0,
        loyalty = 60,
        profession = profession,
        skills = {},
        specialties = {},   -- 专长任务类型，例如 {"hunt"} 或 {"explore","escort"}
        is_on_quest = false,
        idle_days = 0,
    }
    _adventurers[id] = adv
    return adv
end

--- 获取冒险者
---@param id string
---@return AdventurerData|nil
function M.get(id)
    return _adventurers[id]
end

--- 获取所有冒险者
---@return AdventurerData[]
function M.get_all()
    local result = {}
    for _, adv in pairs(_adventurers) do
        result[#result+1] = adv
    end
    return result
end

return M
```

- [ ] **Step 2: 添加忠诚度变更函数**

```lua
-- 在 adventurer_data.lua 继续添加

--- 修改忠诚度，自动钳制在 [0, 100]
---@param id string
---@param delta integer
function M.change_loyalty(id, delta)
    local adv = _adventurers[id]
    if not adv then return end
    adv.loyalty = math.max(0, math.min(100, adv.loyalty + delta))
end

--- 判断冒险者是否处于动摇状态
---@param id string
---@return boolean
function M.is_wavering(id)
    local adv = _adventurers[id]
    return adv ~= nil and adv.loyalty <= 20
end

--- 判断是否应该离队（仅在失败事件后调用，NOT 在成功时调用）
--- 规则：loyalty=0 必然离队；动摇状态(≤20)下有 30% 概率离队
--- ⚠️ 只在 settlement 的失败/abort 分支中调用，成功结算不触发
---@param id string
---@return boolean
function M.check_departure(id)
    local adv = _adventurers[id]
    if not adv then return false end
    if adv.loyalty <= 0 then return true end
    if M.is_wavering(id) then
        -- 动摇状态下 30% 概率离队（仅失败路径触发）
        return math.random(100) <= 30
    end
    return false
end

--- 移除冒险者（离队/阵亡）
---@param id string
function M.remove(id)
    _adventurers[id] = nil
end
```

- [ ] **Step 3: 添加经验与升级函数**

```lua
-- 在 adventurer_data.lua 继续添加

--- 给予经验，自动触发升级（S 级不可经验升级）
---@param id string
---@param xp_amount integer
---@return boolean rank_up 是否升级
function M.add_xp(id, xp_amount)
    local adv = _adventurers[id]
    if not adv then return false end
    if adv.rank >= 6 then return false end -- A 级以上不可普通升级

    adv.xp = adv.xp + xp_amount
    local required = M.XP_TO_NEXT[adv.rank]
    if required and adv.xp >= required then
        adv.xp = adv.xp - required
        adv.rank = adv.rank + 1
        -- 随机解锁一个技能（技能池由外部注入，此处只记录升级事件）
        return true
    end
    return false
end

--- 计算任务经验倍率
--- task_rank_int: 任务等级整数值
--- adv_rank_int:  冒险者等级整数值
---@param task_rank_int integer
---@param adv_rank_int integer
---@return number multiplier
function M.xp_multiplier(task_rank_int, adv_rank_int)
    local diff = task_rank_int - adv_rank_int
    if diff >= 0 then return 1.0 end      -- 等级相符（diff=0）或更高（不可能发生但防御）
    if diff == -1 then return 0.5 end
    if diff == -2 then return 0.25 end
    return 0.1                            -- diff <= -3
end

--- 处理闲置惩罚（每游戏日结束时对所有冒险者调用）
--- 规则：不在任务中的冒险者，每满1游戏日扣3忠诚度（第1天结束时开始）
--- 在任务中的冒险者 idle_days 不增加（结算时由 reset_idle 重置）
function M.tick_idle_penalty()
    for _, adv in pairs(_adventurers) do
        if not adv.is_on_quest then
            adv.idle_days = adv.idle_days + 1
            -- idle_days 在 tick 后变为 1 表示刚满1天，扣除
            if adv.idle_days >= 1 then
                M.change_loyalty(adv.id, -3)
            end
        end
        -- 注意：is_on_quest=true 时不操作 idle_days，由 reset_idle 在结算时重置
    end
end

--- 冒险者从任务归来时重置闲置计数（由 settlement 模块在解除 is_on_quest 前调用）
---@param id string
function M.reset_idle(id)
    local adv = _adventurers[id]
    if adv then adv.idle_days = 0 end
end
```

- [ ] **Step 4: 创建 guild_test.lua 并添加 Task 1 测试**

```lua
-- maps/EntryMap/script/guild_test.lua
-- 调试快捷键绑定 & 单元测试入口
local AdvData = require 'guild.adventurer_data'

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

-- 绑定快捷键 T = 运行测试
y3.game:event('游戏-初始化', function()
    y3.player.with_local(function(p)
        -- 按 T 键触发测试
        y3.game:event('按键-按下', function(_, key)
            if key == 'T' then run_adventurer_tests() end
        end)
    end)
end)
```

- [ ] **Step 5: 在入口文件中 require guild_test（仅开发阶段）**

在 `maps/EntryMap/script/可重载的代码.lua` 末尾加：
```lua
-- [DEV ONLY] 公会系统调试
require 'guild_test'
```

- [ ] **Step 6: 在 Y3 编辑器中热重载，按 T 键，确认日志输出全部 PASS**

预期日志：
```
[TEST PASS] create.rank
[TEST PASS] create.loyalty
... (全部 PASS，无 FAIL)
[TEST PASS] xp_mult -3 rank
=== Task 1 Tests Done ===
```

- [ ] **Step 7: Commit**

```bash
git add maps/EntryMap/script/guild/adventurer_data.lua
git add maps/EntryMap/script/guild_test.lua
git commit -m "feat(guild): add adventurer data module with rank/loyalty/xp logic"
```

---

## Task 2: 任务数据模块 (quest_data.lua)

**Files:**
- Create: `maps/EntryMap/script/guild/quest_data.lua`
- Modify: `maps/EntryMap/script/guild_test.lua`

- [ ] **Step 1: 创建 quest_data.lua**

```lua
-- maps/EntryMap/script/guild/quest_data.lua
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

--- 创建新任务
---@param title string
---@param rank_int integer
---@param quest_type string
---@param time_limit number|nil
---@return QuestData
function M.create(title, rank_int, quest_type, time_limit)
    local id = "quest_" .. string.format("%04d", _next_id)
    _next_id = _next_id + 1
    local quest = {
        id = id,
        title = title,
        rank = rank_int,
        quest_type = quest_type,
        reward_base = BASE_REWARD[rank_int] or 50,
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

function M.get(id) return _quests[id] end

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
---@param id string
---@param mult number 0.5/0.75/1.0/1.25/1.5
function M.post(id, mult)
    local q = _quests[id]
    if not q or q.status ~= M.STATUS.PENDING then return end
    local valid_mults = {[0.5]=true,[0.75]=true,[1.0]=true,[1.25]=true,[1.5]=true}
    if not valid_mults[mult] then return end
    q.bounty_mult = mult
    q.status = M.STATUS.POSTED
end

--- 转移状态
---@param id string
---@param new_status string
function M.set_status(id, new_status)
    local q = _quests[id]
    if q then q.status = new_status end
end

--- 计算实际赏金总额
---@param id string
---@return integer
function M.total_reward(id)
    local q = _quests[id]
    if not q then return 0 end
    return math.floor(q.reward_base * q.bounty_mult)
end

return M
```

- [ ] **Step 2: 在 guild_test.lua 中添加 Task 2 测试**

在 `guild_test.lua` 顶部添加：
```lua
local QuestData = require 'guild.quest_data'
```

在测试函数区域添加：
```lua
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

    -- 无效倍率不生效
    local q3 = QuestData.create("测试任务", 1, QuestData.TYPE.STRATEGIC, nil)
    QuestData.post(q3.id, 0.9) -- 无效
    assert_eq("invalid mult rejected", QuestData.get(q3.id).status, QuestData.STATUS.PENDING)

    log.info("=== Task 2 Tests Done ===")
end
```

更新按键处理，T 键依次运行所有测试：
```lua
if key == 'T' then
    run_adventurer_tests()
    run_quest_data_tests()
end
```

- [ ] **Step 3: 热重载，按 T，确认 Task 2 全部 PASS**

- [ ] **Step 4: Commit**

```bash
git add maps/EntryMap/script/guild/quest_data.lua
git commit -m "feat(guild): add quest data module with state machine and reward calc"
```

---

## Task 3: 报名 AI 模块 (quest_board.lua)

**Files:**
- Create: `maps/EntryMap/script/guild/quest_board.lua`
- Modify: `maps/EntryMap/script/guild_test.lua`

- [ ] **Step 1: 创建 quest_board.lua**

```lua
-- maps/EntryMap/script/guild/quest_board.lua
local AdvData   = require 'guild.adventurer_data'
local QuestData = require 'guild.quest_data'

local M = {}

-- 按忠诚度决定最低可接受赏金倍率
local function min_acceptable_mult(loyalty)
    if loyalty >= 80 then return 0.5  end
    if loyalty >= 60 then return 0.75 end
    if loyalty >= 40 then return 1.0  end
    if loyalty >= 21 then return 1.25 end
    return 1.5  -- 动摇状态（≤20）极度挑剔
end

--- 对一个任务执行报名 AI，返回愿意报名的冒险者 ID 列表
---@param quest_id string
---@return string[]
function M.collect_registrations(quest_id)
    local quest = QuestData.get(quest_id)
    if not quest or quest.status ~= QuestData.STATUS.POSTED then
        return {}
    end

    local pool = {}
    for _, adv in ipairs(AdvData.get_all()) do
        -- 条件1：技术门槛（等级够）
        if adv.rank < quest.rank then goto continue end
        -- 条件2：空闲
        if adv.is_on_quest then goto continue end
        -- 条件3：赏金门槛（忠诚度决定意愿）
        local min_mult = min_acceptable_mult(adv.loyalty)
        if quest.bounty_mult < min_mult then goto continue end

        pool[#pool+1] = adv.id
        ::continue::
    end

    -- 写入任务数据
    quest.registered_ids = pool
    return pool
end

--- 查询某任务的当前报名池
---@param quest_id string
---@return string[]
function M.get_pool(quest_id)
    local quest = QuestData.get(quest_id)
    if not quest then return {} end
    return quest.registered_ids
end

return M
```

- [ ] **Step 2: 在 guild_test.lua 添加 Task 3 测试**

顶部添加：
```lua
local QuestBoard = require 'guild.quest_board'
```

新增测试函数：
```lua
local function run_quest_board_tests()
    log.info("=== Task 3: Quest Board Tests ===")

    -- 准备：3个冒险者，不同忠诚度
    local adv_high = AdvData.create("Alice", "warrior", "C") -- rank=4, loyalty=60
    local adv_low  = AdvData.create("Bob",   "mage",    "D") -- rank=3, loyalty=60
    local adv_wavering = AdvData.create("Carol", "ranger", "B") -- rank=5
    AdvData.change_loyalty(adv_wavering.id, -45) -- loyalty=15（动摇）

    -- 任务：D级(3)，倍率1.0
    local q = QuestData.create("D级讨伐", 3, QuestData.TYPE.HUNT, nil)
    QuestData.post(q.id, 1.0)

    local pool = QuestBoard.collect_registrations(q.id)

    -- adv_high: C级(4)≥D级(3)，忠诚60，min_mult=0.75，1.0≥0.75 → 报名
    -- adv_low:  D级(3)≥D级(3)，忠诚60，min_mult=0.75，1.0≥0.75 → 报名
    -- adv_wavering: B级(5)≥D级(3)，忠诚15(动摇)，min_mult=1.5，1.0<1.5 → 不报名
    assert_eq("pool size at 1.0x", #pool, 2)

    -- 换成1.5x，动摇冒险者也报名
    q.bounty_mult = 1.5
    local pool2 = QuestBoard.collect_registrations(q.id)
    assert_eq("pool size at 1.5x", #pool2, 3)

    -- 等级不够的冒险者（如F级）不报名
    local adv_f = AdvData.create("Newbie", "warrior", "F")
    q.bounty_mult = 1.5
    local pool3 = QuestBoard.collect_registrations(q.id)
    assert_eq("F-rank excluded from D quest", #pool3, 3) -- newbie仍不在

    log.info("=== Task 3 Tests Done ===")
end
```

更新 T 键：
```lua
if key == 'T' then
    run_adventurer_tests()
    run_quest_data_tests()
    run_quest_board_tests()
end
```

- [ ] **Step 3: 热重载，按 T，确认全部 PASS**

- [ ] **Step 4: Commit**

```bash
git add maps/EntryMap/script/guild/quest_board.lua
git commit -m "feat(guild): add quest board AI with loyalty-based registration logic"
```

---

## Task 4: 派遣模块 (quest_dispatch.lua)

**Files:**
- Create: `maps/EntryMap/script/guild/quest_dispatch.lua`
- Modify: `maps/EntryMap/script/guild_test.lua`

- [ ] **Step 1: 创建 quest_dispatch.lua**

```lua
-- maps/EntryMap/script/guild/quest_dispatch.lua
local AdvData   = require 'guild.adventurer_data'
local QuestData = require 'guild.quest_data'

local M = {}

--- 计算队伍平均等级整数值（四舍五入）
---@param adv_ids string[]
---@return integer avg_rank_int
function M.calc_party_avg_rank(adv_ids)
    if #adv_ids == 0 then return 0 end
    local total = 0
    for _, id in ipairs(adv_ids) do
        local adv = AdvData.get(id)
        if adv then total = total + adv.rank end
    end
    return math.floor(total / #adv_ids + 0.5) -- 四舍五入
end

--- 计算基础失败概率（重度失败 / 全灭）
--- 返回 { heavy=number, wipe=number }，值为 0~1
---@param task_rank_int integer
---@param party_avg_rank integer
---@return table
function M.calc_base_fail_prob(task_rank_int, party_avg_rank)
    local diff = task_rank_int - party_avg_rank
    if diff <= 0 then return { heavy=0.10, wipe=0.01 } end
    if diff == 1 then return { heavy=0.25, wipe=0.05 } end
    if diff == 2 then return { heavy=0.50, wipe=0.20 } end
    return { heavy=0.80, wipe=0.50 } -- diff >= 3
end

--- 计算装备修正（装备平均等级 vs 任务等级的差）
---@param equip_avg_rank integer  装备平均等级整数值（无装备=0）
---@param task_rank_int integer
---@return number delta  正数=降低概率（对玩家有利），负数=提高概率
function M.calc_equip_delta(equip_avg_rank, task_rank_int)
    local diff = equip_avg_rank - task_rank_int
    if diff >= 1  then return -0.10 end  -- 装备超出任务等级：-10%
    if diff == 0  then return  0.00 end  -- 同级：无修正
    if diff == -1 then return  0.05 end  -- 低一级：+5%
    return 0.15                          -- 低两级以上：+15%
end

--- 计算最终失败概率
---@param task_rank_int integer
---@param adv_ids string[]
---@param equip_avg_rank integer
---@return table { heavy=number, wipe=number }
function M.calc_final_fail_prob(task_rank_int, adv_ids, equip_avg_rank)
    local avg = M.calc_party_avg_rank(adv_ids)
    local base = M.calc_base_fail_prob(task_rank_int, avg)
    local delta = M.calc_equip_delta(equip_avg_rank, task_rank_int)
    return {
        heavy = math.max(0, math.min(0.95, base.heavy + delta)),
        wipe  = math.max(0, math.min(0.95, base.wipe  + delta)),
    }
end

--- 执行派遣：将选定冒险者标记为任务中，任务转为 DISPATCHED
---@param quest_id string
---@param selected_ids string[] 玩家选择的冒险者 ID（必须在报名池中）
---@param equip_ids string[]    借出装备 ID 列表
---@return boolean success
function M.dispatch(quest_id, selected_ids, equip_ids)
    local quest = QuestData.get(quest_id)
    if not quest or quest.status ~= QuestData.STATUS.POSTED then
        return false
    end

    -- 验证所有选定 ID 都在报名池中
    local pool_set = {}
    for _, id in ipairs(quest.registered_ids) do pool_set[id] = true end
    for _, id in ipairs(selected_ids) do
        if not pool_set[id] then return false end
    end

    -- 标记冒险者为任务中
    for _, id in ipairs(selected_ids) do
        local adv = AdvData.get(id)
        if adv then
            adv.is_on_quest = true
            adv.idle_days = 0
        end
    end

    quest.dispatched_ids = selected_ids
    quest.equipment_ids  = equip_ids or {}
    QuestData.set_status(quest_id, QuestData.STATUS.DISPATCHED)
    return true
end

return M
```

- [ ] **Step 2: 在 guild_test.lua 添加 Task 4 测试**

顶部添加：
```lua
local Dispatch = require 'guild.quest_dispatch'
```

新增测试函数：
```lua
local function run_dispatch_tests()
    log.info("=== Task 4: Dispatch Tests ===")

    -- 平均等级计算
    local a1 = AdvData.create("X", "warrior", "B") -- 5
    local a2 = AdvData.create("Y", "mage",    "D") -- 3
    local a3 = AdvData.create("Z", "ranger",  "C") -- 4
    -- (5+3+4)/3 = 4.0 → C
    assert_eq("avg rank BDC", Dispatch.calc_party_avg_rank({a1.id,a2.id,a3.id}), 4)

    -- (1+2)/2 = 1.5 → 2(E)
    local af = AdvData.create("F1","warrior","F")
    local ae = AdvData.create("E1","warrior","E")
    assert_eq("avg rank FE", Dispatch.calc_party_avg_rank({af.id,ae.id}), 2)

    -- 基础失败概率
    local p0 = Dispatch.calc_base_fail_prob(3, 3)
    assert_eq("same rank heavy", p0.heavy, 0.10)
    assert_eq("same rank wipe",  p0.wipe,  0.01)

    local p2 = Dispatch.calc_base_fail_prob(5, 3)
    assert_eq("+2 rank heavy", p2.heavy, 0.50)

    -- 装备修正
    local delta_good = Dispatch.calc_equip_delta(4, 3) -- 装备超1级
    assert_eq("equip +1 delta", delta_good, -0.10)

    -- 最终概率（同级 + 超1级装备 = 10%-10%=0%）
    local adv_c = AdvData.create("CC","warrior","C") -- rank=4
    local final = Dispatch.calc_final_fail_prob(4, {adv_c.id}, 5)
    assert_eq("final heavy 0%", final.heavy, 0.0)
    assert_eq("final wipe 0%",  final.wipe,  0.0)

    log.info("=== Task 4 Tests Done ===")
end
```

更新 T 键，添加 `run_dispatch_tests()`。

- [ ] **Step 3: 热重载，按 T，确认全部 PASS**

- [ ] **Step 4: Commit**

```bash
git add maps/EntryMap/script/guild/quest_dispatch.lua
git commit -m "feat(guild): add dispatch module with failure probability calculation"
```

---

## Task 5: 执行与召回模块 (quest_execution.lua)

**Files:**
- Create: `maps/EntryMap/script/guild/quest_execution.lua`
- Modify: `maps/EntryMap/script/guild_test.lua`

> 此模块负责在地图上创建冒险者单位、驱动其移动、监控到达/死亡、触发事件卡、处理召回。

- [ ] **Step 1: 创建 quest_execution.lua**

```lua
-- maps/EntryMap/script/guild/quest_execution.lua
local AdvData    = require 'guild.adventurer_data'
local QuestData  = require 'guild.quest_data'

local M = {}

-- 运行中的任务执行上下文
local _executions = {} ---@type table<string, ExecutionContext>

---@class ExecutionContext
---@field quest_id string
---@field adv_units table<string, py.Unit>  adv_id → 地图单位
---@field target_point table                {x, z}
---@field on_complete function|nil          完成回调
---@field recalled boolean                  是否已召回
---@field death_listener any|nil            死亡事件监听句柄（用于 off()）
---@field check_timer any|nil               检查定时器句柄（用于 cancel()）
---@field card_timer any|nil                事件卡定时器句柄（用于 cancel()）

-- 冒险者职业对应的物编单位 ID（需在编辑器中配置，此处为占位值）
local PROFESSION_UNIT_KEY = {
    warrior = 100101,
    mage    = 100102,
    ranger  = 100103,
}

--- 启动任务执行
---@param quest_id string
---@param target_point table {x:number, z:number}
---@param on_complete function  结算回调，参数为 (quest_id, outcome)
---@param on_event_card function|nil  事件卡回调，参数为 (quest_id, event_data)
function M.start(quest_id, target_point, on_complete, on_event_card)
    local quest = QuestData.get(quest_id)
    if not quest or quest.status ~= QuestData.STATUS.DISPATCHED then return end

    local ctx = {
        quest_id     = quest_id,
        adv_units    = {},
        target_point = target_point,
        on_complete  = on_complete,
        recalled     = false,
    }

    -- 在地图上创建冒险者单位
    local player = y3.player.get_by_id(1) -- 玩家1阵营
    for _, adv_id in ipairs(quest.dispatched_ids) do
        local adv = AdvData.get(adv_id)
        if adv then
            local unit_key = PROFESSION_UNIT_KEY[adv.profession] or 100101
            -- 在起始点附近生成（此处用固定点，实际应由领地数据提供）
            local unit = y3.unit.create(player, unit_key, y3.point.create(0, 0))
            if unit then
                ctx.adv_units[adv_id] = unit
                -- 命令单位移动到目标点
                unit:move_to(y3.point.create(target_point.x, target_point.z))
            end
        end
    end

    _executions[quest_id] = ctx

    -- 监听单位死亡（存储句柄用于后续 off()，防止监听器泄漏）
    local death_handler = function(_, dead_unit)
        if not _executions[quest_id] then return end
        for adv_id, u in pairs(ctx.adv_units) do
            if u == dead_unit then
                ctx.adv_units[adv_id] = nil
                break
            end
        end
        local any_alive = false
        for _, u in pairs(ctx.adv_units) do
            if u then any_alive = true; break end
        end
        if not any_alive then
            M._finish(quest_id, "wipe")
        end
    end
    -- ⚠️ 必须使用 :event() 返回的句柄（或 Y3 等效 API）在 _finish() 中 off()
    -- 若 Y3 API 为 y3.game:event() 返回句柄，则：
    ctx.death_listener = y3.game:event('单位-死亡', death_handler)

    -- 定时检查到达目标（每2秒，存储句柄用于 cancel）
    ctx.check_timer = y3.timer.loop(2, function()
        if not _executions[quest_id] or ctx.recalled then return end
        -- 实际到达检测：检查距离 < 阈值或触发区事件（具体任务类型扩展）
    end)

    -- 偶发事件卡（Task 8 集成后写入 ctx.card_timer）
end

--- 玩家主动召回（轻度失败结算）
---@param quest_id string
function M.recall(quest_id)
    local ctx = _executions[quest_id]
    if not ctx or ctx.recalled then return end
    ctx.recalled = true

    -- 删除地图上的冒险者单位
    for _, u in pairs(ctx.adv_units) do
        if u then u:remove() end
    end
    ctx.adv_units = {}

    M._finish(quest_id, "abort")
end

--- 内部：完成执行，清理所有监听器和定时器（防泄漏）
---@param quest_id string
---@param outcome string "success"|"light_fail"|"heavy_fail"|"wipe"|"abort"
function M._finish(quest_id, outcome)
    local ctx = _executions[quest_id]
    if not ctx then return end
    _executions[quest_id] = nil

    -- ⚠️ 必须在这里注销所有监听器和定时器，避免泄漏
    -- Y3 API：若 y3.game:event() 返回可 off 的句柄则 :off()
    -- 若 API 为 y3.timer.loop() 返回 timer 对象则 :cancel()
    -- 实际 API 名称请对照 timer.md / y3-lualib 文档确认
    if ctx.death_listener then
        -- y3.game:off(ctx.death_listener)  ← 按实际 API 解注释
    end
    if ctx.check_timer then
        ctx.check_timer:cancel()  -- 取消循环定时器
    end
    if ctx.card_timer then
        ctx.card_timer:cancel()
    end

    if ctx.on_complete then
        ctx.on_complete(quest_id, outcome)
    end
end

--- 从外部标记任务成功（到达目标、完成目标后调用）
---@param quest_id string
function M.mark_success(quest_id)
    M._finish(quest_id, "success")
end

--- 从外部标记任务失败（重度失败）
---@param quest_id string
---@param is_heavy boolean
function M.mark_fail(quest_id, is_heavy)
    M._finish(quest_id, is_heavy and "heavy_fail" or "light_fail")
end

return M
```

- [ ] **Step 2: 在 guild_test.lua 添加召回路径测试（不需要地图单位，只测逻辑）**

```lua
local Execution = require 'guild.quest_execution'

local function run_execution_tests()
    log.info("=== Task 5: Execution Tests ===")
    -- 执行模块主要依赖游戏运行时（单位创建），此处只测非地图路径
    -- 完整测试需在游戏中手动验证（见操作手册）

    log.info("[MANUAL] Task 5: 需要在游戏中验证以下行为：")
    log.info("  - 派遣后，冒险者单位出现在地图上并向目标移动")
    log.info("  - 按 R 键召回，单位消失，任务以 abort 结算")
    log.info("  - 单位全部死亡时，触发 wipe 结算")
    log.info("=== Task 5 Tests Done ===")
end
```

添加 R 键召回快捷键（在 T 键绑定区域旁边）：
```lua
if key == 'R' then
    -- 召回第一个 DISPATCHED 任务（调试用）
    local dispatched = QuestData.get_by_status(QuestData.STATUS.DISPATCHED)
    if dispatched[1] then
        Execution.recall(dispatched[1].id)
        log.info("[DEBUG] 召回任务: " .. dispatched[1].id)
    end
end
```

- [ ] **Step 3: 热重载，按 T，确认无错误（手动测试项记录在日志）**

- [ ] **Step 4: Commit**

```bash
git add maps/EntryMap/script/guild/quest_execution.lua
git commit -m "feat(guild): add quest execution module with unit movement and recall"
```

---

## Task 6: 结算模块 (quest_settlement.lua)

**Files:**
- Create: `maps/EntryMap/script/guild/quest_settlement.lua`
- Modify: `maps/EntryMap/script/guild_test.lua`

- [ ] **Step 1: 创建 quest_settlement.lua**

```lua
-- maps/EntryMap/script/guild/quest_settlement.lua
local AdvData   = require 'guild.adventurer_data'
local QuestData = require 'guild.quest_data'
local Dispatch  = require 'guild.quest_dispatch'

local M = {}

-- 赏金倍率 → 忠诚度变化
local LOYALTY_BY_MULT = {
    [0.5]=0, [0.75]=2, [1.0]=5, [1.25]=10, [1.5]=15
}

-- 任务基础经验奖励（按任务等级整数值）
local BASE_XP = {
    [1]=100, [2]=200, [3]=450, [4]=900, [5]=1800, [6]=3500, [7]=7000
}

---@class SettlementResult
---@field outcome string         "success"|"light_fail"|"heavy_fail"|"wipe"|"abort"
---@field gold_reward integer    玩家获得金币（成功时有值）
---@field lost_adv_ids string[]  永久失去的冒险者 ID
---@field lost_equip_ids string[] 损毁装备 ID
---@field loyalty_changes table<string,integer> adv_id → loyalty delta

--- 计算装备平均等级整数值（无装备返回0）
--- equip_ids: 物品 ID 列表，此处简化：假设装备 ID 携带等级信息，
--- 实际实现时需从物品库查询，占位实现返回任务等级（同级装备，无修正）
---@param equip_ids string[]
---@param fallback_rank integer 当无法查询时的兜底值
---@return integer
local function calc_equip_avg_rank(equip_ids, fallback_rank)
    if #equip_ids == 0 then return 0 end
    -- TODO: 对接物品库后，从每个 eq_id 查询其等级整数值，求平均
    -- 目前返回 fallback_rank（同级装备，无惩罚也无加成）
    return fallback_rank
end

--- 执行结算
---@param quest_id string
---@param outcome string
---@return SettlementResult
function M.settle(quest_id, outcome)
    local quest = QuestData.get(quest_id)
    if not quest then return { outcome=outcome, gold_reward=0, lost_adv_ids={}, lost_equip_ids={}, loyalty_changes={} } end

    local result = {
        outcome = outcome,
        gold_reward = 0,
        lost_adv_ids = {},
        lost_equip_ids = {},
        loyalty_changes = {},
    }

    local dispatched = quest.dispatched_ids
    local equip_ids  = quest.equipment_ids

    if outcome == "success" then
        result.gold_reward = QuestData.total_reward(quest_id)
        local loyalty_gain = LOYALTY_BY_MULT[quest.bounty_mult] or 5
        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then
                AdvData.reset_idle(adv_id)        -- 归来时重置闲置计数
                adv.is_on_quest = false
                AdvData.change_loyalty(adv_id, loyalty_gain)
                result.loyalty_changes[adv_id] = loyalty_gain
                -- 专属奖励：任务类型匹配专长时额外 +5 忠诚度
                for _, specialty in ipairs(adv.specialties or {}) do
                    if specialty == quest.quest_type then
                        AdvData.change_loyalty(adv_id, 5)
                        result.loyalty_changes[adv_id] = (result.loyalty_changes[adv_id] or 0) + 5
                        break
                    end
                end
                -- 经验奖励（TODO: 多人任务分配公式待设计，当前平均分配）
                local xp = (BASE_XP[quest.rank] or 100)
                local mult = AdvData.xp_multiplier(quest.rank, adv.rank)
                AdvData.add_xp(adv_id, math.floor(xp * mult))
            end
        end
        QuestData.set_status(quest_id, QuestData.STATUS.SUCCEEDED)

    elseif outcome == "light_fail" or outcome == "abort" then
        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then
                AdvData.reset_idle(adv_id)
                adv.is_on_quest = false
                AdvData.change_loyalty(adv_id, -10)
                result.loyalty_changes[adv_id] = -10
                -- ⚠️ 只在失败路径调用 check_departure
                if AdvData.check_departure(adv_id) then
                    result.lost_adv_ids[#result.lost_adv_ids+1] = adv_id
                    AdvData.remove(adv_id)
                end
            end
        end
        QuestData.set_status(quest_id, QuestData.STATUS.FAILED)

    elseif outcome == "heavy_fail" then
        -- 使用实际装备等级计算最终概率（修复：不再硬传 0）
        local equip_avg = calc_equip_avg_rank(equip_ids, quest.rank)
        local prob = Dispatch.calc_final_fail_prob(quest.rank, dispatched, equip_avg)
        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then
                if math.random() < prob.heavy then
                    result.lost_adv_ids[#result.lost_adv_ids+1] = adv_id
                    AdvData.remove(adv_id)
                else
                    -- 幸存者：重置闲置、解除任务状态、扣忠诚、检查离队
                    AdvData.reset_idle(adv_id)
                    adv.is_on_quest = false
                    AdvData.change_loyalty(adv_id, -20)
                    result.loyalty_changes[adv_id] = -20
                    -- ⚠️ -20 可能推入动摇区，必须检查离队
                    if AdvData.check_departure(adv_id) then
                        result.lost_adv_ids[#result.lost_adv_ids+1] = adv_id
                        AdvData.remove(adv_id)
                    end
                end
            end
        end
        for _, eq_id in ipairs(equip_ids) do
            if math.random() < prob.heavy then
                result.lost_equip_ids[#result.lost_equip_ids+1] = eq_id
            end
        end
        QuestData.set_status(quest_id, QuestData.STATUS.FAILED)

    elseif outcome == "wipe" then
        -- 全灭：所有派遣冒险者永久失去
        for _, adv_id in ipairs(dispatched) do
            result.lost_adv_ids[#result.lost_adv_ids+1] = adv_id
            AdvData.remove(adv_id)
        end
        result.lost_equip_ids = equip_ids
        -- ⚠️ 全灭事件对公会其他成员造成 -20 士气（幸存者处理）
        for _, adv in ipairs(AdvData.get_all()) do
            -- 仅影响本次未派遣的在场冒险者
            local was_dispatched = false
            for _, did in ipairs(dispatched) do
                if did == adv.id then was_dispatched = true; break end
            end
            if not was_dispatched then
                AdvData.change_loyalty(adv.id, -20)
                result.loyalty_changes[adv.id] = -20
            end
        end
        QuestData.set_status(quest_id, QuestData.STATUS.FAILED)
    end

    return result
end

return M
```

- [ ] **Step 2: 在 guild_test.lua 添加 Task 6 测试**

顶部添加：
```lua
local Settlement = require 'guild.quest_settlement'
```

新增测试函数：
```lua
local function run_settlement_tests()
    log.info("=== Task 6: Settlement Tests ===")

    -- 成功结算
    local adv1 = AdvData.create("Hero", "warrior", "D")
    local q1 = QuestData.create("成功测试", 3, QuestData.TYPE.HUNT, nil)
    QuestData.post(q1.id, 1.25)
    q1.dispatched_ids = {adv1.id}
    adv1.is_on_quest = true

    local r1 = Settlement.settle(q1.id, "success")
    assert_eq("success gold", r1.gold_reward, 500) -- floor(400*1.25)=500
    assert_eq("success no lost adv", #r1.lost_adv_ids, 0)
    assert_eq("success loyalty gain", r1.loyalty_changes[adv1.id], 10)
    assert_eq("success adv freed", AdvData.get(adv1.id).is_on_quest, false)

    -- 全灭结算
    local adv2 = AdvData.create("Martyr", "ranger", "C")
    local q2 = QuestData.create("全灭测试", 3, QuestData.TYPE.HUNT, nil)
    QuestData.post(q2.id, 1.0)
    q2.dispatched_ids = {adv2.id}
    q2.equipment_ids  = {"eq_001"}
    adv2.is_on_quest = true

    local r2 = Settlement.settle(q2.id, "wipe")
    assert_eq("wipe adv lost", #r2.lost_adv_ids, 1)
    assert_eq("wipe equip lost", #r2.lost_equip_ids, 1)
    assert_eq("wipe adv removed from registry", AdvData.get(adv2.id), nil)

    log.info("=== Task 6 Tests Done ===")
end
```

更新 T 键，添加 `run_settlement_tests()`。

- [ ] **Step 3: 热重载，按 T，确认全部 PASS**

- [ ] **Step 4: Commit**

```bash
git add maps/EntryMap/script/guild/quest_settlement.lua
git commit -m "feat(guild): add settlement module with outcome branching and loyalty updates"
```

---

## Task 7: 协调器 (quest_manager.lua)

**Files:**
- Create: `maps/EntryMap/script/guild/quest_manager.lua`
- Modify: `maps/EntryMap/script/可重载的代码.lua`

> 将所有模块串联，提供对外接口，驱动游戏日计时器。

- [ ] **Step 1: 创建 quest_manager.lua**

```lua
-- maps/EntryMap/script/guild/quest_manager.lua
local AdvData    = require 'guild.adventurer_data'
local QuestData  = require 'guild.quest_data'
local QuestBoard = require 'guild.quest_board'
local Dispatch   = require 'guild.quest_dispatch'
local Execution  = require 'guild.quest_execution'
local Settlement = require 'guild.quest_settlement'

local M = {}

-- 游戏日时长（秒）= 600（10分钟），可调
local GAME_DAY_SECONDS = 600

--- 初始化系统（在游戏初始化事件中调用）
function M.init()
    -- 游戏日定时器：每 GAME_DAY_SECONDS 秒触发一次闲置惩罚
    y3.timer.loop(GAME_DAY_SECONDS, function()
        AdvData.tick_idle_penalty()
        log.info("[Guild] 游戏日结束，闲置惩罚已结算")
    end)
    log.info("[Guild] 冒险者公会任务系统已初始化")
end

--- 发布任务（领地事件触发 或 玩家主动创建）
---@param title string
---@param rank_int integer
---@param quest_type string
---@param bounty_mult number
---@param time_limit number|nil
---@return string quest_id
function M.post_quest(title, rank_int, quest_type, bounty_mult, time_limit)
    local q = QuestData.create(title, rank_int, quest_type, time_limit)
    QuestData.post(q.id, bounty_mult)
    QuestBoard.collect_registrations(q.id)
    log.info("[Guild] 任务已发布: " .. title .. " (" .. QuestData.STATUS.POSTED .. ")")
    return q.id
end

--- 执行派遣（玩家从报名池中选人后调用）
---@param quest_id string
---@param selected_ids string[]
---@param equip_ids string[]
---@param target_point table {x, z}
---@return boolean
function M.dispatch_quest(quest_id, selected_ids, equip_ids, target_point)
    local ok = Dispatch.dispatch(quest_id, selected_ids, equip_ids)
    if not ok then
        log.error("[Guild] 派遣失败: " .. quest_id)
        return false
    end

    -- 启动实时执行
    Execution.start(quest_id, target_point, function(qid, outcome)
        -- 结算回调
        local result = Settlement.settle(qid, outcome)
        M._on_settlement(qid, result)
    end)

    return true
end

--- 玩家主动召回
---@param quest_id string
function M.recall_quest(quest_id)
    Execution.recall(quest_id)
end

--- 结算后处理（扣金、通知玩家）
---@param quest_id string
---@param result SettlementResult
function M._on_settlement(quest_id, result)
    local quest = QuestData.get(quest_id)
    if not quest then return end

    local player = y3.player.get_by_id(1)

    if result.gold_reward > 0 then
        -- 给予玩家金币（y3 货币 API）
        player:add_money(result.gold_reward)
    end

    -- 广播结算信息
    local msg = "[公会] " .. (quest.title or quest_id) .. " — " .. result.outcome
    if #result.lost_adv_ids > 0 then
        msg = msg .. " (" .. #result.lost_adv_ids .. "名冒险者永久失去)"
    end
    player:display_message(msg, 5)

    log.info("[Guild] 结算完成: " .. msg)
end

return M
```

- [ ] **Step 2: 在入口文件中初始化**

在 `maps/EntryMap/script/可重载的代码.lua` 中添加：

```lua
local GuildManager = require 'guild.quest_manager'

y3.game:event('游戏-初始化', function()
    GuildManager.init()
end)
```

- [ ] **Step 3: 热重载，确认日志输出 `[Guild] 冒险者公会任务系统已初始化`**

- [ ] **Step 4: 完整流程手动测试**

按以下步骤在游戏中验证：
```
1. 游戏启动 → 日志出现 "[Guild] 冒险者公会任务系统已初始化"
2. 在调试快捷键中调用 GuildManager.post_quest(...) 发布一个任务
3. 日志出现报名池冒险者列表
4. 调用 GuildManager.dispatch_quest(...) 派遣
5. 地图上出现冒险者单位并移动
6. 按 R 键召回 → 日志出现 "任务结算: abort"
```

- [ ] **Step 5: Commit**

```bash
git add maps/EntryMap/script/guild/quest_manager.lua
git commit -m "feat(guild): add quest manager coordinator with game day timer and settlement callbacks"
```

---

## Task 8: 事件卡系统（偶发）

**Files:**
- Modify: `maps/EntryMap/script/guild/quest_execution.lua`
- Create: `maps/EntryMap/script/guild/event_cards.lua`

> 每次任务执行过程中，0~2次概率触发事件卡，玩家选择影响结算。

- [ ] **Step 1: 创建 event_cards.lua**

```lua
-- maps/EntryMap/script/guild/event_cards.lua
local M = {}

-- 事件卡定义（按任务类型分组）
M.CARDS = {
    hunt = {
        {
            id = "ambush",
            text = "队伍遭遇埋伏，是否消耗道具突围？",
            options = {
                { label="消耗道具突围", effect="light_escape" },  -- 轻度失败概率-10%
                { label="强行突围",     effect="risk_escape" },   -- 有概率重度失败
            }
        },
        {
            id = "wounded",
            text = "冒险者受重伤，是否撤退？",
            options = {
                { label="撤退（轻度失败）", effect="abort" },
                { label="继续前进",         effect="continue" },
            }
        },
    },
    explore = {
        {
            id = "treasure",
            text = "发现神秘宝箱，是否冒险开启？",
            options = {
                { label="开启宝箱", effect="bonus_loot" },   -- 额外奖励或触发陷阱
                { label="放弃宝箱", effect="continue" },
            }
        },
    },
}

--- 为任务类型随机抽取0~2张事件卡（按执行进度触发）
---@param quest_type string
---@return table[] cards
function M.draw_cards(quest_type)
    local pool = M.CARDS[quest_type] or {}
    if #pool == 0 then return {} end

    local count = math.random(0, math.min(2, #pool))
    local drawn = {}
    local indices = {}
    for i = 1, #pool do indices[i] = i end

    -- Fisher-Yates 简化版随机取 count 个
    for i = 1, count do
        local j = math.random(i, #indices)
        indices[i], indices[j] = indices[j], indices[i]
        drawn[i] = pool[indices[i]]
    end
    return drawn
end

return M
```

- [ ] **Step 2: 在 quest_execution.lua 的 start() 中集成事件卡**

在 `start()` 函数末尾添加事件卡抽取和定时触发逻辑：

```lua
local EventCards = require 'guild.event_cards'

-- 在 start() 函数内添加：
local cards = EventCards.draw_cards(quest.quest_type)
local card_index = 1

-- 简化触发：每30秒检查是否触发下一张事件卡（存储句柄，_finish 时 cancel）
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
```

- [ ] **Step 3: 热重载，手动验证事件卡触发（查看日志）**

- [ ] **Step 4: Commit**

```bash
git add maps/EntryMap/script/guild/event_cards.lua
git commit -m "feat(guild): add event card system with random in-quest events"
```

---

## Task 9: UI 层（任务公告板 + 派遣界面）

> **使用 y3-ui-pipeline 技能**实现此任务。此任务需要激活 `y3-ui-pipeline` 技能，按其流程创建 UI 面板。

**Files:**
- Create: `UI面板/QuestBoardPanel.json`
- Create: `UI面板/DispatchPanel.json`
- Create: `maps/EntryMap/script/guild/quest_ui.lua`

- [ ] **Step 1: 设计任务公告板 UI 结构（ASCII 草图）**

```
┌─────────── 任务公告板 ───────────────┐
│ [任务标题]  [等级]  [赏金倍率 ▼]  [发布]│
├──────────────────────────────────────┤
│ 待处理任务列表                        │
│  ○ 讨伐哥布林  D级  150g × 1.0x  [挂牌]│
│  ○ 探索遗迹    C级  1000g × ?    [挂牌]│
│                                      │
│ 当前已挂牌任务                        │
│  ● 山贼清剿   E级  150g × 1.25x  [派遣]│
│    报名人数：3/5                      │
└──────────────────────────────────────┘
```

- [ ] **Step 2: 激活 y3-ui-pipeline 技能，按照技能流程生成 QuestBoardPanel.json**

- [ ] **Step 3: 设计派遣选人 UI**

```
┌──────────── 任务：山贼清剿 ─────────────┐
│ 等级：E   赏金：187g    时限：3天       │
├──────────────────────────────────────  │
│ 报名冒险者（点击选择）                   │
│  [✓] Alice  D级  忠诚:80  技能:剑术     │
│  [ ] Bob    C级  忠诚:55  技能:火球     │
│  [ ] Carol  B级  忠诚:15⚠ 技能:疾风    │
├──────────────────────────────────────  │
│ 失败概率：重度 10%  全灭 1%             │
│ 借出装备：[选择装备 ▼]                 │
│                    [取消]  [确认派遣]  │
└──────────────────────────────────────┘
```

- [ ] **Step 4: 激活 y3-ui-pipeline 技能，按照技能流程生成 DispatchPanel.json**

- [ ] **Step 5: 创建 quest_ui.lua 绑定 UI 逻辑**

```lua
-- maps/EntryMap/script/guild/quest_ui.lua
local GuildManager = require 'guild.quest_manager'
local QuestData    = require 'guild.quest_data'
local AdvData      = require 'guild.adventurer_data'
local Dispatch     = require 'guild.quest_dispatch'

local M = {}

function M.init()
    y3.player.with_local(function(player)
        -- 绑定任务公告板"确认派遣"按钮
        local dispatch_btn = y3.ui.get_ui(player, "DispatchPanel.confirm_btn")
        if dispatch_btn then
            dispatch_btn:add_fast_event('左键-按下', function()
                -- 从 UI 状态读取当前选择（具体实现依赖 UI 数据绑定）
                -- 此处为框架占位，实际绑定在 y3-ui-pipeline 生成后完善
                log.info("[GuildUI] 确认派遣按钮点击")
            end)
        end
    end)
end

return M
```

- [ ] **Step 6: 热重载，验证 UI 面板可以打开，按钮响应正常**

- [ ] **Step 7: Commit**

```bash
git add "UI面板/QuestBoardPanel.json" "UI面板/DispatchPanel.json"
git add maps/EntryMap/script/guild/quest_ui.lua
git commit -m "feat(guild): add quest board and dispatch UI panels"
```

---

## Task 10: 结算 UI + 系统收尾

**Files:**
- Create: `UI面板/SettlementPanel.json`
- Modify: `maps/EntryMap/script/guild/quest_manager.lua`

- [ ] **Step 1: 设计结算面板**

```
┌──────────── 任务结算 ────────────────┐
│  任务：山贼清剿          ✅ 成功      │
├─────────────────────────────────────│
│  奖励：+187 金币                     │
│  Alice: 忠诚度 +10 ↑   XP +200      │
│  Bob:   忠诚度 +10 ↑   XP +100      │
├─────────────────────────────────────│
│                           [确认]    │
└─────────────────────────────────────┘
```

失败版本：
```
┌──────────── 任务结算 ────────────────┐
│  任务：挑战魔龙          ❌ 全灭      │
├─────────────────────────────────────│
│  🪦 Alice 永久失去                   │
│  🪦 Bob   永久失去                   │
│  装备"精钢剑"已损毁                   │
├─────────────────────────────────────│
│                           [确认]    │
└─────────────────────────────────────┘
```

- [ ] **Step 2: 激活 y3-ui-pipeline 生成 SettlementPanel.json**

- [ ] **Step 3: 在 quest_manager._on_settlement() 中触发结算面板显示**

```lua
-- 在 _on_settlement 中添加
local quest_ui = require 'guild.quest_ui'
quest_ui.show_settlement(result)
```

- [ ] **Step 4: 全流程端到端测试**

在游戏中跑完整链路一次：
```
发布任务（post_quest）
→ 查看报名池
→ 选人派遣（dispatch_quest）
→ 观战冒险者移动
→ 等待结算
→ 查看结算面板
→ 确认冒险者数据更新（忠诚度、经验）
```

- [ ] **Step 5: 移除开发阶段的 `require 'guild_test'`（或加 debug 开关）**

```lua
-- 可重载的代码.lua
local DEBUG_MODE = false  -- 发布时改为 false
if DEBUG_MODE then
    require 'guild_test'
end
```

- [ ] **Step 6: 最终 Commit**

```bash
git add "UI面板/SettlementPanel.json"
git commit -m "feat(guild): add settlement UI panel and complete end-to-end quest flow"
```

---

## 参考资料

编写 Lua 代码时必须激活 `y3-lua-pipeline` 技能并读取：
- `y3-maker-config/skills/y3-lua-pipeline/references/unit.md` — 单位 API
- `y3-maker-config/skills/y3-lua-pipeline/references/player.md` — 玩家 API
- `y3-maker-config/skills/y3-lua-pipeline/references/timer.md` — 计时器 API
- `y3-maker-config/rules/api-safety.mdc` — API 安全规则

设计文档：`docs/superpowers/specs/2026-06-03-adventurer-guild-task-system-design.md`
