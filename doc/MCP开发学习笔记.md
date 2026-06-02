# MCP 开发学习笔记

> 本文档由对话整理，涵盖 MCP 协议基础、mcp-hub 项目解析、rag_doc 代码拆解、Godot MCP 生态调研。

---

## 一、MCP 协议基础

### 标准 MCP 的三类核心原语

| 原语 | 说明 |
|---|---|
| **Tools** | AI 可主动调用的函数，最常用 |
| **Resources** | AI 可读取的数据，类似文件系统（静态/动态/订阅） |
| **Prompts** | 预定义提示词模板，用户通过客户端选用 |

**可选能力：** Sampling（服务端反向请求 AI 生成）、Roots（工作目录范围）、Logging、Progress。

### MCP 工作机制

```
MCP 服务器启动 → 声明自己有哪些 tools
客户端连接 → 拉取 tool 列表 → 注入到 AI 的 context
AI → 按需调用 tool → 服务器执行 → 返回结果
```

---

## 二、y3-maker-config 项目

### 项目结构

| 目录/文件 | 作用 |
|---|---|
| `mcp_settings.json` | MCP 服务器连接配置 |
| `knowledge/` | AI 知识库（md 文档） |
| `rules/` | AI 行为规则（`.mdc` 文件） |
| `skills/` | 技能定义（slash 命令） |
| `tools/` | 辅助 Python 脚本 |
| `memory/` | 记忆文件 |

### 三个 MCP 端点

```json
{
  "y3-helper":  "http://127.0.0.1:8766/mcp",
  "y3editor":   "http://127.0.0.1:8765/mcp",
  "y3runtime":  "http://127.0.0.1:8767/mcp"
}
```

这三个端点**不是** y3-maker-config 启动的，是 Y3 编辑器/游戏引擎本身运行时暴露的。y3-maker-config 只是配置和知识包，告诉 AI 客户端去哪里连接。

---

## 三、mcp-hub 项目解析

### 本质

**单进程多路径 MCP 服务器模板**，不是管理其他 MCP 的 hub，而是把多个集成打包在一个进程里，每个集成挂载到不同 HTTP 路径：

```
启动一个进程 →
  http://localhost:8000/mcp/demo_app   ← 集成 A（示例模板）
  http://localhost:8000/mcp/rag_doc    ← 集成 B（真实业务）
  http://localhost:8000/healthz        ← 健康检查
```

### 集成结构

```
integrations/
├── demo_app/          # 示例（参考模板，2个玩具工具）
│   ├── server.py      # FastMCP 实例
│   ├── tools.py
│   ├── client.py
│   └── models.py
└── rag_doc/           # 真实业务（RAG 文档服务，6个工具）
    ├── server.py
    ├── tools.py
    ├── client.py
    └── models.py
```

每个集成都是独立的 FastMCP 实例，结构完全对等，区别只是业务内容。

### 框架层功能

- `servers/main.py`：Starlette 组装，自动挂载所有集成
- `integrations/registry.py`：自动扫描发现集成，支持 `ENABLED_SERVICES` 环境变量
- `auth.py`：从当前 HTTP 请求提取 Bearer Token
- 支持 stdio / sse / streamable-http 三种传输模式

---

## 四、rag_doc 完整代码拆解

### 6 个工具

| Tool | 功能 |
|---|---|
| `rag_retrieve_chunk` | 语义 RAG 检索，返回最相关文档块 |
| `rag_search_path` | 按路径语义搜索文档 |
| `rag_explore_tree` | 按目录树层级浏览知识库 |
| `rag_search_by_meta` | 纯元数据过滤（不含语义） |
| `rag_search_doc_by_url` | 通过 URL 查找文档 |
| `rag_get_doc_content` | 获取文档完整内容 |

**数据源（app_id）：** 1=Confluence, 2=OnlyOffice, 3=Affine, 4=APITable, 5=Nextcloud

### rag_retrieve_chunk 调用链

```
AI 调用 tool
    → tools.py: rag_retrieve_chunk()
        → auth.py: get_bearer_token()          # 从 HTTP header 提取 token
        → tools.py: _build_metadata_condition() # 组装过滤条件
            → tools.py: _build_date_conditions()
        → client.py: retrieve_chunk()
            → client.py: get_client()           # 单例 httpx 客户端
            → POST /api/v1/doc/retrieveChunk
            → client.py: _extract_data()        # 解包 {success, data} 外壳
            → ChunkDoc.model_validate()         # 反序列化
```

### 关键设计点

**1. 参数名转换（RetrieveChunkRequest）**

Pydantic 模型用 `Field(alias="appIds")` 做蛇形→驼峰转换，`Field("0.5", ...)` 设默认值。Python 命名规范和后端 API 格式的适配层。

**2. 两阶段检索**

```
top_k=50     → 粗召回（向量+关键词混合）→ 50个候选
rerank_topk=10 → 精排（rerank模型重新打分）→ 最终10个
```

**3. 日期范围边界处理**

`created_at_to="2025-03"` → `_next_date_boundary` 转成 `"2025-04"` 用 `<` 比较，实现"包含当月"的闭区间语义。

**4. 元数据条件结构**

```json
{
  "logic": "and",
  "conditions": [
    {"name": "created_by", "value": "zhangsan", "comparison_operator": "is"},
    {"name": "created_at", "value": "2025-01-01", "comparison_operator": ">="},
    {"name": "created_at", "value": "2025-04-01", "comparison_operator": "<"}
  ]
}
```

**5. 错误处理**

用 FastMCP 的 `ToolError` 把底层异常转成 AI 可读的错误信息，服务不崩溃，AI 能看到错误原因并自我修正。

**6. MCP 数据流**

```
AI 调用 tool → MCP 执行 → 返回 chunks 作为 tool result
→ chunks 写回对话上下文 → AI 读到内容生成最终回答
```

rag_retrieve_chunk 只取数据，"交给 LLM 作上下文"由 MCP 客户端协议层自动完成。

---

## 五、Godot MCP 生态调研

### 现有主要项目

| 项目 | 工具数 | 通信方式 | 费用 |
|---|---|---|---|
| [Coding-Solo/godot-mcp](https://github.com/Coding-Solo/godot-mcp) | ~14 | Headless CLI | 免费 |
| [tugcantopaloglu/godot-mcp](https://github.com/tugcantopaloglu/godot-mcp) | 149 | Headless + TCP | 免费 |
| [hi-godot/godot-ai](https://github.com/hi-godot/godot-ai) | ~120 ops | WebSocket | 免费 |
| [youichi-uda/godot-mcp-pro](https://github.com/youichi-uda/godot-mcp-pro) | 162 | WebSocket | $15 |
| [3ddelano/gdai-mcp-plugin-godot](https://github.com/3ddelano/gdai-mcp-plugin-godot) | — | WebSocket | 免费 |

### 两种核心架构

#### 架构一：Headless CLI

```
MCP Server → spawn: godot --headless --script ops.gd <operation> <json>
           ← stdout 解析 JSON 结果
```

GDScript 读命令行参数，执行操作，`print()` 输出 JSON，MCP Server 捕获 stdout。

**优点：** 无需编辑器插件，实现简单。  
**缺点：** 每次操作启动新进程（2-3s 冷启动），无法和运行中的游戏/编辑器交互。

#### 架构二：TCP Bridge

```
MCP Server → TCP Socket :9090 → Godot Plugin (TCPServer, _process轮询)
           ← JSON 响应
```

Godot Plugin 在 `_process()` 主线程里轮询 TCPServer，收到命令后执行 EditorInterface API，天然主线程安全。

**优点：** 实时双向通信，能做运行时操作（`game_eval`、截图、性能监控）。  
**缺点：** 需要安装 Godot 插件，实现较复杂。

### 技术栈

| 层 | 主流选择 |
|---|---|
| MCP Server | TypeScript + `@modelcontextprotocol/sdk`（官方 SDK）|
| 传输协议 | stdio（Claude Code 本地工具标准）|
| Godot 侧 | GDScript `EditorPlugin` + `TCPServer` |
| Python 方案 | FastMCP（少数派）|

### TypeScript MCP SDK 核心用法

```typescript
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';

const server = new Server(
    { name: 'godot-mcp', version: '0.1.0' },
    { capabilities: { tools: {} } }
);

// 注册工具列表
server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [{ name: 'run_project', description: '...', inputSchema: { ... } }]
}));

// 处理工具调用
server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const result = await dispatch(request.params.name, request.params.arguments);
    return { content: [{ type: 'text', text: JSON.stringify(result) }] };
});

await server.connect(new StdioServerTransport());
```

### 核心难点

| 难点 | 说明 |
|---|---|
| **主线程限制** | EditorInterface API 只能在主线程调用，TCP/HTTP 在后台线程，需要队列调度 |
| **Headless 隔离** | Headless 进程看不到正在运行的编辑器，无法做运行时操作 |
| **截图** | 运行时截图有效，编辑器截图有限制，gdai-mcp 把它作为核心卖点 |
| **错误捕获** | GDScript 无 API 直接获取编译错误列表，需要特殊处理 |
| **安全注入** | AI 传入路径参数要防注入，不能直接用 `res://` 路径加载脚本 |
| **工具数量 vs Token** | 149 个工具的 schema 消耗大量 token，需要 Lite Mode 变体 |

### 安全注意事项（来自 Coding-Solo 源码注释）

```gdscript
# Only looks up names via the project's global class registry.
# Raw paths (e.g. "res://evil.gd") are intentionally not accepted here
# to prevent arbitrary script instantiation from agent-supplied input.
```

---

## 六、自建 Godot MCP 方案设计

### 架构

```
Claude Code
    ↕ MCP 协议（stdio）
MCP Server（Python/FastMCP，独立进程）
    ↕ HTTP/TCP localhost
Editor Plugin（GDScript，运行在 Godot 内）
    ↕ Editor API
Godot 编辑器
```

### 推荐工具集

| Tool | 功能 |
|---|---|
| `get_scene_hierarchy` | 返回完整节点树 |
| `get_node_properties` | 读节点所有组件和属性 |
| `create_node` | 创建节点并设初始属性 |
| `modify_node` | 改位置/旋转/组件参数 |
| `delete_node` | 删节点 |
| `read_script` | 读脚本文件 |
| `write_script` | 写脚本（AI 生成代码直接写入）|
| `get_compile_errors` | 拿编译报错 |
| `get_console_logs` | 运行时日志 |
| `run_play_mode` / `stop_play_mode` | 控制运行 |
| `take_screenshot` | 截图，让 AI 看运行效果 |
| `list_assets` | 列出可用资源 |

### 主线程调度模式（关键）

```gdscript
# plugin.gd
var _queue: Array = []

func _process(_delta):
    while not _queue.is_empty():
        var task: Callable = _queue.pop_front()
        task.call()

func dispatch_to_main(task: Callable) -> void:
    _queue.append(task)

# router.gd 里用信号量同步
func _call_on_main(fn: Callable) -> Variant:
    var sem := Semaphore.new()
    var result: Variant = null
    _plugin.dispatch_to_main(func():
        result = fn.call()
        sem.post()
    )
    sem.wait()
    return result
```

### 开发顺序

```
Week 1：Godot Plugin HTTP Server + get_scene_hierarchy
Week 2：write_script + 主线程调度验证
Week 3：MCP Server 接入 Claude Code
Week 4：take_screenshot → 完成视觉闭环
```

### 学习路径

```
1. 读 Coding-Solo/godot-mcp 源码
   → 最简单，理解 MCP SDK 基础、stdio 传输、工具注册

2. 读 tugcantopaloglu 的 TCP 扩展
   → 理解双进程通信、game_eval 实现原理

3. 用 FastMCP 复现 get_scene_hierarchy
   → 练习 Python MCP 写法 + GDScript TCPServer

4. 加 game_eval + take_screenshot
   → 完成"写代码 → 运行 → 截图 → AI 看图 → 修改"闭环
```

---

*整理自 2026-05-27 对话*
