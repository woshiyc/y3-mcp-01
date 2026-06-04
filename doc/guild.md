冒险者公会任务系统 — 实现完成
文件结构

e:/pycode/y3-map/
├── guild/
│   ├── adventurer_data.lua   # 冒险者数据：等级/忠诚度/经验/闲置惩罚
│   ├── quest_data.lua        # 任务状态机：PENDING→POSTED→DISPATCHED→结算
│   ├── quest_board.lua       # 报名AI：三重门槛（等级/空闲/忠诚度）
│   ├── quest_dispatch.lua    # 派遣：队伍平均等级、失败概率计算
│   ├── quest_execution.lua   # 执行：地图单位创建、死亡监控、召回
│   ├── quest_settlement.lua  # 结算：5种结算分支（成功/轻度/召回/重度/全灭）
│   ├── quest_manager.lua     # 协调器：游戏日计时器 + 对外接口
│   ├── event_cards.lua       # 事件卡：Fisher-Yates抽卡，0~2张/任务
│   └── quest_ui.lua          # UI绑定层（框架骨架，等Y3编辑器面板配合）
└── guild_test.lua            # 测试套件（T键运行）
12 次提交，所有关键功能覆盖
模块	核心功能	状态
adventurer_data	RANK_INT映射/忠诚度/经验升级/闲置惩罚	✅
quest_data	状态机/赏金计算/valid mult校验	✅
quest_board	3门槛报名AI/忠诚度→赏金意愿阈值	✅
quest_dispatch	队伍平均等级/基础+装备修正失败概率	✅
quest_execution	单位创建/死亡监听(handle存储)/召回/_finish清理	✅
quest_settlement	5分支结算/专属奖励/全灭旁观者士气	✅
quest_manager	600秒游戏日计时器/post/dispatch/recall接口	✅
event_cards	hunt/explore/escort卡池/0~2张抽取	✅
quest_ui	公告板/派遣/结算面板绑定（需Y3编辑器配合）	✅
待手动完成的事项
同步到游戏项目：将 guild/ 目录和 guild_test.lua 复制到 Y3 编辑器中的 maps/EntryMap/script/ 目录
在入口文件中初始化：在 可重载的代码.lua 中添加 require 'guild.quest_manager' 并调用 GuildManager.init()
UI面板：在Y3编辑器中创建 QuestBoardPanel / DispatchPanel / SettlementPanel 三个面板，组件名称需与 quest_ui.lua 中一致
death_listener注销：确认 Y3 事件监听注销API后，在 quest_execution.lua 第139行解注释 :off() 调用
按T键运行测试：游戏中按T键验证所有自动化测试PASS