---
name: y3-model-evaluator
description: 对用户手动配置的 Y3 模型清单进行 LLM 批量评估，输出 asset_profiles.json，用于后续地形生成和 MCP 实体写入。触发词：评估模型、模型评估、生成资产档案、model evaluator、生成 asset profile。
---

# Y3 模型评估（y3-model-evaluator）

用户手动配置 10~30 个模型的基础信息（ID、名称、尺寸、描述），由 LLM 批量评估每个模型的放置规则、地形影响和玩法属性，输出结构化 `asset_profiles.json`，供地形生成脚本和 `entity_create_block` MCP 调用使用。

---

## ⛔ 全局禁令

| # | 禁令 | 正确做法 |
|---|------|----------|
| 1 | ⛔ **禁止 AI 猜测或捏造 model_id** | model_id 必须来自用户的 manifest 文件 |
| 2 | ⛔ **禁止跳过 manifest 格式验证** | 必须先运行 `validate_manifest.py` |
| 3 | ⛔ **禁止每次只评估 1 个模型** | 每批 5~8 个，提高效率 |
| 4 | ⛔ **禁止输出不完整的 asset_profile** | 每个字段必须有值，不得用 null 或省略 |
| 5 | ⛔ **禁止修改 mcp.entity_type** | 固定为 16777216（资源模型类型） |

---

## Stage 0：前置检查

### 0.1 接收 manifest 文件路径

> 询问用户：
> "请提供模型清单文件路径（`model_manifest.json`）。
> 如果还没有清单，我可以生成模板文件，你填写后再告诉我路径。"

- 用户提供路径 → 继续 0.2
- 用户没有清单 → 执行 Stage 0.1a（生成模板）

#### Stage 0.1a：生成模板

将 `templates/model_manifest_template.json` 复制到用户指定目录，告知填写规则后等待用户反馈。

### 0.2 验证 manifest 格式

```bash
python scripts/validate_manifest.py <manifest_path>
```

| 结果 | 处理 |
|------|------|
| `{"status": "ok", "count": N}` | ✅ 继续，打印"共 N 个模型，开始评估" |
| `{"status": "error", "errors": [...]}` | ⚠️ 将错误逐条展示给用户，等待修正后重新验证 |

### 0.3 确认评估范围

打印所有模型的 name + model_id 列表，询问用户：
- "以上 N 个模型是否全部评估？或者只评估部分？"

用户确认后进入 Stage 1。

---

## Stage 1：批量 LLM 评估

### 1.1 分批评估

每批 **5~8 个**模型，按以下步骤循环：

```
读取 manifest 中当前批次的模型列表
↓
构建评估 Prompt（参见 prompts/evaluate_model_prompt.md）
↓
调用 LLM 评估 → 得到该批次的 asset_profiles 列表
↓
追加到输出 JSON
↓
打印进度（"已完成 X/N 个模型"）
```

### 1.2 评估 Prompt 构建规则

每次评估传入：
1. `prompts/evaluate_model_prompt.md`（系统提示，定义输出格式和规则）
2. 当前批次的模型列表（JSON 格式）

批次输入示例：
```json
[
  {
    "model_id": "201669",
    "name": "国风灰色景观石",
    "size": {"width_m": 2.5, "height_m": 3.5, "depth_m": 2.5},
    "description": "中型灰色景观石，表面粗糙，适合山地和道路两侧装饰"
  }
]
```

### 1.3 LLM 输出格式

LLM 必须严格按照 `prompts/evaluate_model_prompt.md` 中的 JSON Schema 输出，**不得输出任何额外文字**。

---

## Stage 2：输出与保存

### 2.1 合并输出

将所有批次结果合并为完整的 `asset_profiles.json`：

```json
{
  "version": "1.0",
  "generated_at": "<ISO时间>",
  "source_manifest": "<manifest路径>",
  "total": N,
  "profiles": [
    { ... },
    { ... }
  ]
}
```

保存路径：与 manifest 文件同目录，命名为 `asset_profiles.json`。

### 2.2 输出摘要

```
✅ 评估完成
  - 总模型数：N
  - 植被类：X 个
  - 建筑类：X 个
  - 装饰物类：X 个
  - 其他：X 个
  - 输出文件：<路径>/asset_profiles.json

下一步可用于：
  1. 地形生成：将 asset_profiles.json 传入地形生成脚本
  2. MCP 写入：使用 mcp.entity_type + mcp.scale 参数调用 entity_create_block
```

---

## 数据流说明

```
model_manifest.json
  (model_id, name, size, description)
         ↓
   LLM 评估
         ↓
asset_profiles.json
  ├── placement → 地形生成脚本（决定放在哪里）
  ├── terrain_effect → 地形修改逻辑
  └── mcp → entity_create_block 参数
```

---

## 文件结构

```
y3-model-evaluator/
├── SKILL.md                              ← 本文件
├── templates/
│   └── model_manifest_template.json      ← 用户填写模板
├── prompts/
│   └── evaluate_model_prompt.md          ← LLM 评估 Prompt
└── scripts/
    └── validate_manifest.py              ← manifest 格式验证
```
