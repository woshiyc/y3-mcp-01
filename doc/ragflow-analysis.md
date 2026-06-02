# RAGFlow 项目深度技术分析报告

> 项目版本：v0.22.1 | 分析日期：2026-05-12 | 项目地址：https://github.com/infiniflow/ragflow

---

## 目录

1. [项目概述](#1-项目概述)
2. [功能全景](#2-功能全景)
3. [系统架构](#3-系统架构)
4. [核心技术点](#4-核心技术点)
5. [工程实现技术栈](#5-工程实现技术栈)
6. [业界方案对比](#6-业界方案对比)
7. [总结与评价](#7-总结与评价)

---

## 1. 项目概述

RAGFlow 是由 InfiniFlow 开源的**企业级 RAG（Retrieval-Augmented Generation）引擎**，定位为"基于深度文档理解的端到端 RAG 工作流平台"。其核心理念是：

- **Quality in, quality out**：通过深度文档理解（DeepDoc）保证输入质量
- **可解释性**：切片过程可视化，答案溯源到原文片段
- **全流程自动化**：从文档上传到多轮对话的完整 RAG 工作流
- **Agent 能力**：内置可编排 Agentic Workflow，支持复杂任务自动化

---

## 2. 功能全景

### 2.1 文档处理与知识库管理

| 功能模块 | 描述 |
|----------|------|
| **多格式文档解析** | PDF、Word、PPT、Excel、Markdown、HTML、JSON、TXT、图片、邮件(.msg) |
| **多种解析引擎** | 自研 DeepDoc / MinerU / Docling / Apache Tika，可按文档类型选择 |
| **OCR 识别** | 支持扫描件、复印件识别（含表格 OCR） |
| **多模态图片理解** | 用视觉大模型（VLM）描述 PDF/DOCX 中的图表 |
| **版面分析** | ONNX 加速的版面识别模型，识别文字块/表格/图片区域 |
| **分块策略（10+种模板）** | 通用(Naive)、书籍、论文、问答对、法律、表格、代码、简历、演示文稿、图片、音频、行记录、Tag 等 |
| **知识库管理** | 多知识库、文档状态管理、手动调整切片 |
| **外部数据源同步** | S3、Confluence、Notion、Google Drive、SharePoint、Discord、Jira、Gmail、Slack、Teams、Moodle |

### 2.2 检索与问答

| 功能模块 | 描述 |
|----------|------|
| **混合检索** | 向量检索（Dense）+ 关键词检索（Sparse/BM25）融合 |
| **多路召回** | 同时检索多个知识库，结果聚合排序 |
| **重排序（Rerank）** | 支持模型重排或基于 Token/Vector 权重的混合重排 |
| **RAPTOR** | 递归抽象摘要树检索，提升长文档跨段落理解能力 |
| **GraphRAG** | 知识图谱构建与图谱增强检索（支持 General 和 Light 两种模式） |
| **NL2SQL** | 自然语言转 SQL，支持数据库表结构问答 |
| **引用溯源** | 答案关联原文切片，支持高亮回溯 |
| **跨语言查询** | 多语言问题映射到文档语言检索 |

### 2.3 对话与 Chat

| 功能模块 | 描述 |
|----------|------|
| **多轮对话** | 维护对话历史，支持上下文关联问答 |
| **对话配置** | 可配置 LLM、提示词、检索参数、相似度阈值 |
| **Assistant/Dialog** | 命名对话助手，绑定知识库与 LLM 配置 |
| **流式输出** | SSE 流式推送答案 |
| **引用可视化** | 答案中嵌入文档引用快照 |

### 2.4 Agentic Workflow（Agent 编排）

| 功能模块 | 描述 |
|----------|------|
| **可视化画布** | 拖拽式 DAG 工作流编排（类 LangGraph/Dify 画布） |
| **内置组件** | LLM 生成、知识检索、分类器、条件分支、迭代、消息、变量赋值、Webhook、调用等 |
| **内置工具集** | Tavily 搜索、DuckDuckGo、Wikipedia、ArXiv、PubMed、GitHub、Google Scholar、Yahoo Finance、AkShare/Tushare、SQL 执行、代码执行、爬虫、DeepL 翻译、Email 等 |
| **预置 Agent 模板** | 深度研究、客服、股票研究报告、SEO 博客生成、SQL 助手、旅行规划、技术文档 QA 等 20+ 模板 |
| **代码执行沙箱** | Python/JS 代码执行器，gVisor 隔离的容器沙箱 |
| **MCP 集成** | 支持 Model Context Protocol，可作为 MCP Server 或调用外部 MCP 工具 |

### 2.5 LLM 与模型管理

| 功能模块 | 描述 |
|----------|------|
| **Chat LLM** | OpenAI、Azure OpenAI、Anthropic Claude、Google Gemini/Vertex AI、Qwen(阿里云)、智谱 GLM、Baidu 千帆、Groq、Mistral、ModelScope、Ollama（本地）等 |
| **Embedding 模型** | OpenAI、智谱、HuggingFace、Voyage AI、Infinity 本地等 |
| **Rerank 模型** | Cohere、Jina、本地 ONNX 模型等 |
| **CV/VLM 模型** | Google Gemini Vision、OpenAI GPT-4V 等多模态模型 |
| **TTS 模型** | 文字转语音支持 |
| **ASR 模型** | 语音转文字（Sequence2Text）支持 |
| **LiteLLM 统一代理** | 通过 LiteLLM 接入 100+ 模型提供商 |

### 2.6 平台能力

| 功能模块 | 描述 |
|----------|------|
| **REST API** | 完整 OpenAPI 规范，支持二次开发集成 |
| **Python SDK** | `ragflow-sdk` 提供知识库、对话、Agent 管理接口 |
| **MCP Server** | 将 RAGFlow 能力暴露为 MCP 协议端点 |
| **多租户** | 租户隔离，每个租户独立 LLM 配置、知识库、对话 |
| **用户管理** | 注册/登录/权限管理，支持 CAPTCHA |
| **可观测性** | 集成 Langfuse 追踪 LLM 调用链路 |
| **插件系统** | pluginlib 动态插件加载机制 |
| **管理控制台** | Admin Server 独立端口，系统级管理 |
| **Docker 部署** | CPU/GPU 镜像，支持 Helm Chart（Kubernetes） |

---

## 3. 系统架构

```
┌──────────────────────────────────────────────────────────┐
│                    客户端层                               │
│   Web UI (React/TS)    │    REST API    │    MCP Client  │
└──────────────┬─────────────────────────────────┬─────────┘
               │                                 │
┌──────────────▼─────────────────────────────────▼─────────┐
│                    API 网关层 (Nginx)                      │
└──────────────┬───────────────────────────────────────────┘
               │
┌──────────────▼───────────────────────────────────────────┐
│              Flask/Quart 后端服务 (:9380)                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐ │
│  │知识库管理 │ │对话管理  │ │Agent画布 │ │MCP Server  │ │
│  │(kb_app) │ │(dialog) │ │(canvas) │ │(:9382)     │ │
│  └──────────┘ └──────────┘ └──────────┘ └─────────────┘ │
└──────┬────────────────────┬──────────────────────────────┘
       │                    │
┌──────▼──────┐    ┌────────▼────────────────────────────┐
│  任务队列   │    │         核心处理层                   │
│  (Redis)   │    │  ┌──────────────┐ ┌───────────────┐  │
└──────┬──────┘    │  │  DeepDoc     │ │  RAG Pipeline │  │
       │           │  │ (文档解析/   │ │ (切分/嵌入/  │  │
┌──────▼──────┐    │  │  OCR/版面)  │ │  检索/重排)  │  │
│  任务执行器  │    │  └──────────────┘ └───────────────┘  │
│(task_exec.) │    │  ┌──────────────┐ ┌───────────────┐  │
└─────────────┘    │  │  GraphRAG    │ │  RAPTOR       │  │
                   │  │ (知识图谱)   │ │ (树形摘要)    │  │
                   │  └──────────────┘ └───────────────┘  │
                   └─────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼──────────────────┐
        │                           │                  │
┌───────▼──────┐  ┌─────────────────▼───┐  ┌──────────▼──────┐
│  向量/全文    │  │    关系型数据库      │  │   对象存储       │
│  检索引擎     │  │    (MySQL)          │  │   (MinIO/S3)    │
│ ES/Infinity  │  │  用户/知识库/文档    │  │  文档原文/图片   │
│ /OpenSearch  │  │  元数据管理          │  └─────────────────┘
└──────────────┘  └─────────────────────┘
```

### 核心数据流

```
文档上传 → MinIO存储 → 任务队列(Redis) → 任务执行器
    → DeepDoc解析 → 文本切分 → Embedding → ES/Infinity索引

用户提问 → API层 → 检索器(Dense+Sparse混合) → Rerank
    → LLM生成 → 引用注入 → 流式返回
```

---

## 4. 核心技术点

### 4.1 深度文档理解（DeepDoc）

这是 RAGFlow 最核心的差异化能力，自研文档处理引擎：

- **版面识别（Layout Recognition）**：ONNX 推理的神经网络模型，识别页面中的文字段落、标题、表格、图片、公式等区域
- **表格结构识别（Table Structure Recognizer）**：专用模型恢复表格行列结构
- **OCR 引擎**：支持扫描件，Paddle OCR 生态，ONNX Runtime 加速
- **图片语义理解**：调用 VLM（如 GPT-4V、Gemini）为文档中图片生成自然语言描述
- **第三方解析器集成**：MinerU（上交大）、Docling（IBM）作为可选解析后端

**多格式解析器链路**（`deepdoc/parser/`）：
```
PDF → pdf_parser.py (DeepDoc/PlainParser/VisionParser/MinerU/Docling)
DOCX → docx_parser.py
XLSX → excel_parser.py
PPTX → ppt_parser.py
HTML → html_parser.py
MD → markdown_parser.py
```

### 4.2 智能分块策略

区别于简单的固定长度切分，RAGFlow 实现了**场景化分块模板**：

| 模板 | 适用场景 | 核心逻辑 |
|------|----------|----------|
| `naive` | 通用文档 | 按段落/句子语义切分，合并短段 |
| `book` | 书籍类长文档 | 章节感知的层次合并 |
| `paper` | 学术论文 | 摘要/正文/参考文献分离 |
| `qa` | 问答对文档 | 问题-答案对识别与绑定 |
| `table` | 结构化表格 | 行级切片，保留表头上下文 |
| `code` | 代码文件 | tree-sitter 语法树切分（支持 Python/C++） |
| `laws` | 法律法规 | 条款/款/项层级识别 |
| `resume` | 简历 | 结构化字段提取 |
| `one` | 单文档整体 | 不切分，整体入库 |

### 4.3 混合检索与重排序

```
用户问题
    ↓
关键词提取（rag_tokenizer）
    ↓
┌────────────────┬──────────────────┐
│ 向量检索       │ 关键词检索        │
│ (Dense ANN)   │ (BM25/Sparse)    │
│ cosine sim    │ term frequency   │
└───────┬────────┴──────┬───────────┘
        │               │
        └──────┬─────────┘
               ↓
    混合相似度融合（tkweight + vtweight）
               ↓
    重排序（Cross-Encoder 模型 or 混合权重）
               ↓
    标签特征加权（Tag Feature Scoring）
               ↓
    Top-K 结果 → LLM 生成
```

关键实现（`rag/nlp/search.py`）：
- `rerank()`：基于 Token 相似度（BM25）与向量相似度加权融合
- `rerank_by_model()`：外部 Cross-Encoder 模型精排
- `_rank_feature_scores()`：基于 Tag/PageRank 特征的补充打分

### 4.4 RAPTOR（递归抽象摘要树）

解决**长文档跨段落推理**问题，实现文件在 `rag/raptor.py`：

1. 将文档 chunks 进行 Embedding
2. 用 UMAP 降维，Gaussian Mixture Model（GMM）聚类
3. 对每个簇调用 LLM 生成摘要
4. 摘要作为新的节点加入索引
5. 递归直至达到最大层数

检索时同时命中原始 chunks 和摘要节点，实现多粒度覆盖。

### 4.5 GraphRAG（知识图谱增强检索）

两种 Graph 模式（`graphrag/`）：

- **General 模式**：基于 Microsoft GraphRAG 思路，实体关系抽取 → 知识图谱构建 → 图查询 + 向量检索融合
- **Light 模式**：轻量级实体链接，减少 LLM 调用成本

核心 `KGSearch`（`graphrag/search.py`）：
- 用 LLM 将查询转为实体类型关键词
- 图谱实体检索 + 向量检索双路
- `entity_resolution.py`：实体消歧与归并

### 4.6 Agentic Workflow 引擎

基于 DAG 的工作流执行引擎（`agent/canvas.py`）：

```python
class Graph:
    # DSL 描述组件拓扑
    # components: {id: {obj, downstream, upstream}}
    # 执行引擎按拓扑序调用各组件
```

- **组件化设计**：每个节点是独立组件（LLM/Retrieval/Categorize/Switch/Iteration...）
- **变量系统**：`sys.query`、`sys.user_id`、自定义变量在组件间传递
- **ReAct 模式**：`agent_with_tools.py` 实现 Function Calling + ReAct 循环
- **MCP 工具调用**：通过 `MCPServerService` 接入外部 MCP 工具

### 4.7 代码执行沙箱

安全隔离的代码执行环境（`sandbox/`）：
- Docker 容器池管理（Python / Node.js 独立容器）
- gVisor 内核隔离（可选）
- 工作目录隔离：`/tmp/sandbox_{task_id}` → `/workspace/{task_id}`
- 资源限制与超时控制

---

## 5. 工程实现技术栈

### 5.1 后端框架

| 组件 | 技术选型 | 用途 |
|------|----------|------|
| Web 框架 | Flask 3.0 + Quart 0.20 | REST API（同步+异步混合） |
| WSGI/ASGI | Gunicorn + Uvicorn | 生产部署 |
| 身份认证 | Flask-Login + Flask-Session | 会话管理 |
| API 文档 | Flasgger (Swagger) | OpenAPI 规范生成 |
| ORM | Peewee 3.17 | MySQL 对象关系映射 |
| 任务队列 | Redis (Valkey) | 文档处理任务队列 |
| 异步并发 | Trio | 异步 IO 与并发控制 |

### 5.2 数据存储层

| 存储系统 | 版本/选型 | 用途 |
|----------|----------|------|
| **向量+全文检索** | Elasticsearch 8.12 / Infinity v0.6.6 / OpenSearch 2.19 | 文档向量索引 + BM25 全文检索（三选一） |
| **关系型数据库** | MySQL（via Peewee） | 用户、知识库、文档、对话元数据 |
| **缓存/消息队列** | Redis / Valkey 6.0 | 任务队列、LLM 结果缓存、Session 存储 |
| **对象存储** | MinIO / AWS S3 / Azure Blob / 阿里云 OSS | 文档原文、图片、模型文件 |
| **向量数据库（扩展）** | OceanBase（pgvector）、Infinity（自研）| 可选向量存储后端 |

### 5.3 AI/ML 组件

| 组件 | 技术 | 说明 |
|------|------|------|
| **推理加速** | ONNX Runtime（CPU）/ ONNX Runtime-GPU | DeepDoc 视觉模型本地推理 |
| **Embedding** | OpenAI / HuggingFace / Infinity-Embed | 文本向量化 |
| **分词/NLP** | 自研 rag_tokenizer + NLTK | 中英文混合分词、关键词提取 |
| **聚类** | scikit-learn GaussianMixture | RAPTOR 层次聚类 |
| **降维** | UMAP | RAPTOR 向量降维 |
| **机器学习** | XGBoost 1.6 | 文档特征辅助排序（可选） |
| **LLM 统一接口** | LiteLLM | 100+ 模型提供商统一 API |
| **图算法** | graspologic | GraphRAG 图统计与社区检测 |
| **语法树分析** | tree-sitter（Python/C++） | 代码文档智能切分 |

### 5.4 前端技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 框架 | React 18 + TypeScript | SPA 应用主框架 |
| 构建工具 | UmiJS（内置 Vite/Webpack） | 企业级 React 框架 |
| UI 组件库 | Ant Design + shadcn/ui | 主 UI 组件 + 自定义组件 |
| 状态管理 | Zustand | 轻量全局状态 |
| 样式 | Tailwind CSS | 原子化 CSS |
| HTTP | Axios | API 请求 |
| 流式 | EventSource (SSE) | 流式答案接收 |
| 画布 | React Flow / 自实现 DAG | Agent 工作流可视化画布 |

### 5.5 基础设施

| 组件 | 技术 | 说明 |
|------|------|------|
| 容器化 | Docker + Docker Compose | 服务编排 |
| Kubernetes | Helm Chart | 生产集群部署 |
| 反向代理 | Nginx | 静态资源 + API 代理 |
| 代码沙箱 | Docker 容器池 + gVisor | Python/JS 安全执行 |
| 可观测性 | Langfuse | LLM 调用链追踪 |
| 包管理 | uv（Python）/ npm（前端） | 依赖管理 |
| 代码规范 | Ruff（Python lint/format） | 代码质量 |
| 测试 | pytest（优先级标记：p1/p2/p3） | 后端单元/集成测试 |

### 5.6 外部服务集成

- **搜索工具**：Tavily、DuckDuckGo、SearXNG、Google Search、Bing
- **学术数据源**：ArXiv、PubMed、Google Scholar
- **金融数据**：AkShare、Tushare、Yahoo Finance、JIN10
- **协作平台**：Jira、Confluence、Notion、Discord、Slack、Teams
- **云存储**：S3、Google Drive、SharePoint、Dropbox
- **翻译**：DeepL
- **协议集成**：MCP（Model Context Protocol）

---

## 6. 业界方案对比

### 6.1 同类开源 RAG 框架横向对比

| 维度 | RAGFlow | LangChain | LlamaIndex | Dify | Haystack |
|------|---------|-----------|------------|------|----------|
| **定位** | 端到端 RAG 引擎 + Agent 平台 | LLM 应用开发框架 | RAG 框架 | LLM 应用平台 | NLP/RAG 框架 |
| **文档解析** | 自研 DeepDoc（最强）| 依赖第三方 | 依赖第三方 | 基础解析 | 依赖第三方 |
| **分块策略** | 10+ 场景化模板 | 规则切分 | 多种切分器 | 有限模板 | 规则切分 |
| **检索方式** | 混合检索（BM25+向量+Rerank） | 插件式组合 | 插件式组合 | 混合检索 | 混合检索 |
| **Agent 能力** | 可视化 DAG 画布 | 代码定义 | 代码定义 | 可视化画布 | 代码定义 |
| **GraphRAG** | 内置（General+Light） | 插件 | 插件 | 无 | 无 |
| **RAPTOR** | 内置 | 手动实现 | 内置 | 无 | 无 |
| **开箱即用** | 极高（Docker 一键） | 低（需编码） | 低（需编码） | 高 | 中 |
| **MCP 支持** | 内置 Server+Client | 插件 | 插件 | 有 | 无 |
| **多租户** | 原生支持 | 无 | 无 | 原生支持 | 无 |
| **可观测性** | Langfuse 集成 | LangSmith 集成 | Arize/Phoenix | 内置 | Prometheus |
| **向量 DB** | ES/Infinity/OpenSearch（可切换）| 100+ 向量 DB | 100+ 向量 DB | Weaviate/Qdrant 等 | Weaviate/OpenSearch |
| **代码执行沙箱** | 内置（Docker+gVisor）| 无 | 无 | 有 | 无 |
| **许可证** | Apache-2.0 | MIT | MIT | Apache-2.0 | Apache-2.0 |

### 6.2 文档解析方案对比

| 方案 | 技术路线 | 优势 | 劣势 |
|------|----------|------|------|
| **RAGFlow DeepDoc** | 神经网络版面分析 + OCR | 复杂版面效果好，可处理扫描件 | 需要 GPU 或 ONNX 推理环境 |
| **MinerU（上交大）** | PDF 多策略解析 | 公式/代码识别强 | 依赖复杂，速度较慢 |
| **Docling（IBM）** | 多格式统一解析 | 表格理解强，格式支持广 | 较新，社区相对小 |
| **LlamaParse（LlamaIndex）** | 云 API 服务 | 效果好，无需本地资源 | 付费，数据出境隐患 |
| **Unstructured** | 规则 + 模型混合 | 格式兼容性广 | 复杂文档效果一般 |
| **Azure Document Intelligence** | 云 OCR + 结构识别 | 企业级质量，稳定 | 付费，需 Azure 账户 |

### 6.3 向量检索方案对比

| 方案 | 检索类型 | 适用场景 |
|------|----------|----------|
| **Elasticsearch（ES）** | 全文 BM25 + 向量（kNN） | 大规模混合检索，运维成熟 |
| **Infinity（自研）** | 向量 + 稀疏检索 | 高性能，RAGFlow 原生集成 |
| **OpenSearch** | 全文 + 向量 | 开源 ES 替代，AWS 生态 |
| **Qdrant** | 向量为主 | 纯向量场景，性能极好 |
| **Weaviate** | 向量 + 全文 | 内置 BM25+向量混合 |
| **Milvus** | 向量为主 | 超大规模向量检索 |
| **pgvector** | 关系型 + 向量 | 简单场景，已有 PG 的团队 |
| **ChromaDB** | 向量为主 | 开发/原型阶段快速集成 |

### 6.4 Chunking 策略方案对比

| 策略 | 代表实现 | 核心思路 | 适用场景 |
|------|----------|----------|----------|
| **固定长度切分** | 基础方案 | 按 token 数硬切，加 overlap | 快速验证，质量一般 |
| **语义切分** | LangChain SemanticChunker | 相邻句子相似度低则切分 | 通用文档 |
| **递归字符切分** | LangChain RecursiveCharTextSplitter | 优先段落→句子→词 | 通用文档 |
| **场景化模板** | RAGFlow | 针对书籍/论文/法律等专用规则 | 垂直领域文档 |
| **RAPTOR 树状摘要** | RAGFlow / LlamaIndex | 多层摘要+原文并存 | 长文档跨段落推理 |
| **Late Chunking** | Jina AI | 先全文 Embedding 再切分 | 保留上下文语义 |
| **Hierarchical Chunking** | LlamaIndex | 小 chunk 检索，大 chunk 生成 | 精确检索+丰富上下文 |
| **Propositional Chunking** | dense-x-retrieval | LLM 提取原子命题 | 精确问答，成本高 |

### 6.5 GraphRAG 方案对比

| 方案 | 来源 | 核心思路 | 优势 | 劣势 |
|------|------|----------|------|------|
| **RAGFlow GraphRAG** | InfiniFlow | ES 存储图谱 + 向量混合检索 | 与 RAG 无缝集成 | 图能力相对基础 |
| **Microsoft GraphRAG** | Microsoft Research | 社区检测 + 层次摘要 | 全局查询能力强 | LLM 成本极高 |
| **LightRAG** | 香港大学 | 双层检索（局部+全局） | 低成本，效果不错 | 复杂度较高 |
| **Neo4j + LangChain** | 社区方案 | 专业图数据库 | 图查询能力最强 | 运维复杂，成本高 |
| **Nebula Graph** | NebulaGraph | 分布式图数据库 | 超大规模图 | 学习曲线陡峭 |

### 6.6 Agent 编排方案对比

| 方案 | 编程范式 | 特点 |
|------|----------|------|
| **RAGFlow Agent** | 可视化 DAG | 无代码/低代码，内置 RAG 组件，适合业务人员 |
| **LangGraph** | Python 代码 DSL | 灵活，适合工程师，状态机模型 |
| **Dify** | 可视化画布 | 与 RAGFlow 类似，生态更丰富 |
| **AutoGen（Microsoft）** | 多 Agent 对话 | 多 Agent 协作，代码执行能力强 |
| **CrewAI** | 角色扮演 + 工具 | 团队协作 Agent，易上手 |
| **Coze（字节）** | 可视化 + 插件 | 商业平台，集成豆包大模型 |
| **n8n** | 可视化工作流 | 通用自动化，非 AI 专用 |

---

## 7. 总结与评价

### 7.1 核心优势

1. **文档理解能力领先**：自研 DeepDoc 在复杂版面、扫描件、表格处理上显著优于通用方案
2. **端到端完整性**：从文档上传到生产级问答全链路自包含，部署简单
3. **分块策略丰富**：10+ 场景化模板避免通用切分的信息损失
4. **混合检索成熟**：BM25+向量+Rerank 三路融合，配合 Tag 特征排序
5. **高级检索算法**：内置 RAPTOR、GraphRAG，解决长文档和关联推理问题
6. **Agent 平台化**：可视化 DAG + 丰富工具集，无代码构建复杂 AI 工作流

### 7.2 潜在不足

1. **系统复杂性高**：依赖 MySQL + ES/Infinity + Redis + MinIO 四个中间件，运维成本高
2. **资源消耗大**：最低 16GB RAM，ONNX 推理对 CPU 压力较大，GPU 效果更佳
3. **GraphRAG 成本**：构建知识图谱需要大量 LLM 调用，小规模场景性价比低
4. **多语言支持**：对中文场景优化好，英文文档部分功能仍在完善
5. **向量 DB 耦合**：虽支持多种向量库，切换需要重新建索引，迁移成本存在

### 7.3 适用场景建议

| 场景 | 推荐度 | 理由 |
|------|--------|------|
| 企业知识库问答 | ★★★★★ | 核心设计目标，开箱即用 |
| 复杂 PDF 处理（扫描件/报表） | ★★★★★ | DeepDoc 核心优势 |
| 多知识库统一检索 | ★★★★☆ | 原生多知识库支持 |
| 复杂 Agent 工作流（客服/研究） | ★★★★☆ | 丰富模板，快速落地 |
| 简单 MVP 原型验证 | ★★★☆☆ | 系统较重，轻量场景用 LangChain 更快 |
| 超高并发生产系统 | ★★★☆☆ | 需要额外的扩展架构设计 |

---

*本文档基于 RAGFlow v0.22.1 源码分析生成，涵盖 `ragflow/` 项目根目录下所有主要模块。*
