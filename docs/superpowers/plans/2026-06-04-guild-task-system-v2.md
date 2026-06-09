# Guild Task System V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the guild task system to use real-time MOBA-unit simulation, a difficulty-based level acceptance range, and a trait system that replaces loyalty.

**Architecture:** Two new modules (`trait_system.lua`, `casualty.lua`) are added; four existing modules are modified (`adventurer_data`, `quest_board`, `quest_execution`, `quest_settlement`); and `quest_dispatch`'s probability layer is deleted. The `guild_test.lua` test suite is extended throughout.

**Tech Stack:** Lua 5.4, Y3 engine runtime APIs (`y3.unit`, `y3.timer`, `y3.game:event`), existing guild module structure.

**Spec:** [docs/superpowers/specs/2026-06-04-guild-task-system-v2-design.md](../specs/2026-06-04-guild-task-system-v2-design.md)

**Deferred:** Equipment routing into Y3 unit stats (Spec §2.2, "装备直接影响角色战斗属性") requires Y3 item API integration not yet available. This is tracked as a follow-up task once the item library module exists.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `guild/adventurer_data.lua` | **Modify** | Remove loyalty fields; add `traits[]`, `resting_days`, `vacation_days` |
| `guild/trait_system.lua` | **Create** | Trait catalog, trigger rolls, effect query, trait-list + signup weight |
| `guild/casualty.lua` | **Create** | Death/injury judgment chain, first-aid roll, rest/vacation state |
| `guild/quest_board.lua` | **Modify** | Difficulty-based level range, trait behavior gate, bounty-weight ordering |
| `guild/quest_execution.lua` | **Modify** | Death event calls `casualty.lua` chain; all-dead check triggers task failure |
| `guild/quest_dispatch.lua` | **Modify** | Delete `calc_base_fail_prob`, `calc_equip_delta`, `calc_final_fail_prob` |
| `guild/quest_settlement.lua` | **Modify** | Remove heavy_fail/probability branches; add post-settlement trait roll calls |
| `guild_test.lua` | **Modify** | Add tests for all new modules and modified logic |

---

## Task 1: Update `adventurer_data.lua` — Add Trait/State Fields, Remove Loyalty

**Files:**
- Modify: `guild/adventurer_data.lua`
- Modify: `guild_test.lua` (add V2 field assertions to `run_adventurer_tests`)

### Step 1.1: Write failing tests for new adventurer fields

Add to `run_adventurer_tests()` in `guild_test.lua`, after the existing assertions:

```lua
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
```

- [ ] Add V2 field tests to `run_adventurer_tests()` in `guild_test.lua`

### Step 1.2: Run tests to verify failure

Expected: `no loyalty field` FAIL (loyalty=60 not nil), and `has traits list` FAIL.

- [ ] Confirm tests fail as expected

### Step 1.3: Update `guild/adventurer_data.lua`

**In `M.create()`**, replace `loyalty = 60` and `idle_days = 0` with new fields:

```lua
    -- Replace loyalty = 60 and idle_days = 0 with:
    traits = {},
    resting_days = 0,
    vacation_days = 0,
    heartbroken_days_left = 0,
```

**Delete these entire functions:**
- `M.change_loyalty(id, delta)`
- `M.is_wavering(id)`
- `M.check_departure(id)`
- `M.tick_idle_penalty()`
- `M.reset_idle(id)`

**Add these new functions before `M.reset()`:**

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

Also update the file header comment:

```lua
-- guild/adventurer_data.lua
-- 冒险者数据模块 V2：等级/经验/特质/修养/休假状态逻辑（V2 删除忠诚度系统）
```

- [ ] In `M.create()`, replace `loyalty = 60` and `idle_days = 0` with the four new fields shown above
- [ ] Delete the five functions: `change_loyalty`, `is_wavering`, `check_departure`, `tick_idle_penalty`, `reset_idle`
- [ ] Add `M.is_available` and `M.tick_daily` before `M.reset()` as shown above
- [ ] Update the file header comment

### Step 1.4: Run tests and verify they pass

Press T key in-game.
Expected: All adventurer V2 field tests show `[TEST PASS]`

- [ ] Confirm tests pass

### Step 1.5: Commit

```bash
git add guild/adventurer_data.lua guild_test.lua
git commit -m "refactor(guild): replace loyalty/idle system with traits and rest/vacation state"
```

- [ ] Commit

---

## Task 2: Create `trait_system.lua` — Catalog, Roll Logic, Signup Weight

**Files:**
- Create: `guild/trait_system.lua`
- Modify: `guild_test.lua` (add `run_trait_system_tests`)

### Step 2.1: Write failing tests for trait_system

Add this function to `guild_test.lua` (before the keyboard binding), and add `run_trait_system_tests()` to the T-key handler:

```lua
local TraitSystem = require 'guild.trait_system'

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

    log.info("=== TraitSystem Tests Done ===")
end
```

- [ ] Add `run_trait_system_tests` to `guild_test.lua` and wire into T-key handler

### Step 2.2: Verify tests fail

Expected: `module 'guild.trait_system' not found`

- [ ] Confirm failure

### Step 2.3: Create trait catalog in `guild/trait_system.lua`

Create the file with the CATALOG constant and pools only (no functions yet):

```lua
-- guild/trait_system.lua
-- 特质系统 V2：特质库、触发判定、效果查询、报名权重计算
local AdvData = require 'guild.adventurer_data'

local M = {}

-- ── 特质库 ──────────────────────────────────────────────────────────────────
M.CATALOG = {
    -- 正面特质 (12)
    battle_veteran      = { id="battle_veteran",      name="战场老兵",   type="positive", removable=false, stat_effects={atk_mult=0.10, crit_bonus=0.05} },
    near_death_survivor = { id="near_death_survivor",  name="九死一生",   type="positive", removable=false, stat_effects={hp_mult=0.15, casualty_roll_bonus=0.10} },
    brave               = { id="brave",               name="勇猛",      type="positive", removable=false, stat_effects={boss_dmg_mult=0.15} },
    fearless            = { id="fearless",            name="无畏",      type="positive", removable=false, ignore_upper_cap=true },
    greedy              = { id="greedy",              name="贪财",      type="positive", removable=true,  level_min_offset=-1 },
    hunt_specialist     = { id="hunt_specialist",     name="讨伐专精",   type="positive", removable=false, prefer_quest_type="hunt",    stat_effects={hunt_atk_mult=0.10} },
    explorer            = { id="explorer",            name="探索者",    type="positive", removable=false, prefer_quest_type="explore",  stat_effects={explore_movespeed_mult=0.15} },
    guardian_instinct   = { id="guardian_instinct",   name="护卫直觉",   type="positive", removable=false, prefer_quest_type="escort",  stat_effects={escort_dmg_taken_mult=-0.10} },
    inspiring           = { id="inspiring",           name="鼓舞",      type="positive", removable=false, stat_effects={ally_atk_mult=0.05} },
    tenacious           = { id="tenacious",           name="坚韧",      type="positive", removable=false, stat_effects={first_aid_roll_bonus=0.15, casualty_roll_bonus=0.05} },
    fast_recovery       = { id="fast_recovery",       name="快速恢复",   type="positive", removable=true,  stat_effects={rest_duration_mult=-0.30} },
    lucky               = { id="lucky",               name="幸运",      type="positive", removable=true,  stat_effects={casualty_roll_bonus=0.05, positive_trigger_rate_bonus=0.10} },
    -- 负面特质 (16)
    heartbroken    = { id="heartbroken",    name="心灰意冷",  type="negative", removable=true,  reject_all_quests_days=3 },
    traumatized    = { id="traumatized",    name="怀疮",     type="negative", removable=true,  reject_quest_types={"hunt"} },
    acrophobia     = { id="acrophobia",     name="恐高",     type="negative", removable=true,  reject_quest_types={"mountain","aerial"} },
    social_anxiety = { id="social_anxiety", name="社恐",     type="negative", removable=true,  reject_quest_types={"escort","diplomatic"} },
    proud          = { id="proud",          name="骄傲",     type="negative", removable=true,  level_min_offset=1 },
    cowardly       = { id="cowardly",       name="懦弱",     type="negative", removable=true,  caps_at_own_rank=true },
    ptsd           = { id="ptsd",           name="应激障碍",  type="negative", removable=true,  stat_effects={triggered_combat_mult=-0.20} },
    fragile        = { id="fragile",        name="脆弱",     type="negative", removable=true,  stat_effects={hp_mult=-0.10, casualty_roll_bonus=-0.10} },
    alcoholic      = { id="alcoholic",      name="酗酒",     type="negative", removable=true,  stat_effects={skill_hit_mult=-0.05} },
    suspicious     = { id="suspicious",     name="多疑",     type="negative", removable=true,  signup_weight_mult=0.50 },
    coward_flee    = { id="coward_flee",    name="贪生怕死",  type="negative", removable=true,  flee_below_hp_pct=0.30 },
    paranoid       = { id="paranoid",       name="偏执",     type="negative", removable=false, stat_effects={triggered_combat_mult=-0.05} },
    quitter        = { id="quitter",        name="放弃癖",   type="negative", removable=true },
    shadow         = { id="shadow",         name="阴影",     type="negative", removable=true,  post_wipe_refuse_days=4 },
    self_doubt     = { id="self_doubt",     name="自我怀疑",  type="negative", removable=true,  stat_effects={skill_dmg_mult=-0.10} },
    trauma_response= { id="trauma_response",name="创伤应激",  type="negative", removable=true,  reject_last_failed_quest_type=true, stat_effects={related_combat_mult=-0.15} },
}

local POS_POOL, NEG_POOL = {}, {}
for id, t in pairs(M.CATALOG) do
    if t.type == "positive" then POS_POOL[#POS_POOL+1] = id
    else NEG_POOL[#NEG_POOL+1] = id end
end

local POSITIVE_RATE = 0.25
local NEGATIVE_RATE = 0.40

return M
```

- [ ] Create `guild/trait_system.lua` with catalog content above

### Step 2.4: Add add/has/query functions to `guild/trait_system.lua`

Append before `return M`:

```lua
-- ── Internal ──────────────────────────────────────────────────────────────

local function find_removable_index(traits)
    for i, t in ipairs(traits) do
        if M.CATALOG[t] and M.CATALOG[t].removable then return i end
    end
    return nil
end

local function pick_random_new(pool, existing_set)
    local candidates = {}
    for _, id in ipairs(pool) do
        if not existing_set[id] then candidates[#candidates+1] = id end
    end
    if #candidates == 0 then return nil end
    return candidates[math.random(#candidates)]
end

-- ── Public API ────────────────────────────────────────────────────────────

function M.add_trait(adv_id, trait_id)
    local adv = AdvData.get(adv_id)
    if not adv or not M.CATALOG[trait_id] then return false end
    local existing = {}
    for _, t in ipairs(adv.traits) do existing[t] = true end
    if existing[trait_id] then return false end
    if #adv.traits >= 6 then
        local ri = find_removable_index(adv.traits)
        if not ri then return false end
        table.remove(adv.traits, ri)
    end
    adv.traits[#adv.traits+1] = trait_id
    return true
end

function M.has_trait(adv_id, trait_id)
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    for _, t in ipairs(adv.traits) do
        if t == trait_id then return true end
    end
    return false
end

function M.get_level_min_offset(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return 0 end
    local offset = 0
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def and def.level_min_offset then offset = offset + def.level_min_offset end
    end
    return offset
end

function M.get_max_rank_cap(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return nil end
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def and def.caps_at_own_rank then return adv.rank end
    end
    return nil
end

function M.rejects_quest_type(adv_id, quest_type)
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def then
            if def.reject_all_quests_days and (adv.heartbroken_days_left or 0) > 0 then
                return true
            end
            if def.reject_quest_types then
                for _, rt in ipairs(def.reject_quest_types) do
                    if rt == quest_type then return true end
                end
            end
        end
    end
    return false
end

--- Returns a signup weight multiplier for this adventurer on a given quest.
--- Base weight = bounty_mult. prefer_quest_type match adds 0.5. signup_weight_mult scales down.
---@param adv_id string
---@param quest_type string
---@param bounty_mult number
---@return number
function M.get_signup_weight(adv_id, quest_type, bounty_mult)
    local adv = AdvData.get(adv_id)
    if not adv then return 0 end
    local weight = bounty_mult
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def then
            if def.prefer_quest_type == quest_type then weight = weight + 0.5 end
            if def.signup_weight_mult then weight = weight * def.signup_weight_mult end
        end
    end
    return weight
end
```

- [ ] Append add/has/query functions to `guild/trait_system.lua`

### Step 2.5: Add trigger roll functions to `guild/trait_system.lua`

Append before `return M`:

```lua
function M.trigger_negative_roll(adv_id)
    return M.trigger_negative_roll_at_rate(adv_id, NEGATIVE_RATE)
end

--- Trigger a negative trait roll at a custom probability rate.
---@param adv_id string
---@param rate number  probability in [0,1]
---@return boolean
function M.trigger_negative_roll_at_rate(adv_id, rate)
    if math.random() > rate then return false end
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    local existing = {}
    for _, t in ipairs(adv.traits) do existing[t] = true end
    local chosen = pick_random_new(NEG_POOL, existing)
    if not chosen then return false end
    return M.add_trait(adv_id, chosen)
end

function M.trigger_positive_roll(adv_id)
    local rate = POSITIVE_RATE
    if M.has_trait(adv_id, "lucky") then
        rate = rate + (M.CATALOG.lucky.stat_effects.positive_trigger_rate_bonus or 0.10)
    end
    if math.random() > rate then return false end
    local adv = AdvData.get(adv_id)
    if not adv then return false end
    local existing = {}
    for _, t in ipairs(adv.traits) do existing[t] = true end
    local chosen = pick_random_new(POS_POOL, existing)
    if not chosen then return false end
    return M.add_trait(adv_id, chosen)
end

--- Accumulate a numeric stat value from all traits.
--- For "_bonus" suffix keys: returns sum of all matching values.
--- For other keys: returns 1.0 + sum (multiplicative base).
---@param adv_id string
---@param stat_key string
---@return number
function M.get_stat_value(adv_id, stat_key)
    local adv = AdvData.get(adv_id)
    if not adv then return stat_key:find("_bonus$") and 0.0 or 1.0 end
    local total = 0.0
    for _, t in ipairs(adv.traits) do
        local def = M.CATALOG[t]
        if def and def.stat_effects and def.stat_effects[stat_key] then
            total = total + def.stat_effects[stat_key]
        end
    end
    if stat_key:find("_bonus$") then return total end
    return 1.0 + total
end
```

- [ ] Append trigger and stat functions to `guild/trait_system.lua`

### Step 2.6: Run tests and verify they pass

Press T key in-game.
Expected: All `TraitSystem Tests` lines show `[TEST PASS]`

- [ ] Confirm all TraitSystem tests pass

### Step 2.7: Commit

```bash
git add guild/trait_system.lua guild_test.lua
git commit -m "feat(guild): add trait_system with catalog, rolls, and signup weight logic"
```

- [ ] Commit

---

## Task 3: Create `casualty.lua` — Death Judgment Chain

**Files:**
- Create: `guild/casualty.lua`
- Modify: `guild_test.lua` (add `run_casualty_tests`)

### Step 3.1: Write failing tests

Add to `guild_test.lua`:

```lua
local Casualty = require 'guild.casualty'

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

    log.info("=== Casualty Tests Done ===")
end
```

Add `run_casualty_tests()` to the T-key handler.

- [ ] Add `run_casualty_tests` to `guild_test.lua` and wire into T-key handler

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

local BASE_SURVIVAL_RATE   = 0.60
local PER_RANK_BONUS       = 0.05
local BASE_FIRST_AID_RATE  = 0.50
local PER_CLERIC_RANK_BONUS= 0.10
local REST_MIN, REST_MAX   = 2, 4
local VACATION_CHANCE      = 0.50
local VACATION_MIN, VACATION_MAX = 1, 2

local function calc_survival_rate(adv_id, task_rank_int)
    local adv = AdvData.get(adv_id)
    if not adv then return 0 end
    local rate = BASE_SURVIVAL_RATE
    local rank_diff = adv.rank - task_rank_int
    if rank_diff > 0 then rate = rate + rank_diff * PER_RANK_BONUS end
    rate = rate + TraitSystem.get_stat_value(adv_id, "casualty_roll_bonus")
    return math.max(0, math.min(1, rate))
end

--- Perform the casualty survival roll.
--- Survived: calls enter_rest(). Dead: calls AdvData.remove().
---@return boolean  true=survived, false=permanently dead
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

--- Put adventurer into medical rest (resting_days = random [2,4]).
function M.enter_rest(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return end
    adv.is_on_quest = false
    adv.resting_days = math.random(REST_MIN, REST_MAX)
end

--- After rest: 50% chance of 1-2 vacation days.
function M.trigger_vacation_check(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return end
    if math.random() <= VACATION_CHANCE then
        adv.vacation_days = math.random(VACATION_MIN, VACATION_MAX)
    end
end

local function calc_first_aid_rate(cleric_id, patient_id)
    local cleric  = AdvData.get(cleric_id)
    local patient = AdvData.get(patient_id)
    if not cleric or not patient then return 0 end
    local rate = BASE_FIRST_AID_RATE
    local rank_diff = cleric.rank - patient.rank
    if rank_diff > 0 then rate = rate + rank_diff * PER_CLERIC_RANK_BONUS end
    rate = rate + TraitSystem.get_stat_value(cleric_id, "first_aid_roll_bonus")
    return math.max(0, math.min(1, rate))
end

--- First-aid roll. Success → enter_rest(patient). Fail → casualty roll.
---@return boolean  true=survived, false=dead
function M.do_first_aid_roll(cleric_id, patient_id, task_rank_int)
    if math.random() <= calc_first_aid_rate(cleric_id, patient_id) then
        M.enter_rest(patient_id)
        return true
    else
        return M.do_casualty_roll(patient_id, task_rank_int or 1)
    end
end

--- Process a downed adventurer in a party. Finds living priest or falls back to direct roll.
---@return boolean  true=survived, false=dead
function M.process_party_casualty(patient_id, party_ids, task_rank_int)
    local cleric_id = nil
    for _, id in ipairs(party_ids) do
        if id ~= patient_id then
            local adv = AdvData.get(id)
            if adv and adv.profession == "priest" and adv.is_on_quest then
                cleric_id = id; break
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

## Task 4: Update `quest_board.lua` — Difficulty Range + Bounty Weight Ordering

**Files:**
- Modify: `guild/quest_board.lua`
- Modify: `guild_test.lua` (replace `run_quest_board_tests`)

### Step 4.1: Write failing tests

Replace `run_quest_board_tests()` in `guild_test.lua`:

```lua
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
    QuestData.post(q_h.id, 1.5)  -- high bounty
    pool = QuestBoard.collect_registrations(q_h.id)
    -- hunt_specialist should appear before normal adventurer in ordered pool
    local spec_pos, norm_pos = nil, nil
    for i, id in ipairs(pool) do
        if id == adv_spec.id then spec_pos = i end
        if id == adv_norm.id then norm_pos = i end
    end
    assert_eq("hunt_specialist ranked higher", spec_pos ~= nil and norm_pos ~= nil and spec_pos < norm_pos, true)

    log.info("=== Quest Board V2 Tests Done ===")
end
```

- [ ] Replace `run_quest_board_tests()` in `guild_test.lua`

### Step 4.2: Verify failure

Expected: `set_difficulty` not found error

- [ ] Confirm failure

### Step 4.3: Rewrite `guild/quest_board.lua`

```lua
-- guild/quest_board.lua
-- 报名 AI 模块 V2：难度容忍幅度等级范围 + 特质行为门槛 + 赏金意愿权重排序
local AdvData     = require 'guild.adventurer_data'
local QuestData   = require 'guild.quest_data'
local TraitSystem = require 'guild.trait_system'

local M = {}

-- 难度 → 容忍幅度（1=简单 2=普通 3=困难 4=噩梦 5=地狱）
local DIFFICULTY_TOLERANCE = { [1]=4, [2]=3, [3]=2, [4]=1, [5]=0 }
local _difficulty = 2

function M.set_difficulty(level)
    assert(DIFFICULTY_TOLERANCE[level], "invalid difficulty: " .. tostring(level))
    _difficulty = level
end

function M.get_tolerance()
    return DIFFICULTY_TOLERANCE[_difficulty] or 3
end

--- Compute [min_rank, max_rank] for an adventurer. max_rank=nil means no upper limit.
function M.get_rank_range(adv_id)
    local adv = AdvData.get(adv_id)
    if not adv then return 1, nil end
    local tolerance = M.get_tolerance()
    local offset    = TraitSystem.get_level_min_offset(adv_id)
    local min_rank  = math.max(1, adv.rank - tolerance + offset)
    local max_rank  = TraitSystem.get_max_rank_cap(adv_id)
    return min_rank, max_rank
end

--- Collect registrations for a posted quest, sorted by signup weight (highest first).
---@param quest_id string
---@return string[]
function M.collect_registrations(quest_id)
    local quest = QuestData.get(quest_id)
    if not quest or quest.status ~= QuestData.STATUS.POSTED then return {} end

    local candidates = {}  -- { adv_id, weight }
    for _, adv in ipairs(AdvData.get_all()) do
        -- Gate 1: availability (not on quest, not resting, not on vacation)
        if not AdvData.is_available(adv.id) then goto continue end
        -- Gate 2: level range
        local min_r, max_r = M.get_rank_range(adv.id)
        if quest.rank < min_r then goto continue end
        if max_r and quest.rank > max_r then goto continue end
        -- Gate 3: trait behavior
        if TraitSystem.rejects_quest_type(adv.id, quest.quest_type) then goto continue end
        -- Passed: compute signup weight for ordering
        local w = TraitSystem.get_signup_weight(adv.id, quest.quest_type, quest.bounty_mult)
        candidates[#candidates+1] = { id=adv.id, weight=w }
        ::continue::
    end

    -- Sort by weight descending (high bounty / preferred quest type first)
    table.sort(candidates, function(a, b) return a.weight > b.weight end)

    local pool = {}
    for _, c in ipairs(candidates) do pool[#pool+1] = c.id end
    quest.registered_ids = pool
    return pool
end

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
git commit -m "feat(guild): rewrite quest board with difficulty range, trait gate, and weight ordering"
```

- [ ] Commit

---

## Task 5: Update `quest_execution.lua` — Death Triggers Casualty Chain

**Files:**
- Modify: `guild/quest_execution.lua`
- Modify: `guild_test.lua` (add execution casualty tests)

### Step 5.1: Write failing tests for execution death routing

Add to `run_execution_tests()` in `guild_test.lua`, after existing setup:

```lua
    -- V2: single-person death routes through casualty chain
    -- We can test _finish is called via outcome tracking by monkey-patching on_complete
    local completed_outcomes = {}
    local function capture_outcome(qid, outcome)
        completed_outcomes[#completed_outcomes+1] = outcome
    end

    AdvData.reset(); QuestData.reset()
    local adv_solo = AdvData.create("Solo", "warrior", "C")
    adv_solo.is_on_quest = true
    local q_solo = QuestData.create("单人任务", 3, QuestData.TYPE.HUNT, nil)
    QuestData.post(q_solo.id, 1.0)
    q_solo.dispatched_ids = {adv_solo.id}
    QuestData.set_status(q_solo.id, QuestData.STATUS.DISPATCHED)

    -- Directly call mark_success to verify it still routes correctly
    Execution.mark_success(q_solo.id)
    -- mark_fail is removed in V2; only mark_success and recall remain
    assert_eq("mark_success exists", type(Execution.mark_success) == "function", true)
    assert_eq("recall exists", type(Execution.recall) == "function", true)
    -- mark_fail (V2 removed heavy_fail path)
    assert_eq("mark_fail removed", Execution.mark_fail, nil)
```

- [ ] Add V2 execution API tests to `run_execution_tests()` in `guild_test.lua`

### Step 5.2: Verify failure

Expected: `mark_fail removed` FAIL (function still exists)

- [ ] Confirm failure

### Step 5.3: Update the death handler in `guild/quest_execution.lua`

Replace the `local death_handler = function(...)` block inside `M.start()` with:

```lua
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
            -- Survived: resting, task continues (no more active members → wipe check below)
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
```

Also **delete** the `M.mark_fail(quest_id, is_heavy)` function entirely, and update the file header comment:

```lua
-- guild/quest_execution.lua
-- 任务执行模块 V2：创建地图单位、通过 casualty.lua 处理伤亡链、处理召回
-- 注：V2 删除 mark_fail，伤亡由死亡事件实时驱动
```

- [ ] Apply changes to `guild/quest_execution.lua`

### Step 5.4: Run tests and verify they pass

- [ ] Confirm execution V2 tests pass

### Step 5.5: Commit

```bash
git add guild/quest_execution.lua guild_test.lua
git commit -m "feat(guild): wire casualty chain into execution death handler, remove mark_fail"
```

- [ ] Commit

---

## Task 6: Update `quest_dispatch.lua` — Remove Probability Layer

**Files:**
- Modify: `guild/quest_dispatch.lua`
- Modify: `guild_test.lua` (add regression test for deletion)

### Step 6.1: Write regression test for probability function removal

Add to `run_dispatch_tests()` in `guild_test.lua`, after existing assertions:

```lua
    -- V2: probability functions must not exist
    assert_eq("calc_base_fail_prob removed", Dispatch.calc_base_fail_prob, nil)
    assert_eq("calc_equip_delta removed", Dispatch.calc_equip_delta, nil)
    assert_eq("calc_final_fail_prob removed", Dispatch.calc_final_fail_prob, nil)
    -- dispatch and calc_party_avg_rank still exist
    assert_eq("dispatch still exists", type(Dispatch.dispatch) == "function", true)
    assert_eq("calc_party_avg_rank still exists", type(Dispatch.calc_party_avg_rank) == "function", true)
```

- [ ] Add regression assertions to `run_dispatch_tests()` in `guild_test.lua`

### Step 6.2: Verify failure

Expected: `calc_base_fail_prob removed` FAIL (function still exists)

- [ ] Confirm failure

### Step 6.3: Delete the three probability functions from `quest_dispatch.lua`

Remove these three functions entirely:
- `M.calc_base_fail_prob(task_rank_int, party_avg_rank)`
- `M.calc_equip_delta(equip_avg_rank, task_rank_int)`
- `M.calc_final_fail_prob(task_rank_int, adv_ids, equip_avg_rank)`

Update the file header comment:

```lua
-- guild/quest_dispatch.lua
-- 派遣模块 V2：队伍平均等级计算、报名资格验证、执行派遣
-- 注：V2 删除概率失败计算层，任务成败由实时执行和 casualty.lua 决定
```

Also remove the `local Dispatch = require 'guild.quest_dispatch'` import from `quest_settlement.lua` (no longer needed there).

- [ ] Delete the three functions and update comments in `quest_dispatch.lua`
- [ ] Remove `Dispatch` require from `quest_settlement.lua`

### Step 6.4: Run tests and verify they pass

- [ ] Confirm regression tests pass

### Step 6.5: Commit

```bash
git add guild/quest_dispatch.lua guild/quest_settlement.lua guild_test.lua
git commit -m "refactor(guild): remove probability failure layer from quest_dispatch"
```

- [ ] Commit

---

## Task 7: Update `quest_settlement.lua` — Three Branches + Post-Settlement Trait Rolls

**Files:**
- Modify: `guild/quest_settlement.lua`
- Modify: `guild_test.lua` (replace `run_settlement_tests`)

### Step 7.1: Write failing tests

Replace `run_settlement_tests()` in `guild_test.lua`:

```lua
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
    -- V2: no loyalty_changes field
    assert_eq("success: no loyalty_changes", r1.loyalty_changes, nil)

    -- Test 2: abort — no gold, adv freed, negative trait rolls triggered
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
```

- [ ] Replace `run_settlement_tests()` in `guild_test.lua`

### Step 7.2: Verify failure

Expected: `no loyalty_changes` FAIL (field still exists)

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

local BASE_XP = { [1]=100,[2]=200,[3]=450,[4]=900,[5]=1800,[6]=3500,[7]=7000 }

---@class SettlementResult
---@field outcome string           "success"|"abort"|"wipe"
---@field gold_reward integer
---@field lost_adv_ids string[]
---@field lost_equip_ids string[]

local function run_post_settlement_trait_rolls(adv_ids, is_success, is_abort)
    for _, adv_id in ipairs(adv_ids) do
        if AdvData.get(adv_id) then
            if is_success then
                TraitSystem.trigger_positive_roll(adv_id)
                TraitSystem.trigger_negative_roll(adv_id)
            elseif is_abort then
                -- Single roll at 60% (higher than combat failure's 40%), per spec §3.3
                TraitSystem.trigger_negative_roll_at_rate(adv_id, 0.60)
            else
                TraitSystem.trigger_negative_roll(adv_id)  -- 40% rate
            end
            local adv = AdvData.get(adv_id)
            if adv and adv.resting_days > 0 then
                -- Extra roll for resting adventurers (50% rate)
                TraitSystem.trigger_negative_roll_at_rate(adv_id, 0.50)
                Casualty.trigger_vacation_check(adv_id)
            end
        end
    end
end

---@param quest_id string
---@param outcome string  "success"|"abort"|"wipe"
---@return SettlementResult
function M.settle(quest_id, outcome)
    local quest = QuestData.get(quest_id)
    local result = { outcome=outcome, gold_reward=0, lost_adv_ids={}, lost_equip_ids={} }
    if not quest then return result end

    local dispatched = quest.dispatched_ids
    local equip_ids  = quest.equipment_ids

    if outcome == "success" then
        result.gold_reward = QuestData.total_reward(quest_id)
        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then
                adv.is_on_quest = false
                local xp_base = BASE_XP[quest.rank] or 100
                local mult    = AdvData.xp_multiplier(quest.rank, adv.rank)
                AdvData.add_xp(adv_id, math.floor(xp_base * mult))
            end
        end
        run_post_settlement_trait_rolls(dispatched, true, false)
        QuestData.set_status(quest_id, QuestData.STATUS.SUCCEEDED)

    elseif outcome == "abort" then
        for _, adv_id in ipairs(dispatched) do
            local adv = AdvData.get(adv_id)
            if adv then adv.is_on_quest = false end
        end
        run_post_settlement_trait_rolls(dispatched, false, true)
        QuestData.set_status(quest_id, QuestData.STATUS.ABORTED)

    elseif outcome == "wipe" then
        for _, adv_id in ipairs(dispatched) do
            result.lost_adv_ids[#result.lost_adv_ids+1] = adv_id
            AdvData.remove(adv_id)
        end
        result.lost_equip_ids = equip_ids
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

- [ ] Overwrite `guild/quest_settlement.lua`

### Step 7.4: Run tests and verify they pass

- [ ] Confirm all Settlement V2 tests pass

### Step 7.5: Commit

```bash
git add guild/quest_settlement.lua guild_test.lua
git commit -m "refactor(guild): simplify settlement to 3 branches with post-settlement trait rolls"
```

- [ ] Commit

---

## Task 8: Final Integration — Wire `tick_daily` and Full Suite

**Files:**
- Modify: `guild/quest_manager.lua`
- Modify: `guild_test.lua` (add top-level requires, wire all test calls)

### Step 8.1: Update `quest_manager.lua`

Find `AdvData.tick_idle_penalty()` and replace with `AdvData.tick_daily()`.

- [ ] Replace `tick_idle_penalty()` with `tick_daily()` in `guild/quest_manager.lua`

### Step 8.2: Update `guild_test.lua` top-level requires

Add after existing requires at the top:

```lua
local TraitSystem = require 'guild.trait_system'
local Casualty    = require 'guild.casualty'
```

Update the T-key handler to call all tests in this order:

```lua
run_adventurer_tests()
run_trait_system_tests()
run_casualty_tests()
run_quest_data_tests()
run_quest_board_tests()
run_dispatch_tests()
run_execution_tests()
run_settlement_tests()
run_event_card_tests()
```

- [ ] Update requires and T-key handler in `guild_test.lua`

### Step 8.3: Run full test suite

Press T key in-game.
Expected: All test sections show `[TEST PASS]`. Zero `[TEST FAIL]` lines.

- [ ] Confirm full test suite passes

### Step 8.4: Final commit

```bash
git add guild/quest_manager.lua guild_test.lua
git commit -m "feat(guild): complete V2 integration - wire tick_daily, full test suite green"
```

- [ ] Commit

---

## Summary

After all tasks complete:
- **Task execution** is driven by real-time MOBA unit death events via `casualty.lua`
- **Level acceptance range** is gated by difficulty tolerance + trait offset + upper cap traits
- **Trait system** replaces loyalty: probabilistic post-quest rolls, 12 positive / 16 negative traits
- **Signup ordering** is by bounty weight × prefer_quest_type bonus, descending
- **Settlement** has 3 clean branches (success / abort / wipe), no probability math
- **Equipment → unit stat routing** is deferred pending Y3 item API integration
