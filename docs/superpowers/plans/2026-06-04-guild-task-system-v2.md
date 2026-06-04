# Guild Task System V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the guild task system to use real-time MOBA-unit simulation, a difficulty-based level acceptance range, and a trait system that replaces loyalty.

**Architecture:** Two new modules (`trait_system.lua`, `casualty.lua`) are added; four existing modules are modified (`adventurer_data`, `quest_board`, `quest_execution`, `quest_settlement`); and `quest_dispatch`'s probability layer is deleted. The `guild_test.lua` test suite is extended throughout.

**Tech Stack:** Lua 5.4, Y3 engine runtime APIs (`y3.unit`, `y3.timer`, `y3.game:event`), existing guild module structure.

**Spec:** [docs/superpowers/specs/2026-06-04-guild-task-system-v2-design.md](../specs/2026-06-04-guild-task-system-v2-design.md)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `guild/trait_system.lua` | **Create** | Trait catalog, trigger rolls, effect query, trait-list management |
| `guild/casualty.lua` | **Create** | Death/injury judgment chain, first-aid roll, rest/vacation state |
| `guild/adventurer_data.lua` | **Modify** | Remove loyalty fields; add `traits[]`, `resting_days`, `vacation_days` |
| `guild/quest_board.lua` | **Modify** | Replace loyalty gate with difficulty-based level range + trait behavior gate |
| `guild/quest_execution.lua` | **Modify** | Death event calls `casualty.lua` chain; all-dead check triggers task failure |
| `guild/quest_dispatch.lua` | **Modify** | Delete `calc_base_fail_prob`, `calc_equip_delta`, `calc_final_fail_prob` |
| `guild/quest_settlement.lua` | **Modify** | Remove heavy_fail/probability branches; add post-settlement trait roll calls |
| `guild_test.lua` | **Modify** | Add tests for trait system, casualty chain, new board logic, new settlement |

---

## Task 1: Create `trait_system.lua` — Trait Catalog and Roll Logic

**Files:**
- Create: `guild/trait_system.lua`
- Modify: `guild_test.lua` (add test section at bottom)

### Step 1.1: Write failing tests for trait_system

Add this function to `guild_test.lua` (before the keyboard binding at the bottom):

```lua
local TraitSystem = require 'guild.trait_system'

local function run_trait_system_tests()
    log.info("=== TraitSystem Tests ===")
    local adv = AdvData.create("TraitTester", "warrior", "C")

    -- 1. add_trait
    local ok = TraitSystem.add_trait(adv.id, "battle_veteran")
    assert_eq("add_trait returns true on success", ok, true)
    assert_eq("has_trait after add", TraitSystem.has_trait(adv.id, "battle_veteran"), true)

    -- 2. duplicate prevention
    local ok2 = TraitSystem.add_trait(adv.id, "battle_veteran")
    assert_eq("add_trait returns false on duplicate", ok2, false)

    -- 3. trait cap: fill to 6, then attempt to add a 7th non-removable
    -- first clear and fill with non-removable
    AdvData.reset()
    local adv2 = AdvData.create("CapTest", "mage", "B")
    -- Add 6 permanent traits
    local permanent_ids = {"battle_veteran","brave","lucky","inspiring","fast_recovery","tenacious"}
    for _, tid in ipairs(permanent_ids) do
        TraitSystem.add_trait(adv2.id, tid)
    end
    local ok3 = TraitSystem.add_trait(adv2.id, "greedy")
    assert_eq("blocked when all 6 are non-removable", ok3, false)

    -- 4. trait cap: fill with 6 removable traits, then add a 7th (should evict one)
    AdvData.reset()
    local adv3 = AdvData.create("EvictTest", "ranger", "A")
    local removable_ids = {"traumatized","cowardly","alcoholic","suspicious","fragile","heartbroken"}
    for _, tid in ipairs(removable_ids) do
        TraitSystem.add_trait(adv3.id, tid)
    end
    local adv3data = AdvData.get(adv3.id)
    assert_eq("6 traits before eviction", #adv3data.traits, 6)
    local ok4 = TraitSystem.add_trait(adv3.id, "proud")
    assert_eq("add_trait succeeds with eviction", ok4, true)
    assert_eq("still 6 traits after eviction", #adv3data.traits, 6)

    -- 5. get_level_min_offset
    AdvData.reset()
    local adv4 = AdvData.create("LevelTest", "warrior", "S")
    TraitSystem.add_trait(adv4.id, "proud")       -- proud: min_offset +1
    TraitSystem.add_trait(adv4.id, "greedy")      -- greedy: min_offset -1
    -- net offset = 0
    assert_eq("level min offset nets to 0", TraitSystem.get_level_min_offset(adv4.id), 0)

    -- 6. get_max_rank_cap (懦弱 caps upper bound at own rank)
    AdvData.reset()
    local adv5 = AdvData.create("CowardTest", "ranger", "C")
    assert_eq("no cap without cowardly", TraitSystem.get_max_rank_cap(adv5.id), nil)
    TraitSystem.add_trait(adv5.id, "cowardly")
    assert_eq("cap=own rank with cowardly", TraitSystem.get_max_rank_cap(adv5.id), adv5.rank)

    -- 7. rejects_quest_type
    AdvData.reset()
    local adv6 = AdvData.create("PhobiaTest", "mage", "D")
    TraitSystem.add_trait(adv6.id, "traumatized")  -- traumatized rejects "hunt"
    assert_eq("rejects hunt with traumatized", TraitSystem.rejects_quest_type(adv6.id, "hunt"), true)
    assert_eq("allows explore with traumatized", TraitSystem.rejects_quest_type(adv6.id, "explore"), false)

    -- 8. trigger_negative_roll (deterministic with seed or just check it returns bool)
    AdvData.reset()
    local adv7 = AdvData.create("RollTest", "warrior", "F")
    local result = TraitSystem.trigger_negative_roll(adv7.id)
    assert_eq("trigger_negative_roll returns bool", type(result) == "boolean", true)

    log.info("=== TraitSystem Tests Done ===")
end
```

Also add `run_trait_system_tests()` to the T-key handler (before the final `log.info`).

- [ ] Add the `run_trait_system_tests` function and call to `guild_test.lua` as shown above

### Step 1.2: Run tests to verify they fail

Press T key in-game (or simulate `require` in standalone Lua runner).
Expected: ERROR — `module 'guild.trait_system' not found`

- [ ] Confirm the require error appears in game log

### Step 1.3: Create `guild/trait_system.lua`

```lua
-- guild/trait_system.lua
-- 特质系统：特质库、触发判定、效果查询、特质列表管理
local AdvData = require 'guild.adventurer_data'

local M = {}

-- ── 特质库 ──────────────────────────────────────────────────────────────────
-- fields: id, name, type, removable, level_min_offset, max_rank_cap,
--         reject_quest_types, stat_effects (table of multipliers)
M.CATALOG = {
    -- 正面特质
    battle_veteran = {
        id="battle_veteran", name="战场老兵", type="positive", removable=false,
        stat_effects = { atk_mult=1.10, crit_bonus=0.05 }
    },
    near_death_survivor = {
        id="near_death_survivor", name="九死一生", type="positive", removable=false,
        stat_effects = { hp_mult=1.15, casualty_roll_bonus=0.10 }
    },
    brave = {
        id="brave", name="勇猛", type="positive", removable=false,
        stat_effects = { boss_dmg_mult=1.15 }
    },
    fearless = {
        id="fearless", name="无畏", type="positive", removable=false,
        level_min_offset=0, ignore_upper_cap=true
    },
    greedy = {
        id="greedy", name="贪财", type="positive", removable=true,
        level_min_offset=-1
    },
    hunt_specialist = {
        id="hunt_specialist", name="讨伐专精", type="positive", removable=false,
        prefer_quest_type="hunt", stat_effects = { hunt_atk_mult=1.10 }
    },
    explorer = {
        id="explorer", name="探索者", type="positive", removable=false,
        prefer_quest_type="explore", stat_effects = { explore_movespeed_mult=1.15 }
    },
    guardian_instinct = {
        id="guardian_instinct", name="护卫直觉", type="positive", removable=false,
        prefer_quest_type="escort", stat_effects = { escort_dmg_taken_mult=0.90 }
    },
    inspiring = {
        id="inspiring", name="鼓舞", type="positive", removable=false,
        stat_effects = { ally_atk_mult=1.05 }
    },
    tenacious = {
        id="tenacious", name="坚韧", type="positive", removable=false,
        stat_effects = { first_aid_roll_bonus=0.15, casualty_roll_bonus=0.05 }
    },
    fast_recovery = {
        id="fast_recovery", name="快速恢复", type="positive", removable=true,
        stat_effects = { rest_duration_mult=0.70 }
    },
    lucky = {
        id="lucky", name="幸运", type="positive", removable=true,
        stat_effects = { casualty_roll_bonus=0.05, positive_trigger_rate_bonus=0.10 }
    },
    -- 负面特质
    heartbroken = {
        id="heartbroken", name="心灰意冷", type="negative", removable=true,
        reject_all_quests_days=3  -- 3游戏日内拒绝所有任务
    },
    traumatized = {
        id="traumatized", name="怀疮", type="negative", removable=true,
        reject_quest_types={"hunt"}
    },
    acrophobia = {
        id="acrophobia", name="恐高", type="negative", removable=true,
        reject_quest_types={"mountain","aerial"}
    },
    social_anxiety = {
        id="social_anxiety", name="社恐", type="negative", removable=true,
        reject_quest_types={"escort","diplomatic"}
    },
    proud = {
        id="proud", name="骄傲", type="negative", removable=true,
        level_min_offset=1
    },
    cowardly = {
        id="cowardly", name="懦弱", type="negative", removable=true,
        caps_at_own_rank=true
    },
    ptsd = {
        id="ptsd", name="应激障碍", type="negative", removable=true,
        stat_effects = { trigger_flee_on_terrain=true, triggered_combat_mult=0.80 }
    },
    fragile = {
        id="fragile", name="脆弱", type="negative", removable=true,
        stat_effects = { hp_mult=0.90, casualty_roll_bonus=-0.10 }
    },
    alcoholic = {
        id="alcoholic", name="酗酒", type="negative", removable=true,
        random_miss_registration=true, stat_effects = { skill_hit_mult=0.95 }
    },
    suspicious = {
        id="suspicious", name="多疑", type="negative", removable=true,
        multiparty_signup_weight=0.50
    },
    coward_flee = {
        id="coward_flee", name="贪生怕死", type="negative", removable=true,
        flee_below_hp_pct=0.30
    },
    paranoid = {
        id="paranoid", name="偏执", type="negative", removable=false,
        reject_profession_in_party=true
    },
    quitter = {
        id="quitter", name="放弃癖", type="negative", removable=true,
        abort_bonus_chance=0.10
    },
    shadow = {
        id="shadow", name="阴影", type="negative", removable=true,
        post_wipe_refuse_days=4
    },
    self_doubt = {
        id="self_doubt", name="自我怀疑", type="negative", removable=true,
        stat_effects = { skill_dmg_mult=0.90 }
    },
    trauma_response = {
        id="trauma_response", name="创伤应激", type="negative", removable=true,
        reject_last_failed_quest_type=true,
        stat_effects = { related_combat_mult=0.85 }
    },
}

-- Separate pools for positive/negative triggering
local POS_POOL = {}
local NEG_POOL = {}
for id, t in pairs(M.CATALOG) do
    if t.type == "positive" then POS_POOL[#POS_POOL+1] = id
    else NEG_POOL[#NEG_POOL+1] = id end
end

-- Base trigger rates
local POSITIVE_RATE = 0.25
local NEGATIVE_RATE = 0.40

-- ── Internal helpers ──────────────────────────────────────────────────────

local function find_removable_index(traits)
    for i, t in ipairs(traits) do
        if M.CATALOG[t] and M.CATALOG[t].removable then return i end
    end
    return nil
end

local function pick_random_new(pool, existing_set)
    -- Fisher-Yates shuffle, pick first not in existing_set
    local candidates = {}
    for _, id in ipairs(pool) do
        if not existing_set[id] then candidates[#candidates+1] = id end
    end
    if #candidates == 0 then return nil end
    return candidates[math.random(#candidates)]
end

-- ── Public API ────────────────────────────────────────────────────────────

--- Add a trait to an adventurer. Returns true if added, false if blocked.
---@param adv_id string
---@param trait_id string
---@return boolean
function M.add_trait(adv_id, trait_id)
    local adv = AdvData.get(adv_id)
    if not adv or not M.CATALOG[trait_id] then return false end

    -- Build existing set
    local existing = {}
    for _, t in ipairs(adv.traits) do existing[t] = true end
    if existing[trait_id] then return false end  -- already has it

    -- Cap check
    if #adv.traits >= 6 then
        local ri = find_removable_index(adv.traits)
        if not ri then return false end  -- all permanent, blocked
        table.remove(adv.traits, ri)    -- evict one removable
    end

    adv.traits[#adv.traits+1] = trait_id
    return true
end

--- Check if adventurer has a specific trait
---@param adv_id string
---@param trait_id string
---@return boolean
function M.has_trait(adv_id, trait_id)
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    for _, t in ipairs(adv.traits) do
        if t == trait_id then return true end
    end
    return false
end

--- Get the net level_min_offset from all current traits
---@param adv_id string
---@return integer  (negative = more tolerant, positive = more selective)
function M.get_level_min_offset(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return 0 end
    local offset = 0
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def and def.level_min_offset then
            offset = offset + def.level_min_offset
        end
    end
    return offset
end

--- Returns the max rank cap imposed by traits (nil = no cap)
---@param adv_id string
---@return integer|nil
function M.get_max_rank_cap(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return nil end
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def and def.caps_at_own_rank then return adv.rank end
    end
    return nil
end

--- Returns true if this adventurer's traits reject the given quest type
---@param adv_id string
---@param quest_type string
---@return boolean
function M.rejects_quest_type(adv_id, quest_type)
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def then
            -- heartbroken: refuse all if days remaining
            if def.reject_all_quests_days and (adv.heartbroken_days_left or 0) > 0 then
                return true
            end
            -- specific type rejection
            if def.reject_quest_types then
                for _, rt in ipairs(def.reject_quest_types) do
                    if rt == quest_type then return true end
                end
            end
        end
    end
    return false
end

--- Trigger a negative trait roll. Returns true if a trait was added.
---@param adv_id string
---@return boolean
function M.trigger_negative_roll(adv_id)
    if math.random() > NEGATIVE_RATE then return false end
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    local existing = {}
    for _, t in ipairs(adv.traits) do existing[t] = true end
    local chosen = pick_random_new(NEG_POOL, existing)
    if not chosen then return false end
    return M.add_trait(adv_id, chosen)
end

--- Trigger a positive trait roll. Returns true if a trait was added.
---@param adv_id string
---@return boolean
function M.trigger_positive_roll(adv_id)
    -- lucky trait boosts positive rate
    local rate = POSITIVE_RATE
    if M.has_trait(adv_id, "lucky") then rate = rate + 0.10 end
    if math.random() > rate then return false end
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    local existing = {}
    for _, t in ipairs(adv.traits) do existing[t] = true end
    local chosen = pick_random_new(POS_POOL, existing)
    if not chosen then return false end
    return M.add_trait(adv_id, chosen)
end

--- Get a stat multiplier from all traits. key examples: "hp_mult", "atk_mult", "casualty_roll_bonus"
--- Returns the product of all matching multipliers (additive bonuses are summed, not multiplied).
---@param adv_id string
---@param stat_key string
---@return number
function M.get_stat_value(adv_id, stat_key)
    local adv = AdvData.get(adv_id)
    if not adv then return 1.0 end
    local total = 0.0
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def and def.stat_effects and def.stat_effects[stat_key] then
            total = total + def.stat_effects[stat_key]
        end
    end
    -- For bonus fields (_bonus suffix), return sum; for mult fields, base=1.0+sum
    if stat_key:find("_bonus$") then return total end
    return 1.0 + total  -- e.g. atk_mult: base 1.0 + accumulated deltas
end

return M
```

- [ ] Create `guild/trait_system.lua` with the content above

### Step 1.4: Run tests and verify they pass

Press T key in-game.
Expected: All `TraitSystem Tests` lines show `[TEST PASS]`

- [ ] Confirm all TraitSystem tests pass

### Step 1.5: Commit

```bash
git add guild/trait_system.lua guild_test.lua
git commit -m "feat(guild): add trait_system module with catalog and roll logic"
```

- [ ] Commit

---

## Task 2: Update `adventurer_data.lua` — Add Trait/State Fields, Remove Loyalty

**Files:**
- Modify: `guild/adventurer_data.lua`
- Modify: `guild_test.lua` (update existing adventurer tests)

### Step 2.1: Write failing test for new adventurer fields

Add to `run_adventurer_tests()` in `guild_test.lua`, after the existing assertions:

```lua
    -- New V2 fields
    local adv_v2 = AdvData.create("V2Test", "mage", "C")
    assert_eq("new adv has traits list", type(adv_v2.traits) == "table", true)
    assert_eq("new adv traits empty", #adv_v2.traits, 0)
    assert_eq("new adv resting_days=0", adv_v2.resting_days, 0)
    assert_eq("new adv vacation_days=0", adv_v2.vacation_days, 0)
    assert_eq("new adv heartbroken_days_left=0", adv_v2.heartbroken_days_left, 0)
    -- loyalty field should not exist
    assert_eq("no loyalty field", adv_v2.loyalty, nil)

    -- tick_daily: resting and vacation counts down
    adv_v2.resting_days = 3
    AdvData.tick_daily()
    assert_eq("resting_days decrements", AdvData.get(adv_v2.id).resting_days, 2)

    adv_v2.resting_days = 0
    adv_v2.vacation_days = 2
    AdvData.tick_daily()
    assert_eq("vacation_days decrements", AdvData.get(adv_v2.id).vacation_days, 1)

    -- is_available: false when resting or on vacation
    adv_v2.resting_days = 1
    adv_v2.vacation_days = 0
    assert_eq("not available while resting", AdvData.is_available(adv_v2.id), false)
    adv_v2.resting_days = 0
    adv_v2.vacation_days = 1
    assert_eq("not available while on vacation", AdvData.is_available(adv_v2.id), false)
    adv_v2.vacation_days = 0
    adv_v2.is_on_quest = false
    assert_eq("available when free", AdvData.is_available(adv_v2.id), true)
```

- [ ] Add V2 field tests to `run_adventurer_tests()` in `guild_test.lua`

### Step 2.2: Run test to verify failure

Expected: `no loyalty field` FAIL (loyalty=60 not nil), and trait/resting fields missing.

- [ ] Confirm tests fail as expected

### Step 2.3: Update `guild/adventurer_data.lua`

Make these targeted changes:

**In `M.create()`**, replace the `loyalty = 60` line and add new fields:

```lua
    -- REMOVE: loyalty = 60,
    -- ADD:
    traits = {},
    resting_days = 0,       -- days remaining in medical rest (cannot accept quests)
    vacation_days = 0,      -- days remaining in mental break (refuses quests)
    heartbroken_days_left = 0, -- days remaining on "心灰意冷" quest refusal
    -- REMOVE: idle_days = 0,
```

**Delete these entire functions:**
- `M.change_loyalty(id, delta)`
- `M.is_wavering(id)`
- `M.check_departure(id)`
- `M.tick_idle_penalty()`
- `M.reset_idle(id)`

**Add new functions:**

```lua
--- Returns true if adventurer can accept quests right now
---@param id string
---@return boolean
function M.is_available(id)
    local adv = _adventurers[id]
    if not adv then return false end
    if adv.is_on_quest then return false end
    if adv.resting_days > 0 then return false end
    if adv.vacation_days > 0 then return false end
    return true
end

--- Called once per game day. Decrements rest/vacation counters for all adventurers.
function M.tick_daily()
    for _, adv in pairs(_adventurers) do
        if adv.resting_days > 0 then
            adv.resting_days = adv.resting_days - 1
        elseif adv.vacation_days > 0 then
            adv.vacation_days = adv.vacation_days - 1
        end
        if adv.heartbroken_days_left > 0 then
            adv.heartbroken_days_left = adv.heartbroken_days_left - 1
        end
    end
end
```

- [ ] Apply all changes to `guild/adventurer_data.lua` as described

### Step 2.4: Run tests and verify they pass

Expected: All adventurer V2 field tests show `[TEST PASS]`

- [ ] Confirm tests pass

### Step 2.5: Commit

```bash
git add guild/adventurer_data.lua guild_test.lua
git commit -m "refactor(guild): replace loyalty/idle system with traits and rest/vacation state"
```

- [ ] Commit

---

## Task 3: Create `casualty.lua` — Death Judgment Chain

**Files:**
- Create: `guild/casualty.lua`
- Modify: `guild_test.lua` (add casualty tests)

### Step 3.1: Write failing tests for casualty

Add to `guild_test.lua`:

```lua
local Casualty = require 'guild.casualty'

local function run_casualty_tests()
    log.info("=== Casualty Tests ===")
    AdvData.reset()

    -- 1. do_casualty_roll: base 60% survival, test return type
    local adv = AdvData.create("CasTester", "warrior", "C")
    local survived = Casualty.do_casualty_roll(adv.id, 4)  -- task rank = C(4)
    assert_eq("casualty_roll returns bool", type(survived) == "boolean", true)

    -- 2. if survived, adventurer enters resting state
    AdvData.reset()
    local adv2 = AdvData.create("Survivor", "warrior", "C")
    -- Force survival by overriding math.random temporarily is complex; instead
    -- test that enter_rest() sets resting_days correctly
    Casualty.enter_rest(adv2.id)
    assert_eq("resting_days set after enter_rest", AdvData.get(adv2.id).resting_days > 0, true)
    assert_eq("resting_days in range 2-4", AdvData.get(adv2.id).resting_days >= 2, true)

    -- 3. trigger_vacation_check: 50% chance, sets vacation_days 1-2
    AdvData.reset()
    local adv3 = AdvData.create("VacTest", "ranger", "B")
    Casualty.trigger_vacation_check(adv3.id)
    local vd = AdvData.get(adv3.id).vacation_days
    assert_eq("vacation_days is 0 or 1-2", vd >= 0 and vd <= 2, true)

    -- 4. do_first_aid_roll returns boolean
    AdvData.reset()
    local cleric = AdvData.create("Cleric", "priest", "C")
    local patient = AdvData.create("Patient", "warrior", "C")
    local aid_ok = Casualty.do_first_aid_roll(cleric.id, patient.id)
    assert_eq("first_aid_roll returns bool", type(aid_ok) == "boolean", true)

    log.info("=== Casualty Tests Done ===")
end
```

Add `run_casualty_tests()` to the T-key handler.

- [ ] Add casualty tests to `guild_test.lua`

### Step 3.2: Verify tests fail

Expected: `module 'guild.casualty' not found`

- [ ] Confirm failure

### Step 3.3: Create `guild/casualty.lua`

```lua
-- guild/casualty.lua
-- 伤亡判定链：存活/死亡判定、急救判定、修养/休假状态写入
local AdvData     = require 'guild.adventurer_data'
local TraitSystem = require 'guild.trait_system'

local M = {}

-- Base survival probability on casualty roll
local BASE_SURVIVAL_RATE = 0.60
-- Per-rank-tier bonus when adventurer rank > task rank
local PER_RANK_BONUS = 0.05
-- Base first-aid success rate (cleric)
local BASE_FIRST_AID_RATE = 0.50
-- Per-rank-tier bonus when cleric rank > patient rank
local PER_CLERIC_RANK_BONUS = 0.10
-- Rest duration range (game days)
local REST_MIN = 2
local REST_MAX = 4
-- Vacation probability and range
local VACATION_CHANCE = 0.50
local VACATION_MIN = 1
local VACATION_MAX = 2

--- Calculate survival probability for an adventurer given the task rank
---@param adv_id string
---@param task_rank_int integer
---@return number  probability in [0, 1]
local function calc_survival_rate(adv_id, task_rank_int)
    local adv = AdvData.get(adv_id)
    if not adv then return 0 end
    local rate = BASE_SURVIVAL_RATE
    -- Rank bonus: each level above task rank adds 5%
    local rank_diff = adv.rank - task_rank_int
    if rank_diff > 0 then rate = rate + rank_diff * PER_RANK_BONUS end
    -- Trait bonuses (casualty_roll_bonus is additive)
    rate = rate + TraitSystem.get_stat_value(adv_id, "casualty_roll_bonus")
    return math.max(0, math.min(1, rate))
end

--- Perform the casualty survival roll.
--- On survival: calls enter_rest(). On death: calls AdvData.remove().
---@param adv_id string
---@param task_rank_int integer
---@return boolean  true = survived (entered rest), false = permanently dead
function M.do_casualty_roll(adv_id, task_rank_int)
    local rate = calc_survival_rate(adv_id, task_rank_int)
    if math.random() <= rate then
        M.enter_rest(adv_id)
        return true
    else
        AdvData.remove(adv_id)
        return false
    end
end

--- Put an adventurer into medical rest (resting_days = random in [REST_MIN, REST_MAX]).
--- Marks is_on_quest = false so the adventurer leaves the active quest.
---@param adv_id string
function M.enter_rest(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return end
    adv.is_on_quest = false
    adv.resting_days = math.random(REST_MIN, REST_MAX)
end

--- After rest ends: 50% chance of entering vacation. Modifies vacation_days.
---@param adv_id string
function M.trigger_vacation_check(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return end
    if math.random() <= VACATION_CHANCE then
        adv.vacation_days = math.random(VACATION_MIN, VACATION_MAX)
    end
end

--- Calculate first-aid success rate for a cleric trying to save a patient
---@param cleric_id string
---@param patient_id string
---@return number
local function calc_first_aid_rate(cleric_id, patient_id)
    local cleric  = AdvData.get(cleric_id)
    local patient = AdvData.get(patient_id)
    if not cleric or not patient then return 0 end
    local rate = BASE_FIRST_AID_RATE
    local rank_diff = cleric.rank - patient.rank
    if rank_diff > 0 then rate = rate + rank_diff * PER_CLERIC_RANK_BONUS end
    -- Cleric's "tenacious" trait adds 15%
    rate = rate + TraitSystem.get_stat_value(cleric_id, "first_aid_roll_bonus")
    return math.max(0, math.min(1, rate))
end

--- Perform first-aid roll. On success: calls enter_rest(patient). On failure: runs casualty roll.
---@param cleric_id string
---@param patient_id string
---@param task_rank_int integer
---@return boolean  true = patient survived (in rest), false = patient dead
function M.do_first_aid_roll(cleric_id, patient_id, task_rank_int)
    local rate = calc_first_aid_rate(cleric_id, patient_id)
    if math.random() <= rate then
        M.enter_rest(patient_id)
        return true
    else
        return M.do_casualty_roll(patient_id, task_rank_int or 1)
    end
end

--- Process a character going down in a multi-person quest.
--- Finds the first living priest in the party, runs first-aid or direct casualty roll.
---@param patient_id string  the downed adventurer
---@param party_ids string[] all dispatched adventurer IDs (including patient)
---@param task_rank_int integer
---@return boolean  true = survived (rest), false = dead
function M.process_party_casualty(patient_id, party_ids, task_rank_int)
    -- Find first alive cleric in party (not the patient)
    local cleric_id = nil
    for _, id in ipairs(party_ids) do
        if id ~= patient_id then
            local adv = AdvData.get(id)
            if adv and adv.profession == "priest" and adv.is_on_quest then
                cleric_id = id
                break
            end
        end
    end
    if cleric_id then
        return M.do_first_aid_roll(cleric_id, patient_id, task_rank_int)
    else
        return M.do_casualty_roll(patient_id, task_rank_int)
    end
end

return M
```

- [ ] Create `guild/casualty.lua` with the content above

### Step 3.4: Run tests and verify they pass

- [ ] Confirm all Casualty tests pass

### Step 3.5: Commit

```bash
git add guild/casualty.lua guild_test.lua
git commit -m "feat(guild): add casualty module with death judgment and first-aid chain"
```

- [ ] Commit

---

## Task 4: Update `quest_board.lua` — Difficulty-Based Level Range

**Files:**
- Modify: `guild/quest_board.lua`
- Modify: `guild_test.lua` (update quest board tests)

### Step 4.1: Write failing tests for new board logic

Replace `run_quest_board_tests()` content in `guild_test.lua`:

```lua
local function run_quest_board_tests()
    log.info("=== Quest Board V2 Tests ===")
    AdvData.reset()
    QuestData.reset()
    QuestBoard.set_difficulty(3)  -- 普通: tolerance=3

    -- S-rank adventurer (rank=7), tolerance=3 → min task rank = 7-3 = 4 (C)
    local adv_s = AdvData.create("SRank", "warrior", "S")
    local q_c = QuestData.create("C级任务", 4, QuestData.TYPE.HUNT, nil)  -- rank=C(4)
    QuestData.post(q_c.id, 1.0)
    local pool = QuestBoard.collect_registrations(q_c.id)
    local found_s = false
    for _, id in ipairs(pool) do if id == adv_s.id then found_s = true end end
    assert_eq("S-rank accepts C task on normal difficulty", found_s, true)

    -- S-rank on hell difficulty (tolerance=0): only accepts S tasks
    QuestBoard.set_difficulty(5)  -- 地狱: tolerance=0
    pool = QuestBoard.collect_registrations(q_c.id)
    found_s = false
    for _, id in ipairs(pool) do if id == adv_s.id then found_s = true end end
    assert_eq("S-rank rejects C task on hell difficulty", found_s, false)

    -- F-rank can accept S task (no upper limit by default)
    QuestBoard.set_difficulty(3)
    AdvData.reset()
    QuestData.reset()
    local adv_f = AdvData.create("FRank", "ranger", "F")
    local q_s = QuestData.create("S级任务", 7, QuestData.TYPE.HUNT, nil)
    QuestData.post(q_s.id, 1.0)
    pool = QuestBoard.collect_registrations(q_s.id)
    local found_f = false
    for _, id in ipairs(pool) do if id == adv_f.id then found_f = true end end
    assert_eq("F-rank can accept S task (no upper limit)", found_f, true)

    -- "懦弱" trait: C-rank with cowardly cannot accept S task
    AdvData.reset()
    QuestData.reset()
    local adv_c = AdvData.create("Coward", "mage", "C")
    TraitSystem.add_trait(adv_c.id, "cowardly")
    local q_s2 = QuestData.create("S级任务2", 7, QuestData.TYPE.HUNT, nil)
    QuestData.post(q_s2.id, 1.0)
    pool = QuestBoard.collect_registrations(q_s2.id)
    local found_c = false
    for _, id in ipairs(pool) do if id == adv_c.id then found_c = true end end
    assert_eq("C-rank with cowardly rejects S task", found_c, false)

    -- Trait behavior gate: adventurer with "traumatized" rejects hunt quest
    AdvData.reset()
    QuestData.reset()
    local adv_t = AdvData.create("Traumatized", "warrior", "S")
    TraitSystem.add_trait(adv_t.id, "traumatized")
    local q_hunt = QuestData.create("讨伐任务", 5, QuestData.TYPE.HUNT, nil)
    QuestData.post(q_hunt.id, 1.0)
    pool = QuestBoard.collect_registrations(q_hunt.id)
    local found_t = false
    for _, id in ipairs(pool) do if id == adv_t.id then found_t = true end end
    assert_eq("traumatized adventurer rejects hunt", found_t, false)

    -- Adventurer in resting state cannot register
    AdvData.reset()
    QuestData.reset()
    local adv_r = AdvData.create("Resting", "warrior", "C")
    adv_r.resting_days = 2
    local q_norm = QuestData.create("普通任务", 3, QuestData.TYPE.EXPLORE, nil)
    QuestData.post(q_norm.id, 1.0)
    pool = QuestBoard.collect_registrations(q_norm.id)
    local found_r = false
    for _, id in ipairs(pool) do if id == adv_r.id then found_r = true end end
    assert_eq("resting adventurer cannot register", found_r, false)

    log.info("=== Quest Board V2 Tests Done ===")
end
```

- [ ] Replace `run_quest_board_tests()` in `guild_test.lua` with the new version above

### Step 4.2: Verify failure

Expected: `set_difficulty` not found error

- [ ] Confirm failure

### Step 4.3: Rewrite `guild/quest_board.lua`

```lua
-- guild/quest_board.lua
-- 报名 AI 模块 V2：基于难度容忍幅度的等级范围门槛 + 特质行为门槛
local AdvData     = require 'guild.adventurer_data'
local QuestData   = require 'guild.quest_data'
local TraitSystem = require 'guild.trait_system'

local M = {}

-- 游戏难度映射到容忍幅度（高等级角色愿意接受的最低等级差）
-- 难度1=简单 2=普通 3=困难 4=噩梦 5=地狱
local DIFFICULTY_TOLERANCE = { [1]=4, [2]=3, [3]=2, [4]=1, [5]=0 }

-- 当前游戏难度（默认普通）
local _difficulty = 2

--- 设置全局游戏难度（1~5）
---@param level integer  1=简单 2=普通 3=困难 4=噩梦 5=地狱
function M.set_difficulty(level)
    assert(DIFFICULTY_TOLERANCE[level], "invalid difficulty level: " .. tostring(level))
    _difficulty = level
end

--- 获取当前难度容忍幅度
---@return integer
function M.get_tolerance()
    return DIFFICULTY_TOLERANCE[_difficulty] or 3
end

--- 计算冒险者对某任务等级的可接范围
---@param adv_id string
---@return integer min_rank, integer|nil max_rank  (max_rank=nil 表示无上限)
function M.get_rank_range(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return 1, nil end
    local tolerance = M.get_tolerance()
    local offset    = TraitSystem.get_level_min_offset(adv_id)
    local min_rank  = math.max(1, adv.rank - tolerance + offset)
    local max_rank  = TraitSystem.get_max_rank_cap(adv_id)  -- nil or adv.rank
    return min_rank, max_rank
end

--- 对一个已挂牌任务执行报名 AI（四重门槛）
---@param quest_id string
---@return string[]  愿意报名的冒险者 ID 列表
function M.collect_registrations(quest_id)
    local quest = QuestData.get(quest_id)
    if not quest or quest.status ~= QuestData.STATUS.POSTED then return {} end

    local pool = {}
    for _, adv in ipairs(AdvData.get_all()) do
        -- 门槛1: 空闲检查（不在任务中、不在修养/休假状态）
        if not AdvData.is_available(adv.id) then goto continue end

        -- 门槛2: 等级范围检查
        local min_r, max_r = M.get_rank_range(adv.id)
        if quest.rank < min_r then goto continue end
        if max_r and quest.rank > max_r then goto continue end

        -- 门槛3: 特质行为检查（是否有"拒绝此类任务"特质）
        if TraitSystem.rejects_quest_type(adv.id, quest.quest_type) then goto continue end

        pool[#pool+1] = adv.id
        ::continue::
    end

    quest.registered_ids = pool
    return pool
end

--- 查询当前报名池（不重新计算）
---@param quest_id string
---@return string[]
function M.get_pool(quest_id)
    local quest = QuestData.get(quest_id)
    if not quest then return {} end
    return quest.registered_ids or {}
end

return M
```

- [ ] Overwrite `guild/quest_board.lua` with the content above

### Step 4.4: Run tests and verify they pass

- [ ] Confirm all Quest Board V2 tests pass

### Step 4.5: Commit

```bash
git add guild/quest_board.lua guild_test.lua
git commit -m "feat(guild): rewrite quest board with difficulty-based level range system"
```

- [ ] Commit

---

## Task 5: Update `quest_execution.lua` — Death Triggers Casualty Chain

**Files:**
- Modify: `guild/quest_execution.lua`

### Step 5.1: Update the death handler in `M.start()`

Replace the death handler block inside `M.start()` (the `local death_handler = function(...)` block) with:

```lua
    -- Import casualty module
    local Casualty = require 'guild.casualty'

    local death_handler = function(_, dead_unit)
        if not _executions[quest_id] then return end
        -- Identify which adventurer died
        local downed_id = nil
        for adv_id, u in pairs(ctx.adv_units) do
            if u == dead_unit then
                downed_id = adv_id
                ctx.adv_units[adv_id] = nil
                break
            end
        end
        if not downed_id then return end

        -- Run casualty chain (single or multi-person)
        local is_single = (#quest.dispatched_ids == 1)
        if is_single then
            -- Single: casualty roll; on death → immediate task failure
            local survived = Casualty.do_casualty_roll(downed_id, quest.rank)
            if not survived then
                M._finish(quest_id, "wipe")
                return
            end
            -- Survived: enter rest, trigger negative trait (done in settlement)
        else
            -- Multi: first-aid or direct casualty
            Casualty.process_party_casualty(downed_id, quest.dispatched_ids, quest.rank)
        end

        -- Check if all party members are now dead/resting (not in quest)
        local any_still_active = false
        for _, u in pairs(ctx.adv_units) do
            if u then any_still_active = true; break end
        end
        if not any_still_active then
            M._finish(quest_id, "wipe")
        end
    end
```

Also: remove the old single-line `M.mark_fail(quest_id, is_heavy)` function since `heavy_fail` outcome is no longer used. Update the comments at the top of the file.

- [ ] Apply changes to `guild/quest_execution.lua` as described

### Step 5.2: Commit

```bash
git add guild/quest_execution.lua
git commit -m "feat(guild): wire casualty chain into quest execution death handler"
```

- [ ] Commit

---

## Task 6: Update `quest_dispatch.lua` — Remove Probability Layer

**Files:**
- Modify: `guild/quest_dispatch.lua`

### Step 6.1: Delete the three probability functions

Remove these three functions entirely from `quest_dispatch.lua`:
- `M.calc_base_fail_prob(task_rank_int, party_avg_rank)`
- `M.calc_equip_delta(equip_avg_rank, task_rank_int)`
- `M.calc_final_fail_prob(task_rank_int, adv_ids, equip_avg_rank)`

Also remove the `local Dispatch = require 'guild.quest_dispatch'` import from `quest_settlement.lua` (verified next task). Keep `M.calc_party_avg_rank` and `M.dispatch` as they are still used.

Update the file header comment to:

```lua
-- guild/quest_dispatch.lua
-- 派遣模块：队伍平均等级计算、验证报名资格、执行派遣
-- 注：V2 删除概率失败计算层，成败由实时执行决定
```

- [ ] Delete the three probability functions from `guild/quest_dispatch.lua`
- [ ] Update the file header comment

### Step 6.2: Commit

```bash
git add guild/quest_dispatch.lua
git commit -m "refactor(guild): remove probability failure calculation from quest_dispatch"
```

- [ ] Commit

---

## Task 7: Update `quest_settlement.lua` — Simplify Branches + Trait Rolls

**Files:**
- Modify: `guild/quest_settlement.lua`
- Modify: `guild_test.lua` (update settlement tests)

### Step 7.1: Write failing tests for new settlement

Replace `run_settlement_tests()` in `guild_test.lua`:

```lua
local function run_settlement_tests()
    log.info("=== Settlement V2 Tests ===")
    AdvData.reset()
    QuestData.reset()

    -- Test 1: success settlement — adventurer freed, xp granted
    local adv1 = AdvData.create("Hero", "warrior", "C")
    adv1.is_on_quest = true
    local q1 = QuestData.create("成功任务", 3, QuestData.TYPE.HUNT, nil)
    QuestData.post(q1.id, 1.0)
    q1.dispatched_ids = {adv1.id}
    q1.equipment_ids = {}
    QuestData.set_status(q1.id, QuestData.STATUS.DISPATCHED)

    local r1 = Settlement.settle(q1.id, "success")
    assert_eq("success: outcome", r1.outcome, "success")
    assert_eq("success: gold_reward > 0", r1.gold_reward > 0, true)
    assert_eq("success: adv freed", AdvData.get(adv1.id).is_on_quest, false)
    -- xp should be added (base 450 * 1.0 mult for C-rank on C-task)
    assert_eq("success: xp added", AdvData.get(adv1.id).xp > 0, true)
    -- no lost adventurers
    assert_eq("success: no losses", #r1.lost_adv_ids, 0)
    -- no loyalty_changes field (V2 removes this)
    assert_eq("success: no loyalty_changes", r1.loyalty_changes, nil)

    -- Test 2: abort settlement — negative trait roll triggered, no gold
    AdvData.reset()
    QuestData.reset()
    local adv2 = AdvData.create("Quitter", "ranger", "B")
    adv2.is_on_quest = true
    local q2 = QuestData.create("放弃任务", 4, QuestData.TYPE.EXPLORE, nil)
    QuestData.post(q2.id, 1.0)
    q2.dispatched_ids = {adv2.id}
    q2.equipment_ids = {}
    QuestData.set_status(q2.id, QuestData.STATUS.DISPATCHED)

    local r2 = Settlement.settle(q2.id, "abort")
    assert_eq("abort: outcome", r2.outcome, "abort")
    assert_eq("abort: no gold", r2.gold_reward, 0)
    assert_eq("abort: adv freed", AdvData.get(adv2.id).is_on_quest, false)
    assert_eq("abort: no losses", #r2.lost_adv_ids, 0)

    -- Test 3: wipe — all dispatched adventurers permanently removed
    AdvData.reset()
    QuestData.reset()
    local adv3a = AdvData.create("Martyr1", "warrior", "C")
    local adv3b = AdvData.create("Martyr2", "mage", "C")
    local bystander = AdvData.create("Watcher", "ranger", "F")
    adv3a.is_on_quest = true
    adv3b.is_on_quest = true
    local q3 = QuestData.create("全灭任务", 5, QuestData.TYPE.HUNT, nil)
    QuestData.post(q3.id, 1.0)
    q3.dispatched_ids = {adv3a.id, adv3b.id}
    q3.equipment_ids = {"eq_001"}
    QuestData.set_status(q3.id, QuestData.STATUS.DISPATCHED)

    local r3 = Settlement.settle(q3.id, "wipe")
    assert_eq("wipe: 2 lost", #r3.lost_adv_ids, 2)
    assert_eq("wipe: equip lost", #r3.lost_equip_ids, 1)
    assert_eq("wipe: adv3a removed", AdvData.get(adv3a.id), nil)
    assert_eq("wipe: adv3b removed", AdvData.get(adv3b.id), nil)
    -- bystander still exists (not removed, trait roll is probabilistic)
    assert_eq("wipe: bystander still alive", AdvData.get(bystander.id) ~= nil, true)

    log.info("=== Settlement V2 Tests Done ===")
end
```

- [ ] Replace `run_settlement_tests()` in `guild_test.lua` with the V2 version

### Step 7.2: Verify failure

Expected: `loyalty_changes` field exists (V2 removes it), test fails.

- [ ] Confirm failure

### Step 7.3: Rewrite `guild/quest_settlement.lua`

```lua
-- guild/quest_settlement.lua
-- 结算模块 V2：三分支结算（success/abort/wipe），触发特质判定
-- 注：V2 删除 light_fail/heavy_fail 概率分支，伤亡由 casualty.lua 实时处理
local AdvData     = require 'guild.adventurer_data'
local QuestData   = require 'guild.quest_data'
local TraitSystem = require 'guild.trait_system'
local Casualty    = require 'guild.casualty'

local M = {}

-- 任务基础经验奖励（按任务等级整数值）
local BASE_XP = {
    [1]=100, [2]=200, [3]=450, [4]=900, [5]=1800, [6]=3500, [7]=7000
}

---@class SettlementResult
---@field outcome string           "success"|"abort"|"wipe"
---@field gold_reward integer      玩家获得金币（仅 success 时非0）
---@field lost_adv_ids string[]    永久失去的冒险者 ID 列表
---@field lost_equip_ids string[]  损毁装备 ID 列表

--- 对所有参与者触发结算后特质判定
---@param adv_ids string[]
---@param is_success boolean
---@param is_abort boolean
local function run_post_settlement_trait_rolls(adv_ids, is_success, is_abort)
    for _, adv_id in ipairs(adv_ids) do
        if AdvData.get(adv_id) then  -- may have been removed if dead
            if is_success then
                TraitSystem.trigger_positive_roll(adv_id)
                TraitSystem.trigger_negative_roll(adv_id)  -- trauma even on success
            elseif is_abort then
                -- Abort carries higher negative rate; trigger twice
                TraitSystem.trigger_negative_roll(adv_id)
                TraitSystem.trigger_negative_roll(adv_id)
            else
                TraitSystem.trigger_negative_roll(adv_id)
            end
            -- Adventurers in rest state get an extra negative roll
            local adv = AdvData.get(adv_id)
            if adv and adv.resting_days > 0 then
                TraitSystem.trigger_negative_roll(adv_id)
                Casualty.trigger_vacation_check(adv_id)
            end
        end
    end
end

--- Execute settlement for a quest
---@param quest_id string
---@param outcome string  "success"|"abort"|"wipe"
---@return SettlementResult
function M.settle(quest_id, outcome)
    local quest = QuestData.get(quest_id)
    local result = {
        outcome      = outcome,
        gold_reward  = 0,
        lost_adv_ids = {},
        lost_equip_ids = {},
    }
    if not quest then return result end

    local dispatched = quest.dispatched_ids
    local equip_ids  = quest.equipment_ids

    -- ── 成功 ─────────────────────────────────────────────────────────────
    if outcome == "success" then
        result.gold_reward = QuestData.total_reward(quest_id)

        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then
                adv.is_on_quest = false
                -- 经验奖励
                local xp_base = BASE_XP[quest.rank] or 100
                local mult    = AdvData.xp_multiplier(quest.rank, adv.rank)
                AdvData.add_xp(adv_id, math.floor(xp_base * mult))
            end
        end

        run_post_settlement_trait_rolls(dispatched, true, false)
        QuestData.set_status(quest_id, QuestData.STATUS.SUCCEEDED)

    -- ── 主动放弃 ─────────────────────────────────────────────────────────
    elseif outcome == "abort" then
        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then adv.is_on_quest = false end
        end
        -- No gold, no XP
        run_post_settlement_trait_rolls(dispatched, false, true)
        QuestData.set_status(quest_id, QuestData.STATUS.ABORTED)

    -- ── 全灭 ─────────────────────────────────────────────────────────────
    elseif outcome == "wipe" then
        for _, adv_id in ipairs(dispatched) do
            result.lost_adv_ids[#result.lost_adv_ids+1] = adv_id
            AdvData.remove(adv_id)
        end
        result.lost_equip_ids = equip_ids

        -- Bystanders (non-dispatched adventurers) get a negative trait roll
        local dispatched_set = {}
        for _, did in ipairs(dispatched) do dispatched_set[did] = true end
        for _, adv in ipairs(AdvData.get_all()) do
            if not dispatched_set[adv.id] then
                TraitSystem.trigger_negative_roll(adv.id)
            end
        end

        QuestData.set_status(quest_id, QuestData.STATUS.FAILED)
    end

    return result
end

return M
```

- [ ] Overwrite `guild/quest_settlement.lua` with the content above

### Step 7.4: Run tests and verify they pass

- [ ] Confirm all Settlement V2 tests pass

### Step 7.5: Commit

```bash
git add guild/quest_settlement.lua guild_test.lua
git commit -m "refactor(guild): simplify settlement to 3 branches with post-settlement trait rolls"
```

- [ ] Commit

---

## Task 8: Final Integration — Wire `tick_daily` and Cleanup

**Files:**
- Modify: `guild/quest_manager.lua` (replace `tick_idle_penalty` with `tick_daily`)
- Modify: `guild_test.lua` (add `require` for new modules at top, wire all new test calls)

### Step 8.1: Update `quest_manager.lua`

Find the call to `AdvData.tick_idle_penalty()` in the game-day timer and replace it with `AdvData.tick_daily()`. Update the header comment.

```lua
-- In the game-day timer callback, replace:
--   AdvData.tick_idle_penalty()
-- With:
    AdvData.tick_daily()
```

- [ ] Make this one-line change in `guild/quest_manager.lua`

### Step 8.2: Update `guild_test.lua` requires and T-key handler

At the top of `guild_test.lua`, add the new requires after existing ones:

```lua
local TraitSystem = require 'guild.trait_system'
local Casualty    = require 'guild.casualty'
```

In the T-key handler, ensure all new test functions are called:

```lua
run_trait_system_tests()
run_casualty_tests()
run_adventurer_tests()
run_quest_data_tests()
run_quest_board_tests()
run_dispatch_tests()
run_execution_tests()
run_settlement_tests()
run_event_card_tests()
```

- [ ] Add requires and wire all test calls in `guild_test.lua`

### Step 8.3: Run the full test suite

Press T key in-game.
Expected: All test sections show `[TEST PASS]`, no `[TEST FAIL]` lines.

- [ ] Confirm full test suite passes

### Step 8.4: Final commit

```bash
git add guild/quest_manager.lua guild_test.lua
git commit -m "feat(guild): complete V2 integration - wire tick_daily and full test suite"
```

- [ ] Commit

---

## Summary

After all tasks complete, the guild system will:
- Use real-time MOBA unit simulation for task outcomes
- Run injury/death judgment chains via `casualty.lua` when units die
- Gate quest registrations by difficulty-based level range + trait behavior filters
- Replace loyalty with a trait system that affects both stats and behavior
- Remove all probability-based failure calculations from `quest_dispatch.lua`
- Reduce settlement to 3 clean branches: success / abort / wipe
