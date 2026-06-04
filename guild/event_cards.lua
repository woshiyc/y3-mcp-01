-- guild/event_cards.lua
-- 事件卡系统：任务执行中偶发触发，玩家选择影响结算
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
                { label="撤退（按轻度失败结算）", effect="abort" },
                { label="继续前进",               effect="continue" },
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
    escort = {
        {
            id = "ambush",
            text = "护送途中遭遇伏击，是否护送商队先撤？",
            options = {
                { label="护送优先撤退", effect="abort" },
                { label="就地迎战",     effect="risk_escape" },
            }
        },
    },
}

--- 为任务类型随机抽取 0~2 张事件卡（Fisher-Yates 无重复抽取）
---@param quest_type string
---@return table[]  抽到的事件卡列表（可能为空）
function M.draw_cards(quest_type)
    local pool = M.CARDS[quest_type] or {}
    if #pool == 0 then return {} end

    local count = math.random(0, math.min(2, #pool))
    if count == 0 then return {} end

    -- 构建索引副本并执行 Fisher-Yates 打乱，取前 count 个
    local indices = {}
    for i = 1, #pool do indices[i] = i end

    for i = 1, count do
        local j = math.random(i, #indices)
        indices[i], indices[j] = indices[j], indices[i]
    end

    local drawn = {}
    for i = 1, count do
        drawn[i] = pool[indices[i]]
    end
    return drawn
end

return M
