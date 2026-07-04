# Logara AI 业务逻辑文档

> 本文档系统梳理 Logara AI 的业务目标、核心流程、数据模型与 API 职责，便于产品、开发与运维快速理解系统行为。
>
> 相关文档：[架构深度解析](./architecture_deep_dive.md) · [服务级向量搜索](./service-scoped-vector-search.md) · [README](../README.md)

---

## 1. 产品定位

**Logara AI** 是一个面向可观测性（Observability）的日志智能平台，核心目标是将原始、嘈杂的日志流转化为**可检索、可理解、可行动**的洞察。

| 维度 | 说明 |
|------|------|
| **领域** | 分布式系统日志采集、语义检索、根因分析、异常关联 |
| **当前阶段** | Alpha（采集管道与 embedding 策略仍在迭代） |
| **核心价值** | 从 keyword grep 转向自然语言语义搜索；结合向量库 + GLM LLM 做 RAG 分析 |
| **安全原则** | 日志在进入队列、向量化、AI 分析前必须先脱敏 |

### 1.1 四大业务能力

```mermaid
graph TB
    Root(("Logara AI"))

    subgraph S1["语义搜索"]
        direction TB
        S1a["自然语言查询"]
        S1b["服务级隔离"]
        S1c["Qdrant 向量检索"]
    end

    subgraph S2["根因分析"]
        direction TB
        S2a["RAG 上下文检索"]
        S2b["GLM 解释生成"]
        S2c["Incident Memory 缓存"]
    end

    subgraph S3["日志降噪"]
        direction TB
        S3a["语义去重聚类"]
        S3b["Cluster 元数据"]
        S3c["减少存储膨胀"]
    end

    subgraph S4["安全合规"]
        direction TB
        S4a["PII 自动脱敏"]
        S4b["入队前清洗"]
        S4c["敏感数据检测 API"]
    end

    Root --> S1
    Root --> S2
    Root --> S3
    Root --> S4
```

### 1.2 四大能力详解与示例

---

#### 能力一：语义搜索（Semantic Log Search）

**解决什么问题**

传统 `grep "timeout"` 只能匹配字面量，搜不到 *"connection pool exhausted"*、*"checkout stalled waiting for DB"* 这类语义相近但措辞不同的日志。Logara 把日志转成 1024 维向量（BAAI/bge-m3），在 Qdrant 里按**语义相似度**检索。

**工作原理**

1. 用户输入自然语言查询（如 `"支付环节数据库连接失败"`）
2. 查询文本同样生成 embedding
3. 在 Qdrant `logs` 集合中做 cosine 最近邻搜索
4. **强制按 `service_id` 过滤**，避免把 `orders-api` 的日志混入 `payments-api` 的结果

**与传统 grep 对比**

| 场景 | grep | Logara 语义搜索 |
|------|------|----------------|
| 查 `"database timeout"` | 只命中含这两个词的日志 | 也能命中 `"Connection pool exhausted after 30s"` |
| 跨服务排查 | 需分别 grep 各服务日志 | 必须指定 `service_id`，结果不串服 |
| 拼写/措辞变化 | 完全匹配才命中 | 向量空间中的语义相近即可命中 |

**示例：支付服务超时排查**

假设 `payments-api` 曾写入以下日志（已通过 log-processor 向量化）：

```json
{ "service_id": "payments-api", "level": "ERROR", "message": "Connection pool exhausted waiting for checkout-db" }
{ "service_id": "payments-api", "level": "WARN",  "message": "Slow query on orders table took 4.2s" }
{ "service_id": "orders-api",   "level": "ERROR", "message": "Connection pool exhausted waiting for checkout-db" }
```

开发者用自然语言搜索（**不会**搜到 `orders-api` 的日志）：

```bash
curl "http://localhost:8000/search?query=checkout%20database%20timeout&service_id=payments-api&severity=ERROR&limit=5"
```

**预期返回（示意）**

```json
{
  "query": "checkout database timeout",
  "service_id": "payments-api",
  "limit": 5,
  "results": [
    {
      "id": "a1b2c3...",
      "score": 0.89,
      "payload": {
        "service_id": "payments-api",
        "level": "ERROR",
        "message": "Connection pool exhausted waiting for checkout-db",
        "timestamp": "2026-07-02T10:15:00Z"
      }
    }
  ]
}
```

**关键代码路径：** `backend/routes/search.py` → `QdrantVectorStore.semantic_search()`

**适用场景**

- On-call 工程师用口语化描述快速定位相关错误
- 按 `environment=production`、`severity=ERROR` 缩小范围
- 微服务架构下按服务边界隔离检索

---

#### 能力二：根因分析（Root Cause Synthesis / Explain）

**解决什么问题**

找到相关日志后，工程师仍需要人工串联上下文、判断根因、想修复方案。Explain 能力用 **RAG（检索增强生成）** 自动完成这一步：先从 Qdrant 拉取相似历史日志作为上下文，再交给 GLM 生成 SRE 风格的分析报告。

**工作原理**

```mermaid
sequenceDiagram
    participant Dev as 开发者
    participant AI as Insight Engine
    participant Cache as incident_memory
    participant Q as Qdrant logs
    participant LLM as GLM

    Dev->>AI: POST /explain
    AI->>Cache: 是否有过相似错误?
    alt 相似度 ≥ 0.95
        Cache-->>Dev: 直接返回历史解释（跳过 LLM）
    else 缓存未命中
        AI->>Q: 检索 Top-K 上下文日志
        Q-->>AI: 相关日志列表
        AI->>LLM: 错误 + 上下文 → 根因分析
        LLM-->>AI: 解释 + 修复建议
        AI->>Cache: 存入 incident_memory
        AI-->>Dev: ExplainResponse
    end
```

**示例：Redis 连接失败**

**Step 1 — 先写入一批上下文日志**

```bash
curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d '{
  "service_id": "cart-service",
  "level": "WARN",
  "message": "Redis latency p99 exceeded 200ms threshold"
}'

curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d '{
  "service_id": "cart-service",
  "level": "ERROR",
  "message": "Connection refused to redis:6379 — maxclients reached"
}'
```

**Step 2 — 请求根因解释**

```bash
curl -X POST http://localhost:8001/explain -H "Content-Type: application/json" -d '{
  "error_message": "Connection refused to redis:6379",
  "service_id": "cart-service",
  "context_limit": 5
}'
```

**Step 3 — 典型响应结构**

```json
{
  "explanation": "1. 错误含义：cart-service 无法连接 Redis，连接被拒绝。\n\n2. 可能根因：结合上下文日志，Redis 延迟在错误前已升高（p99 > 200ms），且出现 maxclients 相关报错，说明 Redis 连接数耗尽，新连接被拒绝。\n\n3. 修复建议：\n   - 检查 Redis maxclients 配置与当前连接数\n   - 排查 cart-service 是否存在连接泄漏\n   - 考虑增加 Redis 实例或启用连接池上限",
  "context_logs": [
    {
      "message": "Redis latency p99 exceeded 200ms threshold",
      "level": "WARN",
      "service_id": "cart-service",
      "timestamp": "2026-07-02T10:12:00Z"
    },
    {
      "message": "Connection refused to redis:6379 — maxclients reached",
      "level": "ERROR",
      "service_id": "cart-service",
      "timestamp": "2026-07-02T10:13:05Z"
    }
  ],
  "model": "glm-5.1"
}
```

**Incident Memory 缓存示例**

同一错误第二次出现时：

```bash
# 再次请求相同 error_message
curl -X POST http://localhost:8001/explain -H "Content-Type: application/json" -d '{
  "error_message": "Connection refused to redis:6379",
  "service_id": "cart-service"
}'
```

若向量相似度 ≥ **0.95**，直接返回缓存，`model` 字段显示 `"glm-5.1 (cached)"`，`context_logs` 为空——**节省 LLM 调用成本与延迟**。

**关键代码路径：** `insight-engine/services/explain.py` → `ExplainService.explain()`

**适用场景**

- 新人 on-call 快速理解陌生错误
- 重复性故障的秒级 RCA 响应
- 把历史 incident 知识沉淀到 `incident_memory` 集合

---

#### 能力三：日志降噪（Semantic Duplicate Clustering）

**解决什么问题**

生产环境中，同一条错误可能在几秒内重复出现数千次（如 `"Database timeout for user 123"`、`"... user 456"`、`"... user 789"`）。若每条都写入 `logs` 集合，会造成：

- Qdrant 存储膨胀
- 语义搜索结果被重复日志淹没
- Dashboard 噪声极大，难以看到"真正有多少种不同错误"

Logara 在 log-processor 异步管道中用**语义聚类**把"意思相同、细节不同"的日志合并。

**工作原理**

1. log-processor 消费 Redis 队列，为每条日志生成 embedding
2. 在 `log_clusters` 集合中搜索最近邻
3. 相似度 **≥ 0.92**（默认）→ 判定为重复，**只更新 cluster 元数据，不写入 `logs`**
4. 相似度 < 0.92 → 新建 cluster，同时写入 `logs` + `log_clusters`

**示例：同一错误的三次出现**

| 次序 | 原始日志 | log-processor 行为 |
|------|----------|-------------|
| 第 1 条 | `ERROR: Database timeout for user 123` | 新建 cluster，写入 `logs` + `log_clusters` |
| 第 2 条 | `ERROR: Database timeout for user 456` | 相似度 0.95 → `is_duplicate=true`，仅更新 cluster |
| 第 3 条 | `ERROR: Database timeout for user 789` | 同上，`occurrence_count` 变为 3 |

**聚类后的 cluster 元数据（写入 `log_clusters`）**

```json
{
  "cluster_id": "cluster-abc123",
  "representative_log": "ERROR: Database timeout for user 123",
  "occurrence_count": 3,
  "first_seen": "2026-07-02T10:00:00Z",
  "last_seen": "2026-07-02T10:02:00Z",
  "sample_logs": [
    "ERROR: Database timeout for user 123",
    "ERROR: Database timeout for user 456",
    "ERROR: Database timeout for user 789"
  ],
  "similarity_score_average": 0.95,
  "service_name": "payments-service",
  "cluster_summary": "Error cluster: database timeout",
  "cluster_label": "error-database-timeout"
}
```

**与"不同错误"的对比**

以下两条**不会**被合并（相似度低于 0.92）：

```
ERROR: Database timeout for user 123        → cluster A
ERROR: Payment gateway returned HTTP 502    → cluster B（全新错误模式）
```

**降噪效果量化**

```
duplicate_reduction_percentage = ((occurrence_count - 1) / total_logs) × 100
```

上例中 3 条日志合并为 1 个 cluster + 1 条 `logs` 记录，降噪约 **66.7%**。

**可调参数**

| 环境变量 | 默认值 | 调优建议 |
|----------|--------|----------|
| `DUPLICATE_SIMILARITY_THRESHOLD` | `0.92` | 降低 → 更激进合并；提高 → 减少误合并 |
| `MAX_CLUSTER_SAMPLE_SIZE` | `5` | cluster 中保留的样本条数 |
| `ENABLE_DUPLICATE_CLUSTERING` | `true` | 冷启动时可设为 `false` 跳过聚类 |

**关键代码路径：** `backend/worker.py` → `DuplicateClusteringService.assign_to_cluster()`

**适用场景**

- 高 QPS 服务的大量重复 ERROR 日志
- 降低向量库存储与搜索噪声
- Dashboard 展示"错误种类数"而非"错误条数"

---

#### 能力四：安全合规（Security-Aware Log Sanitization）

**解决什么问题**

日志里经常意外携带 JWT、API Key、邮箱、信用卡号等敏感信息。若这些原文进入 Redis 队列、Qdrant 向量库或 GLM 上下文，会造成**数据泄露与合规风险**。Logara 在**入队之前**强制脱敏，确保下游组件只看到清洗后的内容。

**工作原理**

```mermaid
flowchart LR
    Raw["原始日志<br/>含 JWT / API Key"] --> Redactor["Redactor.redact_with_summary()"]
    Redactor --> Clean["脱敏后日志<br/>[JWT] / [API_KEY]"]
    Clean --> Queue["Redis 队列"]
    Clean --> Metrics["脱敏统计 metrics"]

    Queue --> LP["log-processor 向量化"]
    LP --> Qdrant["Qdrant 存储"]
    Qdrant --> LLM["GLM 分析"]

    style Raw fill:#ffcccc
    style Clean fill:#ccffcc
```

**内置脱敏规则（`backend/utils/redaction.py`）**

| 规则标签 | 匹配内容 | 脱敏后 |
|----------|----------|--------|
| `JWT` | `eyJ...` 三段式 token | `[JWT]` |
| `AWS_ACCESS_KEY` | `AKIA...` 16 位 | `[AWS_ACCESS_KEY]` |
| `API_KEY` | `sk-`、`ghp_`、`xoxb-` 等前缀 | `[API_KEY]` |
| `BEARER` | `Bearer eyJ...` | `[BEARER]` |
| `EMAIL` | 标准邮箱格式 | `[EMAIL]` |
| `CREDIT_CARD` | 13–19 位数字（Luhn 校验） | `[CREDIT_CARD]` |
| `IPV4`（可选） | IPv4 地址 | `[IPV4]` |

**示例：含敏感信息的日志接入**

**接入前（客户端发送）**

```json
{
  "service_id": "auth-service",
  "level": "ERROR",
  "message": "Login failed for user admin@company.com with token Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c and api_key sk-live-abc123xyz789secret"
}
```

**入队后（Redis / Qdrant / LLM 实际看到的）**

```
Login failed for user [EMAIL] with token [BEARER] and api_key [API_KEY]
```

**脱敏统计（Redaction Observability）**

每次脱敏会记录匹配摘要，便于运维审计：

```json
{
  "redaction_summary": {
    "EMAIL": 1,
    "BEARER": 1,
    "API_KEY": 1
  }
}
```

**独立安全 API 示例**

不经过 ingestion 管道，也可单独调用脱敏接口：

```bash
# 检测敏感信息（不脱敏）
curl -X POST http://localhost:8000/api/security/detect-sensitive \
  -H "Content-Type: application/json" \
  -d '{"text": "Contact support@example.com or use key sk-test-1234567890abcdef"}'

# 执行脱敏
curl -X POST http://localhost:8000/api/security/redact \
  -H "Content-Type: application/json" \
  -d '{"text": "Contact support@example.com or use key sk-test-1234567890abcdef"}'
```

**配置项**

```bash
REDACT_ENABLED=true                          # 总开关
REDACT_PATTERNS=jwt,api_key,email,bearer     # 启用的规则
REDACT_IPV4=false                            # 是否掩码 IP
```

**关键代码路径：** `backend/services/ingestion.py` → `Redactor.redact_with_summary()`（入队前调用）

**适用场景**

- 多租户 SaaS 平台的日志合规
- 防止 API Key 通过日志泄露到 LLM 训练/推理上下文
- 满足 GDPR / 等保等对 PII 的处理要求

---

### 1.3 四大能力协作：完整故障排查示例

以下是一个四大能力**串联使用**的真实场景：

**背景：** 生产环境 `payments-api` 在 10:00–10:05 出现大量结账失败告警。

| 步骤 | 能力 | 操作 | 效果 |
|------|------|------|------|
| 1 | 安全合规 | 应用 SDK 上报含用户邮箱的 ERROR 日志 | 邮箱被脱敏后再入队，LLM 不会看到 PII |
| 2 | 日志降噪 | 500 条 `"Database timeout for user N"` 重复 ERROR | 合并为 1 个 cluster，`occurrence_count=500` |
| 3 | 语义搜索 | `GET /search?query=checkout database timeout&service_id=payments-api` | 命中 cluster 代表日志 + 相关 WARN |
| 4 | 根因分析 | `POST /explain` 传入 `"Database timeout during checkout"` | GLM 结合上下文给出"连接池耗尽"根因与修复步骤 |
| 5 | 根因分析（缓存） | 10 分钟后同类错误再次触发 Explain | Incident Memory 命中，秒级返回历史 RCA |

```mermaid
flowchart LR
    A["① 安全合规<br/>脱敏入队"] --> B["② 日志降噪<br/>500条→1 cluster"]
    B --> C["③ 语义搜索<br/>自然语言定位"]
    C --> D["④ 根因分析<br/>RAG + GLM"]
    D --> E["⑤ 缓存命中<br/>Incident Memory"]

    style A fill:#ffe0e0
    style B fill:#e0f0ff
    style C fill:#e0ffe0
    style D fill:#fff0e0
    style E fill:#f0e0ff
```

---

## 2. 系统架构总览

Logara 采用**微服务 + 异步队列**架构，将高吞吐写入与计算密集的向量化/AI 推理解耦。

```mermaid
graph TB
    subgraph Sources["日志来源"]
        Docker[Docker / K8s]
        App[应用 SDK]
        OTel[OTel Collector]
    end

    subgraph Backend["Backend · FastAPI :8000"]
        Ingest[IngestionService]
        Redact[Redactor 脱敏]
        Parser[LogParser 解析]
        QueuePush[Redis LPUSH]
        SearchGET[GET /search<br/>服务级搜索]
        SearchPOST[POST /search<br/>全局搜索 + LLM]
    end

    subgraph Async["异步处理"]
        Redis[(Redis<br/>log_queue)]
        LP[worker.py<br/>Log Processor]
        Cluster[DuplicateClusteringService]
    end

    subgraph Storage["向量存储"]
        Qdrant[(Qdrant)]
        LogsCol[logs 集合]
        ClusterCol[log_clusters 集合]
        IncidentCol[incident_memory 集合]
    end

    subgraph AI["Insight Engine · FastAPI :8001"]
        AISearch[SearchService]
        Explain[ExplainService]
        IncidentMem[IncidentMemoryService]
    end

    subgraph External["外部 AI 服务"]
        Embed[SiliconFlow<br/>BAAI/bge-m3]
        GLM[GLM LLM<br/>OpenAI 兼容 API]
    end

    subgraph UI["前端"]
        Frontend[React SPA<br/>Dashboard / LogExplorer]
    end

    Sources --> Ingest
    Ingest --> Redact --> Parser --> QueuePush --> Redis
    Redis --> LP
    LP --> Embed
    LP --> Cluster
    LP --> LogsCol
    Cluster --> ClusterCol
    LogsCol --- Qdrant
    ClusterCol --- Qdrant
    IncidentCol --- Qdrant

    SearchGET --> Qdrant
    SearchPOST --> Qdrant
    SearchPOST --> GLM
    AISearch --> Qdrant
    Explain --> AISearch
    Explain --> IncidentMem
    Explain --> GLM
    IncidentMem --> IncidentCol

    Frontend --> Backend
```

### 2.1 组件职责一览

| 组件 | 端口/进程 | 核心职责 |
|------|-----------|----------|
| **Backend** | `:8000` | HTTP 接入、脱敏、解析、入队、健康检查、告警/解析/安全扩展 API |
| **Log Processor** | `python worker.py` | 消费 Redis 队列、生成 embedding、语义聚类、写入 Qdrant |
| **Insight Engine** | `:8001` | 语义搜索、RAG 根因解释、Incident Memory 缓存 |
| **Frontend** | Vite dev / nginx | Dashboard 统计、LogExplorer 日志浏览 |
| **Redis** | `:6379` | 异步队列 `log_queue`，LRU 512MB |
| **Qdrant** | `:6333` | 三集合向量存储与 metadata 过滤 |

---

## 3. 核心业务流

### 3.1 日志采集（Ingestion）

采集是系统的**唯一写入入口**，支持多种 payload 格式，统一标准化后入队。

```mermaid
flowchart TD
    A[客户端 POST 请求] --> B{Payload 类型?}

    B -->|log_data 字符串| C[LegacyRawLogIngestRequest]
    B -->|单条结构化 JSON| D[StructuredLogIngestRequest<br/>必须含 service_id/service]
    B -->|logs 数组| E[BatchLogIngestRequest]
    B -->|OTel resourceLogs| F[POST /v1/logs<br/>parse_otel_log_payload]

    C --> G[LogParser.parse_line]
    D --> H[字段校验 + normalize_timestamp]
    E --> I[逐条标准化]
    F --> J[OTel → NormalizedLog]

    G --> K[Redactor 脱敏]
    H --> K
    I --> K
    J --> K

    K --> L[extract_service_id]
    L --> M[构建 QueuePayload<br/>parsed + metadata]
    M --> N[Redis LPUSH log_queue]
    N --> O[返回 success_queued]

    style K fill:#ffe0e0
    style N fill:#e0f0ff
```

**关键代码路径：**

- 路由：`backend/routes/ingestion.py` → `ingest_logs()` / `ingest_otel_logs()`
- 服务：`backend/services/ingestion.py` → `IngestionService`
- Schema：`backend/schemas/ingestion.py` → `NormalizedLog`, `QueuePayload`

**支持的接入格式：**

| 格式 | 示例字段 | 说明 |
|------|----------|------|
| 原始文本 | `{ "log_data": "2024-01-01 ERROR ..." }` | 自动解析时间戳、级别、消息 |
| 结构化 | `{ "service_id": "payments-api", "level": "ERROR", "message": "..." }` | 推荐方式，便于服务隔离 |
| 批量 | `{ "logs": [ {...}, {...} ] }` | 多条结构化日志 |
| OTel | `{ "resourceLogs": [...] }` | OpenTelemetry HTTP 批量协议 |

**同步响应说明：** 接入 API 立即返回 `success_queued`，**不会等待**向量化完成。`format_ai_response()` 返回的是规则模板（非真实 LLM 调用）。

---

### 3.2 异步索引（Log Processor）

log-processor 从 Redis 阻塞消费，完成 embedding 生成、语义去重聚类、Qdrant 持久化。

```mermaid
sequenceDiagram
    participant R as Redis Queue
    participant W as worker.py
    participant E as SiliconFlow Embedding
    participant C as DuplicateClusteringService
    participant Q as Qdrant

    R->>W: BRPOP log_queue
    activate W
    W->>W: 提取 message / level / service_id
    W->>W: build_semantic_log_text()
    W->>E: embed_texts() → 1024 维向量
    E-->>W: embedding vector

    W->>C: assign_to_cluster(log_text, embedding)
    activate C
    C->>Q: 在 log_clusters 中最近邻搜索

    alt 相似度 ≥ 0.92（重复日志）
        C->>Q: 更新 cluster 计数 / 样本
        C-->>W: is_duplicate = true
        Note over W,Q: 不写入 logs 集合
    else 新日志
        C->>Q: 新建 cluster + upsert log_clusters
        C-->>W: is_duplicate = false
        W->>Q: upsert → logs 集合
    end
    deactivate C
    deactivate W
```

**Qdrant 三集合策略：**

```mermaid
graph LR
    subgraph logs["logs 集合"]
        L1[可搜索的日志向量]
        L2[payload: service_id, level,<br/>message, timestamp, cluster_id]
    end

    subgraph clusters["log_clusters 集合"]
        C1[语义重复聚合]
        C2[representative_log<br/>occurrence_count<br/>sample_logs]
    end

    subgraph incidents["incident_memory 集合"]
        I1[历史 RCA 缓存]
        I2[error → explanation<br/>相似度 ≥ 0.95 命中]
    end

    LP -->|非 duplicate| logs
    LP --> clusters
    InsightEngine[Insight Engine Explain] --> incidents
```

**service_id 解析优先级**（log-processor `_extract_service_id()`）：

1. `service`
2. `service.name`
3. `service_id`
4. 兜底 → `"unknown_service"`

---

### 3.3 语义搜索（Search）

系统存在**三套搜索路径**，HTTP 方法不同，职责有区分：

```mermaid
flowchart LR
    subgraph Client["查询方"]
        U[用户 / 前端 / 外部系统]
    end

    subgraph PathA["路径 A · Backend GET /search"]
        A1[强制 service_id 过滤]
        A2[QdrantVectorStore.semantic_search]
        A3[返回原始向量结果<br/>无 LLM 合成]
    end

    subgraph PathB["路径 B · Backend POST /search"]
        B1[全局搜索<br/>无 service_id 强制]
        B2[LogService.semantic_search]
        B3[llm_chat 生成 answer]
    end

    subgraph PathC["路径 C · Insight Engine GET /search"]
        C1[可选 service_id 过滤]
        C2[SearchService.search]
        C3[结构化 SearchResult 列表]
    end

    U --> PathA
    U --> PathB
    U --> PathC
```

| 路径 | 端点 | 服务级隔离 | LLM 合成 | 典型场景 |
|------|------|------------|----------|----------|
| A | `GET /search?query=...&service_id=...` | ✅ 强制 | ❌ | 微服务内精准语义检索 |
| B | `POST /search` body `{ query }` | ❌ | ✅ | 跨服务探索 + 自然语言回答 |
| C | Insight Engine `GET /search` | ⚪ 可选 | ❌ | 独立 AI 微服务调用 |

**服务级搜索示例**（详见 [service-scoped-vector-search.md](./service-scoped-vector-search.md)）：

```
GET /search?query=database timeout&service_id=payments-api&environment=production&severity=ERROR
```

---

### 3.4 根因解释（Explain / RAG）

Insight Engine 的 Explain 是完整的 **RAG（检索增强生成）** 流水线：

```mermaid
sequenceDiagram
    participant Client
    participant Explain as ExplainService
    participant Cache as IncidentMemoryService
    participant Search as SearchService
    participant Qdrant
    participant GLM as GLM LLM

    Client->>Explain: POST /explain<br/>{ error_message, service_id? }
    activate Explain

    Explain->>Cache: search_similar_incident(error)
    Cache->>Qdrant: incident_memory 向量搜索

    alt 相似度 ≥ 0.95（缓存命中）
        Cache-->>Explain: 历史解释
        Explain-->>Client: ExplainResponse（来自缓存）
    else 缓存未命中
        Explain->>Search: search(error_message)
        Search->>Qdrant: logs 集合 Top-K
        Qdrant-->>Search: context logs
        Search-->>Explain: SearchResult[]

        Explain->>Explain: _build_prompt()<br/>组装上下文 + 错误信息
        Explain->>GLM: llm_chat(system=SRE prompt)
        GLM-->>Explain: 根因解释文本

        Explain->>Cache: store_incident()
        Cache->>Qdrant: 写入 incident_memory
        Explain-->>Client: ExplainResponse
    end
    deactivate Explain
```

**GLM 输出结构（SRE 视角）：**

1. 错误含义的简明解释
2. 基于上下文日志的推测根因
3. 可操作的修复建议

---

### 3.5 安全脱敏（Redaction）

脱敏在**入队之前**完成，确保敏感数据不进入 Redis、Qdrant 或 LLM。

```mermaid
flowchart TD
    Raw[原始日志] --> Rules{DEFAULT_RULES 匹配}

    Rules --> JWT[JWT Token]
    Rules --> AWS[AWS Access Key]
    Rules --> API[API Key / Bearer]
    Rules --> Email[Email 地址]
    Rules --> CC[信用卡号 Luhn 校验]
    Rules --> IP[可选 IPv4 掩码]

    JWT --> Out[脱敏后日志]
    AWS --> Out
    API --> Out
    Email --> Out
    CC --> Out
    IP --> Out

    Out --> Queue[Redis 队列]
    Out --> Metrics[redaction summary / metrics]

    style Raw fill:#ffcccc
    style Out fill:#ccffcc
```

**配置项**（`backend/core/settings.py`）：

- `redact_enabled` — 是否启用（默认 true）
- `redact_patterns` — 规则列表（jwt, api_key, email 等）
- `redact_ipv4` — 是否掩码 IPv4

---

### 3.6 异常检测与告警（部分实现）

```mermaid
stateDiagram-v2
    [*] --> Ingestion: 日志接入
    Ingestion --> Detector: analyze_log()<br/>（已导入，log-processor 未调用）
    Detector --> Scoring: ERROR/CRITICAL/FATAL
    Scoring --> ZScore: calculate_z_score()
    ZScore --> AnomalyEvent: 超阈值
    AnomalyEvent --> AlertManager: 规则匹配 + 通知
    AlertManager --> [*]: /api/alerts/*

    note right of Detector
        Alpha 缺口：
        异常检测 API 存在
        但未接入主 ingestion 流水线
    end note
```

---

## 4. 数据模型

### 4.1 实体关系

```mermaid
erDiagram
    NormalizedLog ||--o{ QueuePayload : "入队"
    QueuePayload ||--|| RedisJob : "BRPOP 消费"
    RedisJob ||--o| LogPoint : "向量化后写入"
    RedisJob ||--o| LogCluster : "聚类关联"

    LogPoint {
        uuid id
        vector embedding_1024
        string service_id
        string level
        string message
        datetime timestamp
        string cluster_id
        bool is_cluster
        json metadata
    }

    LogCluster {
        uuid cluster_id
        string representative_log
        int occurrence_count
        datetime first_seen
        datetime last_seen
        array sample_logs
        float similarity_score_average
        string service_name
    }

    IncidentMemory {
        uuid id
        vector embedding
        string error_message
        string explanation
        datetime created_at
    }

    AnomalyEvent {
        string service_id
        string level
        string message
        float anomaly_score
        datetime timestamp
    }

    LogPoint }o--|| LogCluster : "cluster_id"
    IncidentMemory ||--o{ ExplainRequest : "缓存命中"
```

### 4.2 NormalizedLog 标准字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | ISO 8601 | 标准化时间戳 |
| `level` | enum | INFO / WARN / ERROR / DEBUG / CRITICAL / FATAL |
| `service_id` | string | 服务标识（搜索隔离键） |
| `service` | string | 服务名（兼容旧字段） |
| `host` | string | 主机名 |
| `message` | string | 日志正文（已脱敏） |
| `source` | string | 来源标识 |
| `metadata` | object | 扩展元数据 |
| `parser_type` | string | 解析器类型 |
| `raw` | string | 原始文本（可选） |

---

## 5. API 端点地图

### 5.1 Backend 核心 API（`:8000`）

```mermaid
graph TB
    subgraph Ingest["采集"]
        I1[POST /ingest]
        I2[POST /v1/logs OTel]
    end

    subgraph Search["检索"]
        S1[GET /search<br/>服务级语义搜索]
        S2[POST /search<br/>全局搜索 + LLM]
        S3[GET /logs<br/>分页检索]
    end

    subgraph Ops["运维"]
        O1[GET /health]
        O2[GET /dashboard]
        O3[GET /metrics/parser]
        O4[GET /api/ai/status]
    end

    subgraph Ext["扩展模块"]
        E1[/api/parsing/*]
        E2[/api/alerts/*]
        E3[/api/performance/*]
        E4[/api/security/*]
    end
```

| 方法 | 路径 | 处理函数 | 业务用途 |
|------|------|----------|----------|
| POST | `/ingest` | `ingest_logs()` | 原始/结构化/批量日志接入 |
| POST | `/v1/logs` | `ingest_otel_logs()` | OTel HTTP 批量日志 |
| GET | `/search` | `semantic_search()` | **服务级**语义搜索（需 `service_id`） |
| POST | `/search` | `semantic_search()` | 全局语义搜索 + LLM 回答 |
| GET | `/logs` | `get_logs()` | Qdrant 分页日志检索 |
| GET | `/health` | `health_check()` | Redis / Qdrant / LLM 健康 |
| GET | `/dashboard` | `dashboard()` | 内存统计（遗留实现） |

### 5.2 Insight Engine API（`:8001`）

| 方法 | 路径 | 服务 | 业务用途 |
|------|------|------|----------|
| GET | `/search` | `SearchService` | 语义日志搜索 |
| POST | `/explain` | `ExplainService` | RAG 根因分析 |
| GET | `/health` | — | Qdrant + LLM 可达性 |

### 5.3 Frontend 页面

| 路由 | 组件 | 调用的 Backend API |
|------|------|-------------------|
| `/` | Home + LogExplorer | `GET /logs` |
| `/dashboard` | Dashboard | `GET /dashboard` |
| `/docs` | Docs | 静态文档页 |

> **注意：** 前端当前未直接集成 Insight Engine 的 `/explain` 端点。

---

## 6. 部署拓扑

### 6.1 Docker Compose 服务关系

```mermaid
graph TB
    subgraph Compose["docker compose up"]
        Qdrant["qdrant :6333<br/>向量 DB<br/>volume: qdrant_data"]
        Redis["redis :6379<br/>队列<br/>LRU 512MB"]
        InsightEngine["insight-engine :8001<br/>搜索 + Explain"]
        Backend["backend :8000<br/>FastAPI 采集"]
        LogProcessor["log-processor<br/>embedding + 去重聚类"]
        Frontend["frontend :5174<br/>React + nginx"]
    end

    InsightEngine -->|depends_on healthy| Qdrant
    Backend --> Redis
    Backend --> Qdrant
    LogProcessor --> Redis
    LogProcessor --> Qdrant
    Frontend --> Backend

    Network["logara_internal bridge 网络"]
    Compose --- Network
```

| 服务 | Compose 包含 | 说明 |
|------|-------------|------|
| qdrant | ✅ | 持久化向量存储 |
| redis | ✅ | 需配置 `REDIS_PASSWORD` |
| insight-engine | ✅ | 语义搜索 + RAG 根因解释，依赖 Qdrant healthy |
| backend | ✅ | FastAPI 采集 + 检索 API |
| log-processor | ✅ | 消费队列，生成 embedding，语义去重聚类 |
| frontend | ✅ | nginx 提供静态文件并代理后端 API |

### 6.2 外部依赖

| 服务 | 用途 | 默认配置 |
|------|------|----------|
| **SiliconFlow** | Embedding API | `BAAI/bge-m3`, 1024 维 |
| **GLM** | LLM 对话 | OpenAI 兼容 API，`glm-5.1` |

---

## 7. 关键配置项

| 环境变量 | 默认值 | 业务影响 |
|----------|--------|----------|
| `redis_queue_name` | `log_queue` | log-processor 消费队列名 |
| `qdrant_collection` | `logs` | 主搜索集合 |
| `qdrant_cluster_collection` | `log_clusters` | 去重聚类集合 |
| `duplicate_similarity_threshold` | `0.92` | 判定重复日志的相似度阈值 |
| `max_cluster_sample_size` | `5` | 每个 cluster 保留的样本数 |
| `enable_duplicate_clustering` | `true` | 是否启用语义聚类 |
| `embedding_dimensions` | `1024` | 须与 Qdrant 集合维度一致 |
| `incident_similarity_threshold` | `0.95` | RCA 缓存命中阈值 |
| `redact_enabled` | `true` | 脱敏开关 |

---

## 8. 端到端业务场景示例

### 场景 A：支付服务超时排查

```mermaid
sequenceDiagram
    participant App as payments-api
    participant BE as Backend
    participant W as Log Processor
    participant Q as Qdrant
    participant AI as Insight Engine
    participant Dev as 开发者

    App->>BE: POST /ingest<br/>{ service_id: payments-api,<br/>level: ERROR,<br/>message: database timeout }
    BE->>BE: 脱敏 + 解析
    BE-->>App: success_queued
    BE->>W: Redis 队列
    W->>Q: embedding + upsert logs

    Dev->>BE: GET /search?query=checkout timeout<br/>&service_id=payments-api
    BE->>Q: 服务级向量搜索
    Q-->>Dev: Top-K 相关日志

    Dev->>AI: POST /explain<br/>{ error_message: database timeout,<br/>service_id: payments-api }
    AI->>Q: 检索上下文 + incident cache
    AI-->>Dev: 根因解释 + 修复建议
```

### 场景 B：重复错误降噪

同一 `"Connection refused to redis:6379"` 错误在 1 分钟内出现 500 次：

1. 第 1 条 → 新建 cluster，写入 `logs` + `log_clusters`
2. 第 2–500 条 → 相似度 ≥ 0.92，仅更新 cluster 的 `occurrence_count`
3. 搜索时用户看到 1 条代表日志 + cluster 元数据，而非 500 条重复向量

---

## 9. Alpha 阶段已知缺口

| 模块 | 状态 | 说明 |
|------|------|------|
| 异常检测 | ⚠️ 部分 | `analyze_log()` 已实现在 log-processor 中导入但未调用 |
| Dashboard | ⚠️ 遗留 | 使用内存统计，非 Qdrant 实时数据 |
| Frontend × Insight Engine | ⚠️ 未集成 | LogExplorer 未调用 `/explain` |
| Docker Compose | ✅ 已补全 | backend / log-processor / frontend 已纳入 compose（原仅含基础设施） |
| 双搜索路径 | ℹ️ 设计如此 | GET（服务级）与 POST（全局+LLM）职责重叠，调用方需明确选择 |

---

## 10. 设计原则总结

```mermaid
graph TD
    P1[异步解耦<br/>接入同步返回，向量化异步完成]
    P2[服务隔离<br/>GET /search 强制 service_id]
    P3[安全优先<br/>脱敏在入队前完成]
    P4[语义降噪<br/>高相似日志聚类，减少存储]
    P5[RAG 缓存<br/>Incident Memory 避免重复 LLM 调用]

    P1 --> Goal[可扩展 · 可检索 · 可解释]
    P2 --> Goal
    P3 --> Goal
    P4 --> Goal
    P5 --> Goal
```

---

## 附录：文档索引

| 文档 | 路径 | 内容 |
|------|------|------|
| 项目 README | `README.md` | 能力概述、Quick Start、聚类配置 |
| 架构深度解析 | `docs/architecture_deep_dive.md` | 技术组件与数据流 |
| 服务级搜索规范 | `docs/service-scoped-vector-search.md` | service_id 摄入/存储/搜索 |
| 本文档 | `docs/business-logic.md` | 业务逻辑全景（本文） |

---

*最后更新：2026-07-02 · Logara AI Alpha*
