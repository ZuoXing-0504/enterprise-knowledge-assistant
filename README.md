# 企业知识库智能助手

多用户企业知识库 RAG 后端。项目使用 FastAPI、异步
SQLAlchemy、PostgreSQL/pgvector、Redis 和 Celery，核心文档处理与后续检索生成流程
使用原生 Python 实现，不依赖 LangChain。

> 当前进度：七个阶段全部完成。项目已具备认证、多租户知识库、异步文档向量化、同步与
> SSE RAG 问答、限流与重试、用量统计、质量门禁、CI，以及可等待健康状态的一键启动环境。

## 架构

```text
Client / Swagger
       |
       v
FastAPI Router -> Service -> Repository -> PostgreSQL + pgvector
                     |
                     +-> UUID 文件存储
                     |
                     +-> Redis -> Celery Worker
                                      |
                                      +-> 文档解析与清洗
                                      +-> 可配置文本分块
                                      +-> OpenAI 兼容 Embedding API
                                      +-> DocumentChunk 向量入库

Chat Request -> Question Embedding -> pgvector Cosine Search -> Context Budget
                                                        |
                                                        v
                                   OpenAI Compatible Chat Completion
                                                        |
                                                        v
                            Answer + [来源N] + Message + ModelUsage

Redis
  +-> 用户级固定窗口限流
  +-> SHA-256 问题键的 Embedding 缓存

SSE -> metadata -> token... -> done
                         \-> error / replace
```

```text
app/
  api/              # HTTP 路由与依赖注入
  core/             # 配置、日志、异常和中间件
  db/               # SQLAlchemy Base 与异步会话
  infrastructure/   # Redis 等外部客户端
  models/           # ORM 数据模型
  schemas/          # Pydantic 请求与响应模型
  repositories/     # 数据访问层
  services/         # 业务编排、文件存储、文档处理和问答
  rag/              # 解析、分块、Embedding、上下文和聊天客户端
  tasks/            # Celery 异步任务
  main.py           # FastAPI 应用入口
alembic/             # PostgreSQL 数据库迁移
docker/              # PostgreSQL 初始化脚本
tests/               # 单元测试与接口测试
```

HTTP 请求遵循 `API -> Service -> Repository -> Database`。路由不直接访问数据库或模型
服务；文件解析、分块和 Embedding 位于 `rag`，异步编排位于 `tasks`。

## 技术栈

- Python 3.12、FastAPI、Pydantic v2
- SQLAlchemy 2.x async、Alembic、PostgreSQL 16、pgvector
- Redis、Celery
- PyMuPDF、python-docx
- Argon2 密码哈希、JWT Bearer Token
- httpx、OpenAI 兼容 Embedding 与 Chat Completions 接口
- pytest、pytest-cov、Ruff、pre-commit、GitHub Actions、Docker Compose

## 快速启动

1. 创建本地配置：

   ```powershell
   Copy-Item .env.example .env
   ```

2. 至少设置以下变量：

   ```dotenv
   JWT_SECRET_KEY=replace-with-a-random-secret-at-least-32-characters-long
   OPENAI_API_KEY=your-model-provider-key
   OPENAI_BASE_URL=https://api.openai.com/v1
   OPENAI_CHAT_MODEL=your-chat-model
   OPENAI_EMBEDDING_MODEL=text-embedding-3-small
   EMBEDDING_DIMENSION=1536
   ```

   使用其他 OpenAI 兼容服务时，替换 URL、模型名和向量维度。服务返回的向量维度必须
   与数据库迁移中的 `vector(1536)` 一致；修改维度需要新增 Alembic 迁移。

3. 一键启动 API、worker、PostgreSQL 和 Redis：

   ```powershell
   docker compose up -d --build --wait
   ```

   Compose 会等待 PostgreSQL 和 Redis 健康，执行 `alembic upgrade head`，再启动 API
   与 Celery worker，并等待二者通过健康检查。上传文件保存在 Docker 命名卷中。

   查看运行日志：

   ```powershell
   docker compose logs -f api worker
   ```

4. 打开 Swagger：<http://localhost:8000/docs>

5. 检查服务：

   ```powershell
   curl.exe http://localhost:8000/health
   ```

## 本地开发

项目要求 Python 3.12：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m pytest
python -m ruff check app tests
python -m ruff format --check app tests
python -m pre_commit install
python -m pre_commit install --hook-type pre-push
```

`.env.example` 中的数据库主机名 `db` 和 Redis 主机名 `redis` 用于 Compose。若在宿主机
直接运行 API，请将连接地址中的主机名改为 `localhost`。

pre-commit 在提交前执行 Ruff 检查与格式化，在推送前执行完整 pytest。CI 使用 Python
3.12，并启动真实 pgvector/PostgreSQL 与 Redis 服务，检查 Ruff、Alembic 和测试覆盖率。

## 文档处理流程

1. API 校验知识库归属、扩展名、MIME 类型、文件大小和基础文件签名。
2. 文件流式写入临时文件，成功后原子移动，并使用 UUID 作为存储名。
3. 数据库创建状态为 `pending` 的 `Document`，再将任务发送到 Redis。
4. Celery 将状态切换为 `processing`，按格式解析文本并保留页码或段落编号。
5. 文本按 `CHUNK_SIZE` 与 `CHUNK_OVERLAP` 分块。
6. 通过 OpenAI 兼容 `/embeddings` 接口批量生成向量。
7. 在同一事务中替换片段并将文档标记为 `completed`。
8. 失败时标记为 `failed`，保存可理解但不包含密钥的错误信息。

已完成的幂等策略：

- 已完成文档收到重复任务时直接跳过。
- 正在由其他任务处理的文档不会被并发覆盖。
- 同一任务重试时使用事务替换片段，不追加重复向量。
- Embedding 超时、HTTP 429 和 5xx 会由 Celery 进行有限次数指数退避重试。

## RAG 问答流程

1. 同时使用知识库 ID 与当前用户 ID 校验资源归属。
2. 为独立的用户问题生成 Embedding。
3. PostgreSQL 使用 pgvector 余弦距离 `<=>` 检索 Top-K 已完成片段。
4. 丢弃低于 `RAG_MIN_SIMILARITY` 的结果，并按 `RAG_MAX_CONTEXT_CHARS` 控制上下文。
5. 将片段编号为 `[来源1]`、`[来源2]`，保留文档名、页码或段落和摘要。
6. 使用三条独立消息调用模型：系统规则、不可信检索内容、用户问题。
7. 模型只能依据检索内容回答；无片段、相似度不足或没有有效引用时返回
   `根据当前知识库无法确定`。
8. 在同一事务中保存用户消息、助手消息、有效引用、模型名称、Token 和延迟。

知识库文档始终被视为不可信数据。文档中的“忽略系统规则”等文字只会作为引用内容，
不能覆盖系统指令。问题不会被拼接进系统提示词。

## 流式响应

`POST /api/v1/knowledge-bases/{id}/chat/stream` 使用 SSE，事件类型如下：

| 事件 | 说明 |
| --- | --- |
| `metadata` | 返回本次请求的 `request_id` |
| `token` | 助手增量文本 |
| `replace` | 最终引用校验未通过时，用安全的不确定回答替换已显示文本 |
| `done` | 权威最终答案、引用、会话 ID、消息 ID 和用量 |
| `error` | 流式模型调用失败；不会保存不完整助手消息 |

只有收到完整模型流并通过引用校验后，用户消息、助手消息和用量才会在同一事务中提交。
客户端断开或模型中途失败会回滚，不把半截回答标记为成功。

模型超时、HTTP 429 和 5xx 最多按 `MODEL_MAX_RETRIES` 重试，并使用指数退避。流式请求
只有在尚未发送任何 token 时才允许重试，避免客户端看到重复内容。

## 当前接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 应用存活检查 |
| POST | `/api/v1/auth/register` | 用户注册 |
| POST | `/api/v1/auth/login` | 登录并获取 Access Token |
| GET | `/api/v1/users/me` | 获取当前用户 |
| POST | `/api/v1/knowledge-bases` | 创建知识库 |
| GET | `/api/v1/knowledge-bases` | 分页查询自己的知识库 |
| GET | `/api/v1/knowledge-bases/{id}` | 查询自己的知识库 |
| PATCH | `/api/v1/knowledge-bases/{id}` | 修改自己的知识库 |
| DELETE | `/api/v1/knowledge-bases/{id}` | 删除知识库、关联数据和文件 |
| POST | `/api/v1/knowledge-bases/{id}/documents` | 上传文档并创建异步任务 |
| GET | `/api/v1/knowledge-bases/{id}/documents` | 分页查询知识库文档 |
| GET | `/api/v1/documents/{id}` | 查询文档和处理状态 |
| DELETE | `/api/v1/documents/{id}` | 删除文档、片段和文件 |
| POST | `/api/v1/knowledge-bases/{id}/chat` | 基于知识库同步问答 |
| POST | `/api/v1/knowledge-bases/{id}/chat/stream` | 基于知识库 SSE 流式问答 |
| GET | `/api/v1/conversations` | 分页查询自己的会话 |
| GET | `/api/v1/conversations/{id}/messages` | 分页查询会话消息 |
| GET | `/api/v1/usage/summary` | 查询模型 Token、成本和延迟汇总 |

访问其他用户的知识库、文档或会话统一返回 404，避免泄露资源是否存在。

## 接口示例

注册和登录：

```powershell
curl.exe -X POST http://localhost:8000/api/v1/auth/register `
  -H "Content-Type: application/json" `
  -d '{\"email\":\"user@example.com\",\"password\":\"SecurePass123\"}'

curl.exe -X POST http://localhost:8000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{\"email\":\"user@example.com\",\"password\":\"SecurePass123\"}'
```

创建知识库：

```powershell
curl.exe -X POST http://localhost:8000/api/v1/knowledge-bases `
  -H "Authorization: Bearer <access_token>" `
  -H "Content-Type: application/json" `
  -d '{\"name\":\"工程知识库\",\"description\":\"内部工程规范\"}'
```

上传文档：

```powershell
curl.exe -X POST http://localhost:8000/api/v1/knowledge-bases/<kb_id>/documents `
  -H "Authorization: Bearer <access_token>" `
  -F "file=@handbook.pdf;type=application/pdf"
```

查询处理状态：

```powershell
curl.exe http://localhost:8000/api/v1/documents/<document_id> `
  -H "Authorization: Bearer <access_token>"
```

状态依次为 `pending`、`processing`、`completed` 或 `failed`。支持 `.pdf`、`.docx`、
`.txt`、`.md` 和 `.markdown`，默认最大 20 MB。

发起问答：

```powershell
curl.exe -X POST http://localhost:8000/api/v1/knowledge-bases/<kb_id>/chat `
  -H "Authorization: Bearer <access_token>" `
  -H "Content-Type: application/json" `
  -d '{\"question\":\"员工每年有多少天带薪年假？\"}'
```

继续已有会话时传入 `conversation_id`：

```json
{
  "question": "年假如何申请？",
  "conversation_id": "9715bb21-44cb-44a4-8f76-d7a9a794c9d3"
}
```

问答响应包含 `answer`、`sources` 和 `usage`。每个来源给出引用编号、文档名、页码或
段落、片段序号、文本摘要和相似度。

流式问答建议使用不会缓冲 SSE 的客户端：

```powershell
curl.exe -N -X POST http://localhost:8000/api/v1/knowledge-bases/<kb_id>/chat/stream `
  -H "Authorization: Bearer <access_token>" `
  -H "Content-Type: application/json" `
  -d '{\"question\":\"员工每年有多少天带薪年假？\"}'
```

查询当前用户用量：

```powershell
curl.exe http://localhost:8000/api/v1/usage/summary `
  -H "Authorization: Bearer <access_token>"
```

## 配置

所有配置均由环境变量加载，示例位于 `.env.example`。关键文档处理配置：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `UPLOAD_DIR` | `uploads` | 上传文件目录 |
| `MAX_UPLOAD_SIZE_MB` | `20` | 单文件大小上限 |
| `CHUNK_SIZE` | `1000` | 单片段最大字符数 |
| `CHUNK_OVERLAP` | `150` | 相邻片段重叠字符数 |
| `OPENAI_BASE_URL` | OpenAI API | OpenAI 兼容接口根地址 |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding 模型 |
| `EMBEDDING_DIMENSION` | `1536` | 预期向量维度 |
| `EMBEDDING_BATCH_SIZE` | `64` | 单次 Embedding 批量大小 |
| `MODEL_REQUEST_TIMEOUT_SECONDS` | `60` | 模型请求超时 |
| `MODEL_MAX_RETRIES` | `2` | 超时、429 和 5xx 的额外重试次数 |
| `MODEL_RETRY_BASE_SECONDS` | `0.5` | 指数退避基础秒数 |
| `OPENAI_EMBEDDING_SEND_DIMENSIONS` | `false` | 是否发送 `dimensions` 参数 |
| `OPENAI_CHAT_MODEL` | 空 | OpenAI 兼容聊天模型，问答前必须设置 |
| `OPENAI_CHAT_MAX_TOKENS` | `1000` | 单次回答最大 Token 数 |
| `RAG_TOP_K` | `5` | 向量检索候选片段数 |
| `RAG_MIN_SIMILARITY` | `0.2` | 最低余弦相似度 |
| `RAG_MAX_CONTEXT_CHARS` | `12000` | 发送给模型的最大上下文字符数 |
| `CITATION_EXCERPT_CHARS` | `240` | 接口返回的来源摘要长度 |
| `CHAT_RATE_LIMIT_REQUESTS` | `20` | 单个用户在窗口内的聊天请求数 |
| `CHAT_RATE_LIMIT_WINDOW_SECONDS` | `60` | 聊天限流窗口秒数 |
| `EMBEDDING_CACHE_TTL_SECONDS` | `3600` | 问题 Embedding 缓存时间，`0` 为禁用 |
| `MODEL_INPUT_COST_PER_1M_TOKENS` | `0` | 每百万输入 Token 成本 |
| `MODEL_OUTPUT_COST_PER_1M_TOKENS` | `0` | 每百万输出 Token 成本 |

`.env`、上传文件、密码、JWT 和模型密钥不会提交到版本库，也不会写入应用日志。
缓存键只保存模型名与问题文本的 SHA-256，不保存问题明文；缓存值仅为 Embedding。
私有回答不会写入 Redis，也不会在不同用户之间共享。

## 数据库迁移

```powershell
docker compose run --rm api alembic upgrade head
docker compose run --rm api alembic check
```

PostgreSQL 首次初始化会通过 `docker/postgres/init.sql` 启用 `vector` 扩展。当前迁移创建
`users`、`knowledge_bases`、`documents`、`document_chunks`、`conversations`、
`messages` 和 `model_usages`，关联数据使用数据库级 `ON DELETE CASCADE`。

## 测试

```powershell
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=80
python -m ruff check app tests
python -m ruff format --check app tests
python -m pre_commit validate-config .pre-commit-config.yaml
```

或在精确的 Python 3.12 容器环境运行：

```powershell
docker compose exec api python -m pytest --cov=app --cov-report=term-missing
```

测试覆盖健康检查、统一响应、注册登录、非法 Token、知识库 CRUD、分页、跨用户越权、
文件类型与大小校验、路径清理、解析器、文本分块、Embedding 与 Chat 协议、上下文预算、
引用校验、无依据回答、模型重试、SSE 成功与中断、Redis 限流、缓存、消息持久化、
用量成本和任务幂等。CI 强制分支覆盖率不低于 80%。快速测试使用独立 SQLite、内存 Redis
和可控模型替身；Docker 验证真实 PostgreSQL/pgvector、Redis、Celery、Alembic、API 与
worker 健康检查。外部模型密钥不会出现在测试或 CI 中。

## 技术难点

- **多租户隔离**：Repository 查询同时绑定资源 ID 和当前用户 ID，越权访问与资源不存在
  使用相同 404 响应。
- **安全文件处理**：不信任客户端文件名；使用 UUID 存储名、路径边界检查、大小限制、
  MIME 白名单和 PDF/DOCX 基础签名检查。
- **异步一致性**：先持久化文档再投递任务；投递失败会记录 `failed`；worker 使用行锁、
  任务 ID 和事务控制状态流转及重复消费。
- **可追溯分块**：PDF 保留页码，DOCX/TXT/Markdown 保留段落编号，RAG 可直接生成
  `[来源N]` 引用。
- **向量契约**：客户端校验返回数量、顺序和维度，避免错误模型配置悄悄写入不可检索数据。
- **提示注入隔离**：系统规则、检索数据和用户问题使用独立消息；文档明确标记为不可信，
  没有有效 `[来源N]` 的模型答案不会被接受。
- **上下文预算**：先按相似度筛选，再按字符预算截断；返回来源与实际发送给模型的编号一致。
- **原子持久化**：一次成功问答同时保存两条消息、引用和用量；模型失败时不留下半条会话。
- **流式一致性**：`done` 是权威结果；中断不落库，引用失效时通过 `replace` 事件让客户端
  丢弃未通过校验的增量文本。
- **有限重试**：同步请求可重试临时错误；流式请求一旦发出 token 就禁止重试，避免重复文本。
- **隐私缓存**：只缓存问题 Embedding，键使用不可逆摘要，不缓存或跨用户共享私有回答。
- **可配置成本**：兼容接口无法统一推断价格，因此按环境变量配置输入与输出单价，统计接口
  明确返回估算成本而非账单金额。
- **可理解失败**：空文档、编码错误、模型超时、限流和服务异常都转换为稳定状态与安全错误，
  日志不记录密码、Token 或模型密钥。
