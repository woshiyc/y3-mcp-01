# rag-doc-server 项目分析报告

## 一、项目定位

**文档 RAG 中间层服务**，承担两个核心角色：

- **写入端（数据源预训练）**：将多平台文档（Confluence、OnlyOffice、Affine、APITable、Nextcloud、P4）统一采集、格式转换后写入 Ragflow 向量数据库
- **读取端（AI Agent 知识网关）**：为 AI Agent 提供带用户权限控制的知识检索接口，屏蔽底层向量库细节

核心 RAG 能力（embedding、chunking、向量检索）由 Ragflow 实现，工作流编排由 Dify 完成，rag-doc-server 本身不做 AI，只做**数据进出的管道和权限门卫**。

---

## 二、主要功能模块

### 2.1 多平台文档接入

支持 6 种数据源，通过策略模式统一抽象：

| 数据源 | 类型 | 说明 |
|--------|------|------|
| Confluence | Wiki | 通过 MCP Atlassian 服务获取页面内容，支持附件/图片处理 |
| OnlyOffice | 文档协同 | 在线文档导出与解析 |
| Affine | 知识库 | 导出为 Markdown/图形内容解析 |
| APITable | 表格数据库 | 行级别增量同步，记录变更触发 RAG 更新 |
| Nextcloud | 文件系统 | 文件夹路径粒度的文档树同步 |
| P4 (Perforce) | 版本控制 | 按目录粒度分割为多文档 |

### 2.2 文档处理 Pipeline

基于状态机的多阶段文档处理流水线：

```
COLLECT → BLOCK → SEGMENT → INDEX → DONE
                                  ↓
                               FAILED（记录 stage + error_msg，可断点重试）
```

- **COLLECT**：从源系统拉取文档内容，转换为统一的 Markdown 格式
- **BLOCK**：物理分块，对每个块计算 MD5，与 MySQL 中已有记录对比，识别变化块
- **SEGMENT**：语义分析，调用 LLM 对变化区域进行语义段划分，生成摘要和上下文
- **INDEX**：将语义段写入 Ragflow 向量库，记录 chunk ID 映射关系

### 2.3 文档写入与增量更新

**写入链路（事件驱动）：**

```
文档变更事件 → RabbitMQ
  → Redis 去重防抖（ZSet + Hash）
  → 定时调度（500ms 合批）→ RabbitMQ
  → DocUploadRagConsumer（并发数=8）
  → DocActionProvider 拉取文档内容
  → Dify 工作流 → Ragflow embedding 入库
```

**增量更新（物理块 MD5 对比）：**
- 全文相同 → 直接跳过，零开销
- 有变化 → 仅将变化块及相邻语义段重新处理，不全量重建

### 2.4 文档检索（带权限控制）

**检索链路（两阶段权限过滤）：**

```
用户提问
  → 前过滤：根据用户所属 space 构建 metadata_condition，缩小向量检索范围
  → 调用 Dify/Ragflow 向量检索
  → ragId → docId 映射还原
  → 后过滤：文档级权限校验（剔除无权限文档）
  → token 截断（jtokkit 计算 token 数，控制 LLM context）
  → 返回 ChunkDocVo 列表
```

### 2.5 权限同步

- 各平台文档的可见用户列表同步至本地 `DocPermissionEntity`
- Confluence 支持实时权限推送（via MCP Atlassian + Feign）
- 检索时双重过滤（前过滤降低向量库查询量，后过滤保证权限准确性）

### 2.6 资产管理

- 支持 MinIO 和七牛云两种对象存储后端
- 文档中的图片附件自动上传至 OSS，存储 URL 关联关系
- 支持图片 AI 描述生成（MdParse 服务，底层 Gemini）
- 文件内容审核（涉黄/违规检测回调接口）

### 2.7 用户与认证

- 多种 OAuth 登录：Mattermost OAuth、OA 系统 OAuth
- Spring Security + Spring Session（Redis 存储）
- JWT 支持
- 用户与 Space 的关联关系管理

### 2.8 APITable 特殊处理

APITable 作为表格数据库，有独立的行级增量同步机制：
- `ApitableRecordChangeConsumer`：监听记录变更事件
- `ApitableRowChunkConsumer`：行转 chunk 逻辑
- `ApitableRowChunkFormatter`：格式化表格行为 RAG 友好的文本
- `ApitableSyncState`：记录同步状态，支持断点续传
- CAS（Compare-and-Swap）防止并发重复处理

---

## 三、核心技术点

### 3.1 策略模式的多源适配

`DocActionProvider` 接口统一定义数据源行为：

```java
public interface DocActionProvider {
    AppTypeEnum supportedType();
    DocFileContent getDocFileContent(UploadDocToRagDto dto);
    default List<DocFileContent> getDocFileContents(UploadDocToRagDto dto) { ... }
    default void syncPermission(UploadDocToRagDto dto, String docId, ...) { }
}
```

`DocActionFactory` 在启动时扫描所有实现类，通过 `AppTypeEnum` 路由，新增数据源只需实现接口，主流程零修改。

### 3.2 双层分块架构（物理层 + 语义层）

**物理层（变更检测锚点）：**
- 固定大小分块（1000 字符），边界永远不变
- 每块计算 MD5，持久化到 `doc_blocks` 表
- 与历史对比确定变化范围，实现真正的增量处理

**语义层（向量检索载体）：**
- 基于物理块范围，由 LLM 划分语义完整的段落
- 每个语义段包含：breadcrumb（文档路径面包屑）、summary（摘要）、实际内容
- 写入 Ragflow 时拼接 breadcrumb + summary，提升 embedding 质量
- 持久化到 `doc_semantic_segments`，记录 `rag_chunk_id` 映射

**两层分离的收益：**
- 物理层不要求语义完整（只做 MD5 对比），语义层不要求边界稳定（LLM 自由划分）
- 更新时只有变化的物理块对应的语义段需要重建，避免全量重处理

### 3.3 Pipeline 状态机 + CAS 并发控制

`DocPipelineStatusService` 维护每篇文档的处理状态：

- `getOrCreate` / `updateStage` / `markFailed`：基础状态流转
- `markStageIfCurrent`：CAS 操作，`UPDATE ... WHERE current_rag_id = ?`，防止并发 Consumer 重复推进
- `claimApitableSlot`：APITable 专用的分布式 slot 竞争，避免同一文档并发处理
- `listStuck`：查找卡住超时的 pipeline，供 nudge 定时任务重触发

### 3.4 Redis 去重防抖

文档变更事件频繁（协同编辑场景每秒多次触发）：
- ZSet 记录文档最后变更时间戳，消费端取 500ms 内未被"刷新"的事件
- Hash 记录文档当前处理状态，避免同一文档同时进入多条处理链
- 使用 Redisson 实现分布式锁（`LockService`），调度任务防并发

### 3.5 Token 管理

使用 `jtokkit` 库（OpenAI tokenizer 的 Java 实现）：
- 检索后对 chunk 内容按 token 数截断，避免超过 LLM context 限制
- 支持 cl100k_base 编码（GPT-4/Claude 兼容）

### 3.6 零拷贝哈希

使用 `zero-allocation-hashing`（xxHash64 算法）：
- 计算文档块哈希时无 GC 压力
- 比 MD5 快 3~5 倍，适合高频小块哈希场景

### 3.7 死信队列容错

`DocUploadRagConsumer` 消费失败时：

```java
} catch (Exception e) {
    log.error("处理失败，进入死信队列", e);
    channel.basicNack(deliveryTag, false, false); // 不重新入队，进死信
}
```

死信队列独立消费，支持告警和人工重试，不丢数据。

### 3.8 分布式定时任务锁

使用 ShedLock + Redis 实现：
- 防止多实例部署时定时任务重复执行
- `PathDatasetSyncScheduler`（凌晨 3 点同步文件路径树）使用 900 秒锁超时

---

## 四、工程技术栈

### 4.1 核心框架

| 技术 | 版本 | 用途 |
|------|------|------|
| Spring Boot | 3.3.0 | 应用框架 |
| Java | 21 | 运行时（使用虚拟线程友好的写法） |
| MyBatis-Plus | 3.5.5 | ORM，Lambda 查询，动态数据源 |
| Spring Security | (Boot 3.3) | 认证授权 |
| Spring Session (Redis) | (Boot 3.3) | 分布式 Session |

### 4.2 数据存储

| 技术 | 版本 | 用途 |
|------|------|------|
| MySQL | 8.2.0 | 文档元数据、pipeline 状态、权限关系、chunk 映射 |
| Redis (Redisson) | 3.17.7 | Session、去重防抖、分布式锁 |
| Liquibase | 4.27.0 | 数据库版本管理 |
| H2 | - | 单元测试内存数据库 |
| MinIO | 8.5.7 | 自托管对象存储 |
| 七牛云 SDK | 7.15.0 | 云端对象存储备选 |

### 4.3 消息与通信

| 技术 | 版本 | 用途 |
|------|------|------|
| RabbitMQ (Spring AMQP) | - | 异步文档处理队列、死信队列 |
| OpenFeign | 4.1.3 | HTTP 客户端，调用 Dify/Ragflow/第三方平台 |
| Apache HttpClient5 | - | 底层 HTTP 支持 |
| gRPC + Protobuf | 1.59.1 / 3.25.0 | 与其他后端微服务通信 |
| Socket.IO Client | 2.1.0 | 实时事件推送 |

### 4.4 文档处理

| 技术 | 版本 | 用途 |
|------|------|------|
| Apache PDFBox | 3.0.1 | PDF 解析 |
| EasyExcel | 4.0.1 | Excel 导入导出（用户批量操作） |
| JavaCV + FFmpeg | 1.5.9 | 视频/媒体文件处理 |
| Beetl | 3.15.10 | 模板引擎（消息/通知模板） |
| Pinyin4j | 2.5.0 | 拼音转换（搜索辅助） |

### 4.5 AI/RAG 相关

| 技术 | 用途 |
|------|------|
| Ragflow（外部服务） | 向量数据库，负责 embedding + 检索 |
| Dify（外部服务） | 工作流编排，封装 upload/retrieve 流程 |
| MdParse（内部服务） | 文档解析服务，底层调用 Gemini，支持图片 AI 描述 |
| jtokkit (0.6.1) | OpenAI tokenizer Java 实现，token 计数与截断 |
| zero-allocation-hashing (0.16) | xxHash64，高性能文档块哈希 |

### 4.6 工程工具

| 技术 | 用途 |
|------|------|
| Hutool（Core/JSON/Crypto/HTTP/JWT） | 通用工具库 |
| Lombok | 代码生成（Builder、Slf4j 等） |
| Knife4j (OpenAPI3) | API 文档（Swagger 增强版） |
| Spring Actuator + Prometheus | 监控指标暴露 |
| ShedLock + Redis | 分布式定时任务锁 |
| AspectJ | AOP（日志、权限切面） |
| Dynamic Datasource | 多数据源动态切换 |

---

## 五、第三方系统集成（Feign Clients）

| Feign 接口 | 对接系统 | 职责 |
|-----------|---------|------|
| `RagflowService` | Ragflow | 上传文档、删除 chunk、向量检索、path dataset 管理 |
| `DifyService` | Dify | 工作流触发（上传/检索） |
| `McpAtlassianService` | MCP Atlassian | 获取 Confluence 页面、权限信息 |
| `ConfluenceDownloadService` | Confluence | 附件/图片下载 |
| `AffineService` | Affine | 文档导出 |
| `ApitableService` | APITable | 表格记录、Schema 获取 |
| `OnlyofficeService` | OnlyOffice | 文档内容获取 |
| `MdParseFeign` | MdParse | 文档解析、图片 AI 描述 |
| `MattermostOAuthFeign` | Mattermost | OAuth 认证 |
| `MattermostMessageFeign` | Mattermost | 消息通知（Bot 推送） |
| `OAAuthFeign` / `OAChnService` | OA 系统 | 认证 + 消息通道 |
| `CollabspaceService` | Collabspace | 文档变更事件接收 |

---

## 六、业界常用技术方案对比

### 6.1 文档分块策略对比

| 方案 | 实现方式 | 优点 | 缺点 | 适用场景 |
|------|---------|------|------|---------|
| **固定字符数分块**（当前基础） | 按字符数硬切（16384 字符/块） | 实现简单、边界确定 | 破坏语义完整性（句子/表格被截断） | 快速原型 |
| **递归字符分割**（LangChain RecursiveCharacterTextSplitter） | 优先按段落→句子→字符递归分割 | 比固定切割语义更完整 | 不保证语义段完整，无上下文关联 | 通用文档 |
| **语义分割**（SemanticChunker） | 用 embedding 相似度检测话题边界 | 语义完整性高 | 计算成本高，边界不稳定（不可复现） | 高质量知识库 |
| **层级分块**（HierarchicalNodeParser） | 保留文档树结构，生成父子 node | 支持多粒度检索 | 实现复杂，存储量大 | 结构化文档 |
| **双层分块**（本项目设计） | 物理层（MD5 稳定）+ 语义层（LLM 划分） | 增量更新效率高，兼顾语义完整 | 依赖 LLM 调用，初次成本高 | 频繁更新的文档库 |

### 6.2 向量检索策略对比

| 方案 | 原理 | 优点 | 缺点 |
|------|------|------|------|
| **单路向量检索**（当前） | 纯语义向量相似度 | 实现简单 | 关键词精确匹配弱，召回率受 embedding 质量限制 |
| **混合检索**（Hybrid Search） | 向量检索 + BM25 关键词检索，加权融合 | 语义 + 精确两者兼顾 | 需要维护两套索引，融合权重需调优 |
| **两阶段检索**（Cohere Rerank） | 粗召回 50~100 候选 + Cross-encoder 精排 | 不相关结果从 30% 降至 <10% | 精排模型推理成本，延迟增加 |
| **图谱增强检索**（GraphRAG） | 向量检索 + 知识图谱关系遍历 | 能回答跨文档综合问题 | 图谱构建成本高（LLM 抽取实体），索引成本是纯 RAG 的 3~5 倍 |
| **多路检索 + 路由**（LlamaIndex Router） | 多种检索器，自动选择最合适的策略 | 灵活适配不同问题类型 | 路由判断引入额外 LLM 调用 |

### 6.3 权限控制方案对比

| 方案 | 实现 | 优点 | 缺点 |
|------|------|------|------|
| **纯后过滤**（Post-filter） | 检索结果出来后再校验权限 | 实现最简单 | 无权限文档参与了向量检索，浪费算力；结果集可能大量被过滤导致返回不足 |
| **前过滤 metadata_condition**（本项目） | 检索前将用户所在 space 的文档 ID 集合作为过滤条件下发向量库 | 减少无效检索；避免返回无权限内容 | metadata_condition 数据量大时有性能开销；需要 space 数据实时同步 |
| **文档级加密**（企业级方案） | 不同权限文档用不同密钥加密 embedding | 安全性最高 | 实现复杂度极高，密钥管理困难 |
| **命名空间隔离**（Glean 方案） | 不同组织/团队的数据存放在独立的向量库命名空间中 | 物理隔离，安全彻底 | 跨组织检索困难，运维成本高 |

### 6.4 写入管道可靠性对比

| 方案 | 实现 | 可靠性 | 吞吐量 | 复杂度 |
|------|------|--------|--------|--------|
| **同步推送**（早期实现） | 变更事件 → 同步调用 Dify | 低（单点故障丢数据） | 低（串行）| 低 |
| **MQ + basicAck**（本项目当前） | 异步消费，死信队列容错 | 高（不丢消息） | 中（并发消费） | 中 |
| **CDC（Change Data Capture）** | 数据库 binlog → Debezium → MQ | 极高（数据库级保证） | 高 | 高 |
| **Kafka + 幂等生产者** | 端到端 exactly-once 语义 | 极高 | 极高 | 高 |
| **本项目 + 物理块 MD5 幂等** | MQ + CAS + MD5 去重，重复消费自动跳过 | 高 | 中高（增量处理快） | 中 |

### 6.5 RAG 系统整体方案对比

| 维度 | **本项目（rag-doc-server）** | **Glean** | **RAGflow** | **LlamaIndex** | **Dify RAG** |
|------|-------------------------|-----------|-------------|----------------|-------------|
| 数据接入 | 6 个连接器，策略模式可扩展 | 100+ 连接器 | 需自建 | 100+ Loader | 有限内置 |
| 文档解析 | MdParse（Gemini）+ PDFBox | 自研 | 自研 | LlamaParse | 内置 |
| 分块策略 | 双层（物理+语义） | 未公开 | 固定/语义 | 多种可选 | 固定/语义 |
| 权限控制 | 双重过滤（前+后） | 实时同步 100+ 平台 | 无 | 无 | 无 |
| 增量更新 | MD5 级别增量 | 自动 | 全量替换 | 需自建 | 全量替换 |
| 知识图谱 | 规划中 | 企业知识图谱（核心） | 无 | 支持 | 无 |
| 检索策略 | 单路+权限过滤 | 混合+个性化 | 混合检索 | 多路+路由 | 混合检索 |
| 部署方式 | 私有化 | SaaS | 私有化 | 框架（需自建服务） | 私有化/SaaS |
| 成本 | 自研维护成本 | 高昂商业授权 | 开源免费 | 开源框架 | 开源+商业 |

---

## 七、当前不足与规划路线

### 7.1 已知不足

| 问题 | 影响 | 规划方案 |
|------|------|---------|
| 大文件 OOM 风险 | 单文档内存峰值 ≈ 原文 4~5 倍 | 流式物理分块（固定大小 buffer） |
| 批量处理吞吐低 | ~0.17 篇/秒，200 篇需 20+ 分钟 | 增量更新（MD5 对比跳过未变内容） |
| 单路召回 | 关键词精确匹配弱 | 混合检索（向量 + BM25） |
| 无查询改写 | 用户原始问题直接用于检索 | 接入查询改写/扩展 |
| 无评估体系 | 优化全凭主观感觉 | rag-eval-server（检索日志+评估指标） |
| 无知识图谱 | 跨文档关联问答能力弱 | rag-graph-server（元数据图谱→实体关系） |

### 7.2 改造路线图

**Phase 1（高优先级）**：消费者死信队列容错、Feign 超时熔断、pipeline 状态表

**Phase 2（高优先级）**：流式物理分块 + MD5 增量更新

**Phase 3（中优先级）**：语义层标注（直接调 LLM API，不走 Dify）

**Phase 4（中优先级）**：检索增强 + Agent/MCP 接口暴露

---

## 八、项目结构概览

```
src/main/java/com/yottastudios/ns/ragdoc/
├── app/           # 平台枚举（AppTypeEnum）和通用 Action 接口
├── asset/         # 资产管理（OSS 上传、内容审核）
├── auth/          # 认证（OAuth 模板方法、Session 配置）
├── base/          # 基础能力（系统配置、日历、节点树）
├── core/          # 核心抽象（BaseEntity、异常体系、响应封装）
├── doc/           # 核心模块
│   ├── action/    # 各平台 DocActionProvider 实现（策略模式）
│   ├── consumer/  # RabbitMQ 消费者（文档上传、权限同步、APITable）
│   ├── pipeline/  # Pipeline 状态机（COLLECT→BLOCK→SEGMENT→INDEX→DONE）
│   ├── manager/   # 业务编排（DocQueryManager、DocUpdateManager）
│   ├── scheduler/ # 定时任务（路径同步、卡住 pipeline 重触发）
│   └── service/   # 基础数据服务（docRagRel、docBlock、docSegment）
├── image/         # 图片处理服务
├── interfaces/    # gRPC 接口（AuthFacade）
├── shared/        # 横切关注点（配置、缓存、MQ、安全、工具）
├── space/         # 空间管理（Space、SpaceUserRel）
├── starter/       # 自定义 Starter（OSS、Socket.IO）
├── third/         # 第三方服务 Feign 客户端
└── user/          # 用户管理
```

---

*生成时间：2026-05-12*
