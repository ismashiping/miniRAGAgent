# MiniRAG Agent — Project SPEC

**文档类型：** 项目级需求规范（Project SPEC）  
**当前状态：** Draft v2，待确认（默认决策见第 12 章，修订记录见第 13 章）  
**项目版本：** V0.1 起步，目标版本 V1.0  
**项目定位：** 通过小步 TDD 学习 LangChain、LangGraph、RAG 与 AI Agent 工程开发，并用于 AI Agent 工程师面试准备

---

## 0. 文档职责与仓库基线

### 0.1 文档职责

| 文档 | 职责 |
|---|---|
| `docs/SPEC.md`（本文） | 系统要做什么、阶段划分、如何验收、任务与学习文档的强制规则 |
| `docs/ARCHITECTURE.md` | 模块职责、依赖关系、数据流、State 字段的实现细节 |
| `docs/TASKS.md` | 按依赖排列的任务明细与真实进度、测试证据 |
| `docs/DECISIONS.md` | 经过权衡的技术选型、备选方案和选择理由 |
| `docs/learning/<任务编号>-<短名>.md` | 每个任务的实现、原理、测试与面试复盘（第 8 章） |

SPEC 与其他文档冲突时，以 SPEC 为准，并在发现时同步修正。

### 0.2 仓库基线（2026-10-20 实际检查结果）

- 仓库只有 `docs/SPEC.md`；没有源码、测试、`pyproject.toml`、README、`ARCHITECTURE.md`、`TASKS.md`、`DECISIONS.md`。
- Git 处于 `master` 分支，尚无任何提交。
- 所有功能状态均为“尚未实现”。
- 同日在 SPEC 确认设计决策后，新增 `docs/ARCHITECTURE.md` 与 `docs/TASKS.md` 初版。

本节是历史快照，之后的进度以 `TASKS.md` 和测试证据为准。

## 1. 项目目标

### 1.1 系统目标

构建一个小型、可运行、可测试、可观测的 RAG Agent 系统：基于本地知识库回答问题并给出可追溯引用；证据不足时拒答；能按意图选择闲聊、知识问答或计算工具；最终以 HTTP 服务形式部署。

### 1.2 学习目标

开发者完成项目后，必须能够基于本项目的真实代码和测试解释：

1. LangChain 的 ChatModel、Prompt、Messages、Runnable、结构化输出、Document、Retriever、Embeddings、Tool 分别解决什么问题，在本项目哪里使用。
2. LangGraph 的 State、Node、Edge、Conditional Edge、Reducer、循环、并行和 Checkpoint 如何组织一次请求。
3. 模型如何请求调用工具，应用程序如何校验、授权、执行并回传结果。
4. RAG 的切分、Embedding、向量检索、BM25、RRF、重排、证据筛选和引用如何影响结果，并用评估数据说明。
5. 输入校验、工具白名单、拒答、超时、重试和降级如何提高可靠性。
6. Python 类型标注、异常处理、异步编程，以及 FastAPI、Pydantic、pytest、日志、配置、Redis、PostgreSQL、Docker 的必要用法。
7. 每个设计取舍的备选方案、当前局限和优化方向。

完成的标准是开发者能独立阅读、修改、调试、测试和讲解代码，而不是“项目能运行”。

### 1.3 非目标

见 2.2。

## 2. 项目范围

### 2.1 必须实现的能力

- 基于 LangChain 的 ChatModel 调用、Prompt、Messages 与结构化输出。
- 基于 LangGraph 的执行图：State、Node、Edge、条件边、循环、并行、Reducer、Checkpoint。
- Tool Calling：参数 Schema、按意图的工具白名单、工具执行和结果回传。
- 意图路由与回退、有限次数的检索重试与工具循环。
- 文档读取、清洗、切分、Embedding、本地向量索引。
- 向量召回、BM25 召回、RRF 融合与去重、重排、证据筛选。
- 带编号的引用与证据不足拒答。
- 超时、有限重试、召回降级与明确的错误码。
- 日志、`request_id`、节点耗时和 Token 使用量。
- 固定评估集、检索与拒答指标、消融实验、失败案例分析。
- 会话历史、多轮查询改写、基础长期记忆。
- FastAPI、SSE、Redis 问答缓存、PostgreSQL 持久化、Docker Compose。

“必须”指该能力在其所属阶段（2.3）内为强制要求。

### 2.2 明确不做的事情

- 不训练或微调模型；不在本地加载 Embedding 或重排模型，统一调用托管服务。
- 不开发复杂前端；不建设用户、组织、计费系统；不做身份认证。
- 不实现多 Agent 协作，不实现通用的自主任务规划器。
- 不引入 Kubernetes、微服务、分布式任务系统。
- 不实现增量索引（每次全量重建）、幂等键、分布式锁、数据库迁移框架。
- 不提供文档管理 HTTP 接口；入库只通过 CLI。
- 不使用 `langchain.agents.create_agent`、`langgraph.prebuilt` 中的预制 ReAct Agent 作为核心流程：本项目要求显式写出每个节点和边，以便学习和测试。可以在学习文档中作为对比方案讨论。
- 不在核心流程使用 `langchain_community` 的 BM25Retriever、FAISS、Chroma 等现成检索实现（理由见 3.3），可作为可选对比实验。
- 不强制接入 LangSmith 等需要外网的追踪服务。
- 不为展示技术栈引入没有实际用途的依赖；不将未经验证的实验结果写成性能指标；不在缺少证据时生成虚构引用。

新增范围必须先更新 SPEC，说明原因、影响模块和新增测试。

### 2.3 版本与阶段映射

版本是对外交付节点，阶段是学习与开发顺序。每个阶段结束时系统都必须可运行、可测试。

| 版本 | 阶段 | 主题 | 引入的主要框架概念 |
|---|---|---|---|
| V0.1 | S0 | 工程骨架与最小 LangChain + LangGraph 闭环 | ChatModel、ChatPromptTemplate、Messages、`usage_metadata`、StateGraph、Node、Edge、`START`/`END` |
| V0.1 | S1 | 文档入库 | Document、Text Splitter、Embeddings |
| V0.1 | S2 | 混合检索 | BaseRetriever、Runnable 接口 |
| V0.1 | S3 | 有据回答与拒答 | 证据 Prompt、Conditional Edge |
| V0.1 | S4 | 检索评估与消融实验 | — |
| V0.2 | S5 | Agent 编排 | 结构化输出、Tool、`bind_tools`、ToolMessage、工具循环、并行分支、Reducer |
| V1.0 | S6 | 会话与记忆 | Checkpointer、`thread_id`、Store |
| V1.0 | S7 | 服务化与部署 | `astream`、FastAPI、SSE、Redis、Docker Compose |
| 可选 | — | jieba 分词对比、pgvector / FAISS 对比、LLM-as-judge 回答质量评估 | — |
| 未排期 | — | PDF 解析（加入前须更新 SPEC） | — |

LangChain 与 LangGraph 从 S0 开始使用。V0.1 的执行图是线性流程加一条条件边（S3），复杂编排在 S5 引入。

## 3. 技术栈约束

### 3.1 运行环境与基础技术

- Python 解释器：复用现有 Conda 环境 `C:\Users\11091\.conda\envs\medical-agent\python.exe`（Python 3.10）。不得创建新的虚拟环境或更换解释器。
- 目标 Python 版本 3.10：不得使用 3.11+ 才有的语法和标准库（例如 `typing.Self`、`asyncio.TaskGroup`、`ExceptionGroup`、`tomllib`）。
- 数据校验与配置：Pydantic v2、pydantic-settings。
- LLM 框架：`langchain-core`、`langchain-openai`（通过 OpenAI 兼容 API 接入模型与 Embedding）、`langchain-text-splitters`。
- 编排：`langgraph`、`langgraph-checkpoint`。
- Web（S7）：FastAPI、Uvicorn、SSE。
- 持久化（S6/S7）：PostgreSQL；缓存（S7）：Redis。
- 测试：pytest、pytest-asyncio；代码质量：Ruff；类型检查：mypy。
- 容器化（S7）：Docker、Docker Compose。

2026-10-20 在该环境中实测的已安装版本：langchain-core 1.6.12、langgraph 1.2.11、langgraph-checkpoint 4.2.0、langchain-openai 1.6.2、langchain-text-splitters 1.1.2、pydantic 2.13.5、pydantic-settings 2.15.0、fastapi 0.141.1、pytest 9.1.1、pytest-asyncio 1.4.0、numpy 2.2.6、httpx 0.28.1。`pip check` 无冲突。未安装：`langgraph-checkpoint-postgres`、psycopg（v3）。

### 3.2 LangChain 与 LangGraph 使用约定

框架抽象只在它解决明确问题时使用。业务规则（切分规则、RRF、证据筛选、引用校验、拒答、白名单、错误映射）由项目代码实现并直接测试，不藏在框架配置里。

| 抽象 | 本项目用途 | 为什么用 | 首次引入 |
|---|---|---|---|
| `BaseChatModel`（`ChatOpenAI`） | 所有 LLM 调用 | 统一同步/异步/流式/工具调用接口；测试时可替换为 Fake 模型 | S0 |
| `ChatPromptTemplate`、`MessagesPlaceholder` | 组织 System Prompt、问题、证据、历史 | 模板与变量分离，可单测渲染结果 | S0 |
| `SystemMessage` / `HumanMessage` / `AIMessage` / `ToolMessage` | 模型输入输出 | 统一消息格式，承载 `tool_calls` 与 `usage_metadata` | S0 |
| `AIMessage.usage_metadata` | Token 使用量 | 框架统一字段；缺失时 `usage` 为 `null` | S0 |
| `StateGraph`、`START`、`END` | 每次 `ask` 的执行图 | 显式状态与节点，便于测试单个节点和整体流程 | S0 |
| `Document` | 切片的数据载体 | 与 Splitter、Retriever 的输入输出一致 | S1 |
| Text Splitter | 按 Markdown 标题分节 | 复用可靠实现；段落累积规则由项目实现（4.6） | S1 |
| `Embeddings`（`OpenAIEmbeddings`） | 文档与查询向量化 | 统一 `embed_documents` / `embed_query`；测试用 `DeterministicFakeEmbedding` | S1 |
| `BaseRetriever` | 向量召回、BM25 召回 | 统一 `invoke` / `ainvoke`，可作为 Runnable 组合；分数写入 `Document.metadata` | S2 |
| Conditional Edge | 无证据跳过生成、意图分发、重试与工具循环 | 路由逻辑成为可单测的纯函数 | S3 |
| `with_structured_output` | 意图路由 | 返回 Pydantic 对象；解析失败可检测并回退 | S5 |
| `@tool` / `StructuredTool`、`bind_tools` | `calculate`、`save_memory` | 由 Pydantic Schema 生成工具描述并校验参数 | S5 |
| 并行分支 + Reducer（`Annotated`） | 双路召回、`degraded` 合并 | 并发结果合并规则显式、与完成顺序无关 | S5 |
| Checkpointer（`InMemorySaver`，后续 PostgreSQL） | 会话历史 | `thread_id = session_id`，跨请求保存状态 | S6 |
| Store（`InMemoryStore`，后续 PostgreSQL） | 长期记忆 | 跨会话、按 `user_id` 命名空间存取（待确认，见 12 章） | S6 |
| `astream(stream_mode="messages")` | SSE token 流 | 从图中流出模型增量输出 | S7 |

节点所需的外部依赖（模型、Retriever、Reranker、配置）在调用图时注入，不得在节点内部读取全局单例，以便测试替换。默认使用 LangGraph 的 `context_schema` 与 `Runtime[Context]`（2026-10-20 实测可用）；依赖不进入 State，因此不会被写入 Checkpoint。

### 3.3 RAG 技术

- 文档格式：UTF-8 编码的 Markdown 和 TXT；中文为主，允许中英混合。
- 切分：先按 Markdown 标题分节，再按段落累积到目标长度（规则见 4.6）。
- Embedding：托管服务，通过 `Embeddings` 接口封装，模型可配置。
- 向量检索：本地向量矩阵（numpy，持久化为 `.npy`），自行实现余弦相似度与 Top-K。理由：语料规模小，自己实现能理解相似度计算；FAISS/Chroma 作为可选对比。
- 关键词检索：自行实现 BM25，分词为“中文字符二元组 + 英文/数字词元”，不引入分词库。理由：`langchain_community` 的 BM25Retriever 依赖未安装的 `rank-bm25`，且自行实现能直接测试分词与打分。
- 融合：Reciprocal Rank Fusion（RRF），自行实现。
- 重排：托管重排服务（例如 bge-reranker 系列的 rerank 接口），通过项目定义的接口封装。
- 评估：自行实现检索指标与拒答指标。

### 3.4 依赖管理

- 使用 `pyproject.toml` 声明项目依赖、兼容范围和工具配置（Ruff、mypy、pytest）。当前没有锁文件，也不引入新的依赖管理工具。
- 依赖范围以 3.1 中实测版本为下限、下一个主版本为上限（例如 `langgraph>=1.2,<2`）。
- 安装或升级任何包之前，必须先说明：缺少什么、为什么需要、建议版本范围、兼容性影响，并获得确认。
- 安装命令必须显式使用指定解释器，例如 `& "C:\Users\11091\.conda\envs\medical-agent\python.exe" -m pip install "<包名>==<版本>"`。不得批量升级或降级。
- 项目代码采用 `src/` 布局。默认不把项目安装进共享环境：pytest 通过 `pythonpath` 配置找到源码，CLI 通过 `python -m minirag` 运行（待确认，见 12 章）。
- 已知后续需求：S6/S7 接入 PostgreSQL 需要 `langgraph-checkpoint-postgres` 及 psycopg v3，届时单独申请安装。

### 3.5 存储职责

| 数据 | V0.1 – V0.2 | V1.0 |
|---|---|---|
| 文档、切片文本与元数据 | 本地 JSONL 文件 | 同左 |
| 向量矩阵 | 本地 `.npy` 文件 | 同左 |
| 索引清单（`index_id`、配置） | 本地 JSON 文件 | 同左 |
| BM25 索引 | 加载切片后在内存中构建 | 同左 |
| Checkpoint 与会话历史 | 不持久化 | S6 先用 `InMemorySaver`，S6 末改为 PostgreSQL |
| 长期记忆 | 无 | S6 先用内存实现，S6 末改为 PostgreSQL |
| 问答缓存 | 无 | Redis |
| 评估数据集与报告 | `eval/` 目录 | 同左 |

规则：

- 入库全量重建：先写入临时目录，全部成功后整体替换旧索引；中途失败时旧索引保持可用。
- 每次构建生成 `index_id`，由构建时间与切分、Embedding 配置的哈希组成，写入索引清单。
- 问答缓存只用于 `knowledge` 意图且没有会话历史的请求。缓存键由规范化问题、`index_id` 和检索配置哈希组成，TTL 默认 1 小时。
- Redis 不可用时跳过缓存继续回答。

## 4. 功能需求

### 4.1 LLM 与 Prompt

- 模型通过工厂函数创建，返回 `BaseChatModel`；模型名、`base_url`、API Key、超时、重试次数来自配置。
- System Prompt 使用 `ChatPromptTemplate` 定义，渲染结果必须可单测。
- 上下文历史有限长度管理（S6）。
- 需要程序解析的结果（意图路由）使用 Pydantic 结构化输出；知识问答回答使用带 `[n]` 编号的纯文本，以便流式输出（4.10）。
- 不得假设模型始终输出正确格式；必须处理调用失败、超时和格式错误。
- 每次模型调用记录模型名、耗时和 Token 使用量（来自 `usage_metadata`，缺失时为 `null`，不得用 0 代替）。

### 4.2 Tool Calling（S5）

系统必须区分并可分别测试以下步骤：

1. 模型在 `AIMessage.tool_calls` 中提出工具调用请求。
2. 应用程序按工具 Schema 解析并校验参数。
3. 应用程序检查当前意图的工具白名单。
4. 应用程序执行工具。
5. 结果以 `ToolMessage`（携带对应 `tool_call_id`）回传模型。
6. 模型根据结果生成后续输出。

工具执行节点由项目自行实现，不使用预制 ToolNode（理由：白名单与错误回传规则需要显式可测；ToolNode 可在学习文档中对比）。

按意图的静态白名单，不按用户区分：

- `chat`：只允许 `save_memory`（S6 起，且请求带有 `user_id`）。
- `knowledge`：不向模型绑定任何工具；检索由流程直接执行。
- `calculate`：只允许 `calculate`。

模型请求白名单之外的工具时不执行，记录日志，并以 `ToolMessage` 回传“工具不可用”。工具调用循环最多 3 轮，达到上限后停止调用工具并让模型给出最终回答。

`calculate` 工具约束：

- 只接受算术表达式字符串，通过 AST 白名单求值，不使用 `eval`。
- 允许：数字字面量、`+ - * / // % **`、一元正负号、括号。
- 不允许：名称、属性访问、函数调用、下标及其他语法。
- 表达式长度上限 200 字符；`**` 的指数绝对值上限 100。
- 除零、非法表达式和超限返回结构化工具错误，不中断整个请求。

### 4.3 意图路由（S5）

意图：`chat`（简单对话）、`knowledge`（知识库问答）、`calculate`（计算）。

- 路由节点使用 `with_structured_output` 返回 `RouteDecision(intent)`。
- 回退：结构化输出解析失败、调用异常或意图不在枚举内时，路由到 `knowledge`，路由来源为 `fallback`；否则为 `model`。`knowledge` 在证据不足时拒答，避免把知识型问题交给不受证据约束的闲聊路径。
- 每次路由记录 `intent` 与路由来源。

S5 之前的临时行为（属于阶段内行为，不是最终契约）：

- S0 – S2：`ask` 只走 `chat` 路径，`intent=chat`。
- S3 起：`ask` 只走 `knowledge` 路径，`intent=knowledge`；`chat` 节点保留并通过节点单测覆盖，在 S5 重新接入。

### 4.4 LangGraph 执行图

每个阶段的图拓扑（节点名为建议名称，最终以 ARCHITECTURE 为准）：

| 阶段 | 拓扑 |
|---|---|
| S0 | `START → respond_chat → END` |
| S2 | 在 S0 基础上加入独立可测的检索节点（`recall_vector`、`recall_bm25`、`fuse`、`rerank`、`filter_evidence`），暂不接入 `ask` 主流程 |
| S3 | `START → recall_vector → recall_bm25 → fuse → rerank → filter_evidence →（条件边）generate_answer / refuse → END` |
| S5 | `START → route →（条件边）chat / knowledge / calculate`；`knowledge` 中两路召回并行；`calculate` 中 `call_model ⇄ execute_tools` 循环；检索不足时最多改写重试 1 次 |
| S6 | 增加 Checkpointer、历史载入/写回、查询改写 |

要求：

- 每个节点具有明确的输入字段、输出字段和职责，能脱离整图单独测试。
- 条件边的路由函数是纯函数，必须单独测试每个分支。
- 循环必须有显式计数字段和上限，并有测试验证上限生效。
- 并行分支写入的字段必须有 Reducer，并测试合并结果与完成顺序无关。
- 不得把全部逻辑堆积在单个节点或 API 路由函数中。

### 4.5 State、Checkpoint 与 Memory

#### 4.5.1 State 字段与更新规则

以下是契约级字段；类型细节与内部字段在 ARCHITECTURE 中定义。

| 字段 | 含义 | 引入阶段 | 更新规则 |
|---|---|---|---|
| `request_id` | 请求标识 | S0 | 入口写入，只读 |
| `question` | 规范化后的原始问题 | S0 | 入口写入，只读 |
| `answer` | 最终回答文本 | S0 | 覆盖 |
| `status`、`error` | 结果状态与错误 | S0 | 覆盖 |
| `usage_records` | 每次模型调用的用量 | S0 | 追加 |
| `top_k` | 检索数量 | S2 | 入口写入，只读 |
| `retrieval_query` | 当前用于检索的问题 | S2 | 覆盖（改写或重试时更新） |
| `recall_results` | 按来源（`vector` / `bm25`）分组的召回结果 | S2 | 按来源键合并，同一键覆盖 |
| `fused`、`ranked`、`evidence` | 融合、重排、筛选后的切片 | S2 | 覆盖 |
| `degraded` | 降级组件名 | S2 | 并集去重，按名称排序 |
| `citations` | 有效引用 | S3 | 覆盖 |
| `intent`、`route_source` | 路由结果 | S5 | 覆盖 |
| `messages` | 本次请求内的模型/工具消息 | S5 | `add_messages` |
| `tool_rounds`、`retrieval_attempts` | 循环计数 | S5 | 覆盖 |
| `node_timings` | 节点耗时 | S5 | 追加 |
| `history` | 已完成的历史回合 | S6 | 只在回合正常结束时追加 |

规则：

- 并行节点写入的字段（`recall_results`、`degraded`、`node_timings`、`usage_records`）必须使用 Reducer，不得依赖执行顺序。
- 启用 Checkpoint 后，除 `history` 外的请求级字段在每次新调用开始时必须重置，不得把上一轮的 `usage_records`、`messages`、`degraded` 等带入下一轮。必须有测试验证。
- 2026-10-20 实测：同一 `thread_id` 下，对使用 `operator.add` 的字段传入 `[]` 不会清空旧值（结果累积），传入 `langgraph.types.Overwrite([])` 才会重置。重置方式在 S6-01 中实现并测试。

#### 4.5.2 Checkpoint、短期记忆与长期记忆

概念区分：图执行状态是一次执行所需的数据；Checkpoint 保存图状态，本项目用它持久化会话历史；短期记忆是当前会话的对话历史；长期记忆是跨会话保留的、经过筛选的用户信息。

身份与会话：

- `session_id` 标识会话，同时作为 Checkpoint 的 `thread_id`。
- `user_id` 是调用方提供的不透明字符串。系统不做身份认证，`user_id` 不是安全边界；README 必须说明。

短期记忆（S6）：

- 历史由 Checkpointer 保存；S6 末切换到 PostgreSQL 后，服务重启后同一 `session_id` 的历史仍然可用。
- 构造 Prompt 时只使用最近 10 轮，可配置。
- 只有正常完成的回合写入历史；出错或被取消的回合不写入。
- `knowledge` 意图在检索前，若存在历史，先把问题改写为独立问题再检索。原始问题与改写结果都写入日志。

长期记忆（S6）：

- 只在请求带有 `user_id` 时启用。
- 只通过 `save_memory` 工具写入：用户明确要求记住某件事，或明确陈述个人偏好时。不保存知识库内容、模型回答和一次性问题。
- 每条记录包含 `memory_id`、`user_id`、`content`（不超过 200 字符）、`created_at`。
- 每个用户最多 20 条，超出时删除最早的记录。
- 读取时把该用户的全部记忆注入 System Prompt。
- 提供 CLI 按 `user_id` 列出与清空记忆，清空后不得再被读取。

### 4.6 RAG

环节：文档读取 → 清洗 → 切分 → 元数据 → Embedding → 向量索引 → BM25 索引 → 双路召回 → RRF 融合与去重 → 重排 → 证据筛选 → 基于证据生成 → 引用校验 → 记录检索结果。

读取与清洗：

- 递归读取知识库目录下的 `.md`、`.txt`；其他扩展名跳过并计入 `IngestReport`。
- 非 UTF-8 文件跳过并在报告中列出，不中断整次入库。
- 清洗：统一换行符为 `\n`，去除首尾空白，合并 3 个及以上连续空行为 1 个空行；不改写正文内容。

切分：

- 先按 Markdown 标题（`#` 至 `###`）分节，记录标题路径；TXT 整体视为一个无标题节。
- 节内按空行分段，顺序累积段落直到加入下一段会超过 `chunk_size`（默认 300 字符，可配置）。
- 单个段落超过 `chunk_size` 时按 `chunk_size` 硬切分。
- 切片之间不重叠（V0.1 默认；是否引入重叠由消融实验决定后再更新 SPEC）。
- 空节、只含空白的切片不产生。

标识与元数据：

- `doc_id`：相对知识库根目录的路径，统一用 `/` 分隔，例如 `guide/install.md`。
- `chunk_id`：`{doc_id}#{序号}`，序号从 0 开始，按文档内顺序编号。
- 切片以 `Document` 表示，`metadata` 至少包含 `chunk_id`、`doc_id`、`heading`（标题路径，可空）。
- 切分配置变化后 `chunk_id` 可能变化，评估集因此不依赖 `chunk_id`（4.8）。

检索与分数：

- 向量分数为余弦相似度；BM25 分数为 BM25 原始分；RRF 分数为 `Σ 1/(k + rank)`，`k` 默认 60，`rank` 从 1 开始；重排分数为重排服务返回值。四种分数分别保存，不得混为一种。
- 两路各召回 `max(top_k * 2, 10)` 条（可配置），RRF 后按 `chunk_id` 去重，再取前若干条送入重排。
- RRF 分数相同时按 `chunk_id` 字典序排序，保证结果确定。
- 知识库为空、检索无结果或证据不足时，按 4.10 的证据规则处理。

### 4.7 Guardrails 与异常处理

Guardrails 指项目自行实现的校验规则，不引入同名第三方库：输入长度与格式校验、按意图的工具白名单（4.2）、引用校验（4.10）、路由结果的 Schema 校验（4.3）。

异常处理原则：

- 节点抛出项目定义的领域异常，或在可降级时写入 `degraded`；入口层把已知异常映射为错误码，未知异常映射为 `internal_error`，堆栈只写日志，不进入响应。
- 不得捕获全部异常后返回成功。

需覆盖的故障：非法参数与输入过长；模型超时或不可用；结构化输出解析失败；工具参数错误与执行失败；检索失败与重排失败；PostgreSQL 或 Redis 异常；SSE 连接中断。

重试规则：

- 模型与 Embedding 使用 SDK 自带的超时与重试（`timeout` 可配置，`max_retries=2`）。
- 重排调用的重试方式（HTTP 客户端机制或 `Runnable.with_retry`）在 S2 任务中决定并记录到 DECISIONS，上限同样为 2 次。
- 不自行实现通用重试框架。
- 流式输出已向客户端发送任何内容后，不再重试该次生成。

降级规则：

| 故障 | 行为 | 引入阶段 |
|---|---|---|
| 重排失败 | 使用 RRF 顺序，不做阈值筛选，`degraded` 包含 `rerank` | S2 |
| 向量召回失败 | 只使用 BM25 结果，`degraded` 包含 `vector_retrieval` | S5 |
| BM25 召回失败 | 只使用向量结果，`degraded` 包含 `bm25_retrieval` | S5 |
| 两路召回都失败 | `status=error`，`code=retrieval_failed` | S5（S3 中任一路失败即为此结果） |
| Redis 不可用 | 跳过缓存，`degraded` 包含 `cache` | S7 |
| PostgreSQL 不可用 | `status=error`，`code=service_unavailable` | S6 |
| 模型调用重试耗尽 | `status=error`，`code=llm_unavailable` | S0 |

工具参数错误和执行失败作为工具结果回传模型，不使整个请求失败。异常响应不得泄露密钥、数据库凭据、内部堆栈。

### 4.8 Evaluation 与 Observability

评估数据集：

- 语料存放于 `data/corpus/`，必须可以公开提交。
- 数据集存放于 `eval/datasets/`，JSONL 格式，文件名包含版本号。
- 每条记录包含 `question_id`、`question`、`expected_intent`、`evidence_texts`（证据原文片段；无答案题为空列表）。
- 切片包含任一证据原文片段即视为相关切片。
- 至少 30 题，其中至少 5 题在知识库中没有答案。

必须报告的指标：

- 检索：Recall@K、MRR、Hit Rate@K，K 取 1、3、5、10；主指标为 Recall@5 与 MRR。
- 拒答：无答案题的正确拒答率，有答案题的错误拒答率。
- 引用：回答中有效引用的比例。

消融实验（同一数据集）：

1. 仅向量召回。
2. 仅 BM25 召回。
3. 双路召回 + RRF。
4. 双路召回 + RRF + 重排。
5. 在配置 4 下比较两种切分长度（300 与 500 字符）。

失败案例分析：选取至少 10 道答错或检索失败的题，按切分问题、召回失败、排序问题、生成问题分类，写出每类的改进方向。

评估报告存放于 `eval/reports/`，记录模型、检索配置、`index_id`、数据集版本和测试时间。

运行时观测：

- 使用标准 `logging`；每条请求相关日志带 `request_id`（S0）。
- 记录召回的 `chunk_id`、降级组件（S2/S3）。
- 记录 `intent`、路由来源、各节点耗时、每次模型调用的 Token 使用量（S5）。
- 任何日志中不得出现配置的 API Key 或其他密钥。

没有实际测量的数据不得写成实验结果；自动评估分数不得等同于真实业务正确率。

### 4.9 API、SSE 与部署（S7）

- `GET /health`：存活检查。
- `POST /v1/ask`：同步问答，使用 4.10 契约。
- `POST /v1/ask/stream`：SSE 流式问答。
- 请求校验错误返回 `invalid_request`。
- Docker Compose：应用、PostgreSQL、Redis。

SSE 事件：

| 事件 | 数据 |
|---|---|
| `token` | 增量文本 |
| `final` | 完整的 `AskResponse` |
| `error` | `code` 与 `message` |

- 每个流以且仅以一个 `final` 或 `error` 事件结束，随后关闭连接。
- 最终结果以 `final` 为准：引用校验判定证据不足时，`final.answer` 为固定拒答文本（即使已流出的 token 与之不同）。
- 客户端断开时取消后续模型调用，本轮不写入会话历史。

### 4.10 统一入口与问答契约

所有阶段共用同一组 Pydantic 请求与响应 Schema。HTTP 接口只是传输层，不另行定义字段。

入口（默认决策，见 12 章）：

- S0：`aask(request) -> AskResponse`（异步，执行 LangGraph 图）与同步包装 `ask(request) -> AskResponse`。
- S0 末：CLI `python -m minirag ask "<问题>"`。
- S1：`ingest(path) -> IngestReport` 与 `python -m minirag ingest <path>`。
- S4：`python -m minirag eval <数据集>`。
- S6：`python -m minirag memory list|clear --user <user_id>`。
- S7：HTTP 接口调用同一组函数。

`AskRequest`：

- `question`：去除首尾空白后长度 1 到 2000 字符。
- `session_id`：可选；缺省时由系统生成并在响应中返回。
- `user_id`：可选，含义见 4.5.2。
- `top_k`：可选，默认 5，范围 1 到 20。

`AskResponse`：

- `request_id`、`session_id`。
- `status`：`answered`、`insufficient_evidence` 或 `error`。
- `intent`：`chat`、`knowledge` 或 `calculate`；请求校验失败时为 `null`。
- `answer`：回答文本；`status=error` 时为面向用户的简短说明。
- `citations`：`Citation` 列表；非 `knowledge` 意图时为空列表。
- `degraded`：降级组件名列表，按名称排序；无降级时为空列表。
- `error`：仅在 `status=error` 时存在，包含 `code` 与面向用户的 `message`；其他状态下必须为 `null`。
- `usage`：本次请求所有模型调用的汇总（模型名称、输入 Token、输出 Token）；任一调用无法获取用量时为 `null`，不得用 0 代替。
- `latency_ms`：入口测量的端到端耗时。

`Citation`：`marker`（回答中的引用编号）、`chunk_id`、`doc_id`、`heading`（可空）、`snippet`，以及分别记录的 `vector_score`、`bm25_score`、`rrf_score`、`rerank_score`；未参与计算的分数为 `null`。

`IngestReport`：`index_id`、文档数、切片数、跳过的文件及原因、耗时。

错误码：`invalid_request`、`retrieval_failed`、`llm_unavailable`、`service_unavailable`、`internal_error`。新增错误码必须更新本节。

`knowledge` 意图的证据规则：

1. 只依据本次检索到的切片回答，不使用模型自身知识补充事实。
2. 证据筛选：重排分数低于阈值的切片被丢弃；阈值可配置，默认值在 S4 评估集上标定，标定前使用配置中的临时值。重排降级时不做阈值筛选。
3. 证据按 `[1]`、`[2]` 编号放入 Prompt；模型用相同编号标注引用；证据不足时输出固定拒答文本。
4. 编号超出范围的引用标记一律丢弃并记录日志。
5. 以下任一情况返回 `status=insufficient_evidence`、固定拒答文本、`citations` 为空：知识库为空；没有切片通过筛选（此时不调用生成模型）；模型输出拒答文本；丢弃无效标记后没有任何有效引用。

## 5. 代码书写规范

### 5.1 命名

- 模块、函数、变量用 `snake_case`；类用 `PascalCase`；常量用 `UPPER_SNAKE_CASE`。
- 名称表达真实业务含义；避免无意义缩写和含糊的通用名称；布尔变量使用明确语义。

### 5.2 类型标注

- 公开函数、关键接口和数据结构必须标注类型；复杂数据优先使用 Pydantic 模型或 `TypedDict`。
- 避免无必要的 `Any`；不得用大量类型忽略注释掩盖真实错误。
- 语法必须兼容 Python 3.10。

### 5.3 函数与类

- 函数职责单一；避免超长函数、深层嵌套和重复逻辑。
- 类只在需要管理状态、封装行为或建立稳定抽象时使用；不为形式上的面向对象或设计模式而强行引入类。

### 5.4 模块与依赖

- 按业务职责组织模块；避免循环导入和不必要的全局可变状态。
- 业务逻辑、模型调用、存储访问和 HTTP 处理分离。
- 外部依赖通过清晰接口封装，并通过参数注入，便于测试替换。

### 5.5 异常与日志

- 只捕获能够明确处理的异常；不得使用空 `except`，不得 `except Exception: return None`。
- 转换异常时保留上下文（`raise ... from ...`）。
- 使用标准 `logging`；日志事件含义明确并带关联 ID；不得记录密钥、令牌、密码。
- 面向客户端的错误信息安全、明确、稳定。

### 5.6 配置与密钥

- 使用环境变量与 pydantic-settings 管理配置；提供 `.env.example`，只含占位值。
- `.env` 和真实密钥不得提交；密钥字段使用 `SecretStr`。
- 缺少关键配置时给出明确错误提示。

### 5.7 格式与静态检查

- Ruff 统一负责格式和基础静态检查；mypy 检查 `src/`；规则统一配置在 `pyproject.toml`。
- 新增代码不得引入新的 Ruff 或 mypy 错误。

### 5.8 注释与文档

- 优先用命名和结构表达意图；注释解释设计原因和特殊约束，不逐行复述代码。
- 复杂算法、状态转换和非直观行为需要必要说明；注释必须与实际行为一致。

### 5.9 设计原则

- 优先简单、直接、容易验证的实现；不提前实现没有需求的扩展。
- 不为抽象而抽象，不重复实现已有的可靠基础设施，不机械包装框架。
- 不做未经解释的大规模重构；修改公共接口时同步更新调用方和测试。
- 不在未验证的情况下声称功能完成。

## 6. TDD 与测试要求

### 6.1 标准流程

每个开发任务必须按以下顺序执行，并在 `TASKS.md` 和学习文档中记录：

1. 确认本任务在 SPEC 中的需求与验收场景。
2. 阅读现有实现与调用链。
3. 编写或补充测试。
4. 运行测试，确认失败（红灯），并记录失败输出摘要。
5. 实现满足测试的最小代码。
6. 运行目标测试（绿灯）。
7. 运行全部默认测试、Ruff 与 mypy（回归）。
8. 必要时小范围重构并再次运行测试。
9. 记录实际结果和未验证的行为。

红灯规则：

- 红灯必须因目标行为缺失而失败。新模块的第一个测试可以因 `ImportError` 失败；同一模块的后续测试应因断言失败，而不是测试代码本身的语法或拼写错误。
- 不得为了通过测试而削弱断言或修改验收标准。发现验收标准本身有问题时，先停下来更新 SPEC。

### 6.2 测试分层

- 单元测试：纯函数、Schema、分词、BM25、RRF、指标、路由函数、Reducer、单个节点、错误映射。
- 图测试：用测试替身驱动整张 LangGraph 图，验证节点顺序、条件分支、循环上限、并行合并和状态变化。
- 集成测试：真实本地服务（PostgreSQL、Redis）。
- API 测试：FastAPI TestClient 验证请求校验、响应格式、错误码与 SSE 事件。
- 真实服务测试：真实模型、Embedding、重排服务。

### 6.3 测试替身

- 默认测试必须离线运行，不访问网络，不需要 API Key。
- 普通文本回复使用 `langchain_core` 提供的 `GenericFakeChatModel` 或 `FakeMessagesListChatModel`。
- Embedding 使用 `DeterministicFakeEmbedding` 或项目内可控向量的 Fake。
- 2026-10-20 实测：`FakeMessagesListChatModel.bind_tools()` 抛出 `NotImplementedError`。因此 S5 的路由与工具调用测试需要项目自定义的测试替身（`tests/` 中维护），具体实现在对应任务中确定并验证。
- 重排、检索的失败场景使用会抛出指定异常的 Fake，验证降级行为。

### 6.4 测试标记与命令

- `live`：需要真实模型、Embedding 或重排服务。
- `integration`：需要本地 PostgreSQL 或 Redis。
- 默认运行排除以上两类（在 `pyproject.toml` 中配置）。

命令（PowerShell）：

```powershell
$py = "C:\Users\11091\.conda\envs\medical-agent\python.exe"
& $py -m pytest                      # 默认离线测试
& $py -m pytest -m live              # 真实服务测试（需要配置密钥）
& $py -m pytest -m integration       # 本地服务集成测试
& $py -m ruff check .
& $py -m ruff format --check .
& $py -m mypy src
```

网络不可用、密钥缺失或服务未启动造成的阻塞必须如实记录，不得写成“通过”。

### 6.5 验收规则

只有满足当前任务全部验收条件、并有实际测试输出作为依据时，任务才可以进入 `review` 状态（8.2）。代码能生成、程序能启动或单个测试通过，都不等于功能正确。

## 7. 阶段路线与验收场景

验收场景编号格式为 `A-<阶段>-<序号>`，`TASKS.md` 中每个任务必须引用其覆盖的场景编号。除标记【真实服务】或【人工】的场景外，都必须能用测试替身自动运行。

任务清单为初始拆分，详细字段（第 8 章）在 `TASKS.md` 中维护；拆分调整需同步更新本章。

### S0 工程骨架与最小 LangChain + LangGraph 闭环（V0.1）

目标：一个问题经过 Pydantic 校验、LangGraph 单节点图和 LangChain ChatModel，返回符合契约的 `AskResponse`，全部可离线测试。

| 任务 | 学习目标 |
|---|---|
| S0-01 | `pyproject.toml`、`src/` 布局、pytest/Ruff/mypy 配置、测试标记、`.gitignore`；跑通一个冒烟测试 |
| S0-02 | 用 Pydantic 定义 `AskRequest`、`AskResponse`、`Citation`、错误与用量模型，测试字段校验与状态一致性 |
| S0-03 | 用 pydantic-settings 管理配置，`SecretStr` 保护密钥，缺少配置时明确报错 |
| S0-04 | ChatModel 工厂与 Chat Prompt：`ChatOpenAI` 的超时与重试配置、`ChatPromptTemplate` 渲染、`usage_metadata` 转换 |
| S0-05 | LangGraph 最小图：State、`respond_chat` 节点、`START`/`END`、依赖注入；用 Fake 模型测试状态变化 |
| S0-06 | `aask` / `ask` 入口：生成 `request_id` 与 `session_id`、组装响应、测量耗时、带 `request_id` 的日志 |
| S0-07 | 错误映射：校验失败 → `invalid_request`，模型异常 → `llm_unavailable`，未知异常 → `internal_error`，响应不含堆栈 |
| S0-08 | CLI `python -m minirag ask` |

验收场景：

- A-S0-1：使用 Fake 模型调用 `ask`，返回 `status=answered`、`intent=chat`、非空 `request_id` 与 `session_id`，`answer` 等于 Fake 模型输出。
- A-S0-2：`question` 为空白或超过 2000 字符、`top_k` 越界时，返回 `status=error`、`code=invalid_request`，且不调用模型。
- A-S0-3：模型抛出超时或连接异常时，返回 `code=llm_unavailable`，响应中不含堆栈和密钥。
- A-S0-4：模型返回 `usage_metadata` 时 `usage` 被正确填充；不返回时 `usage` 为 `null`。
- A-S0-5：图节点可以脱离 `ask` 单独调用并验证其输入输出字段。
- A-S0-6：默认测试、`ruff check`、`ruff format --check`、`mypy src` 全部通过。
- A-S0-7【真实服务】：配置真实模型后，`python -m minirag ask "你好"` 返回回答，日志中不出现 API Key。

### S1 文档入库（V0.1）

| 任务 | 学习目标 |
|---|---|
| S1-01 | 文档读取与清洗：递归遍历、`doc_id` 规范化、非 UTF-8 与不支持格式的处理 |
| S1-02 | 切分：标题分节、段落累积、超长段落硬切分，输出带元数据的 `Document` |
| S1-03 | Embedding 接口：`OpenAIEmbeddings` 配置与 Fake 替换、批量调用、向量维度检查 |
| S1-04 | 索引持久化：JSONL + `.npy` + 清单、`index_id`、临时目录写入后整体替换 |
| S1-05 | `ingest` 入口、`IngestReport` 与 CLI |

验收场景：

- A-S1-1：切分边界测试：标题路径正确；段落累积不超过 `chunk_size`（硬切分产生的片段除外）；空节不产生切片；`chunk_id` 连续且从 0 开始。
- A-S1-2：重复执行 `ingest` 后切片数量与 `chunk_id` 不变。
- A-S1-3：构建中途失败（例如 Embedding 抛错）时，旧索引仍可加载且内容不变。
- A-S1-4：非 UTF-8 文件与不支持的扩展名被跳过并出现在 `IngestReport` 中。

### S2 混合检索（V0.1）

| 任务 | 学习目标 |
|---|---|
| S2-01 | 向量召回：余弦相似度、Top-K、实现 `BaseRetriever`，分数写入 `metadata` |
| S2-02 | BM25 分词：中文二元组与英文/数字词元 |
| S2-03 | BM25 打分与召回 Retriever |
| S2-04 | RRF 融合与去重（纯函数） |
| S2-05 | 重排接口、超时与重试方式、失败降级 |
| S2-06 | 证据筛选：阈值与降级时跳过筛选 |
| S2-07 | 检索节点：把 S2-01 至 S2-06 包装为图节点，测试状态字段变化与 `degraded` Reducer |

验收场景：

- A-S2-1：向量召回在构造的向量上返回正确的 Top-K 顺序；空索引返回空列表。
- A-S2-2：分词器对中文、英文、数字和混合文本输出预期词元；BM25 在小语料上的排序与手算结果一致。
- A-S2-3：RRF 对两路结果去重，同一切片保留两路分数；分数相同时按 `chunk_id` 排序；结果确定。
- A-S2-4：重排服务失败时使用 RRF 顺序，`degraded` 包含 `rerank`，且不做阈值筛选。
- A-S2-5：每个切片的四种分数分别保存，未参与计算的为 `null`。

### S3 有据回答与拒答（V0.1）

| 任务 | 学习目标 |
|---|---|
| S3-01 | 证据 Prompt：编号证据块、拒答指令、渲染测试 |
| S3-02 | 引用解析与校验：提取 `[n]`、丢弃越界编号、生成 `Citation` |
| S3-03 | 条件边：无证据走 `refuse`，有证据走 `generate_answer`；拒答判定 |
| S3-04 | 接入 `ask`：knowledge 图端到端，覆盖 V0.1 的问答验收场景 |

验收场景：

- A-S3-1：有答案的问题返回 `answered`，每条引用都对应本次检索结果中的切片。
- A-S3-2：无答案的问题或空知识库返回 `insufficient_evidence`、`citations` 为空；没有切片通过筛选时生成模型调用次数为 0。
- A-S3-3：回答中出现越界编号时该标记被丢弃；丢弃后没有有效引用时返回 `insufficient_evidence`。
- A-S3-4：任一路召回失败时返回 `code=retrieval_failed`（S5 改为单路降级）。
- A-S3-5：S0 的验收测试中仍然有效的部分全部通过；因 `intent` 改为 `knowledge` 而变化的断言须在任务中显式更新并说明。

### S4 检索评估与消融实验（V0.1）

| 任务 | 学习目标 |
|---|---|
| S4-01 | 评估集格式、加载与“相关切片”判定 |
| S4-02 | Recall@K、MRR、Hit Rate@K（纯函数，手算用例） |
| S4-03 | 拒答率与有效引用比例 |
| S4-04 | 消融配置运行器与报告生成，CLI `python -m minirag eval` |
| S4-05【人工】 | 准备可公开的语料与不少于 30 题的数据集 |
| S4-06【真实服务】 | 真实评估、阈值标定、失败案例分析 |

验收场景：

- A-S4-1：指标函数在手算用例上结果正确，包括无相关切片的题。
- A-S4-2：`eval` 使用 Fake 依赖输出 4.8 要求的全部指标与消融对比表，报告包含模型、检索配置、`index_id`、数据集版本和测试时间。
- A-S4-3【真实服务】：真实模型在评估集上完成一次完整评估，阈值默认值按结果更新到配置，并完成失败案例分析。

V0.1 完成条件：A-S0 至 A-S4 全部通过并有证据；生成 `docs/REVIEW-V0.1.md`。

### S5 Agent 编排（V0.2）

| 任务 | 学习目标 |
|---|---|
| S5-01 | 意图路由：`with_structured_output`、解析失败检测与回退、自定义测试替身 |
| S5-02 | 条件边按意图分发，重新接入 `chat` 节点 |
| S5-03 | `calculate`：AST 白名单求值（纯函数）与 Tool Schema |
| S5-04 | 工具调用循环：`bind_tools`、自写工具执行节点、白名单、`ToolMessage`、3 轮上限 |
| S5-05 | 并行双路召回与 Reducer |
| S5-06 | 单路召回失败降级 |
| S5-07 | 检索重试循环：改写查询，最多 1 次 |
| S5-08 | 节点耗时与 Token 记录，日志密钥检查 |

验收场景：

- A-S5-1：“帮我算 (3+4)*5” 被路由到 `calculate`，模型调用计算工具，回答包含 35。
- A-S5-2：计算工具拒绝 `__import__('os')` 等包含名称或函数调用的表达式，返回工具错误，请求不失败。
- A-S5-3：模型请求白名单之外的工具时不执行，回传“工具不可用”；工具循环达到 3 轮后停止。
- A-S5-4：路由结构化输出解析失败时回退到 `knowledge`，路由来源为 `fallback`。
- A-S5-5：两路召回都执行，合并结果与两路完成的先后顺序无关（用不同延迟的 Fake 验证）。
- A-S5-6：向量召回失败时返回 BM25 结果，`degraded` 包含 `vector_retrieval`；两路都失败时返回 `retrieval_failed`。
- A-S5-7：首次检索没有切片通过筛选时，改写查询后最多重新检索 1 次。
- A-S5-8：日志记录 `request_id`、`intent`、路由来源、各节点耗时与 Token；任何日志中不出现配置的 API Key。
- A-S5-9：V0.1 的验收测试全部通过（因路由引入而需要的测试调整须逐条说明）。

V0.2 完成条件：A-S5 全部通过并有证据。

### S6 会话与记忆（V1.0）

| 任务 | 学习目标 |
|---|---|
| S6-01 | `InMemorySaver`、`thread_id`、历史写回、请求级字段重置 |
| S6-02 | 历史窗口与多轮查询改写 |
| S6-03 | 长期记忆：`save_memory` 工具与内存存储 |
| S6-04 | 记忆 CLI：list / clear |
| S6-05 | PostgreSQL Checkpointer 与长期记忆存储（需先申请安装依赖） |

验收场景：

- A-S6-1：同一 `session_id` 的第二轮能看到第一轮历史；出错的回合不写入历史；请求级字段不带入下一轮。
- A-S6-2：第二轮追问含指代时，检索使用改写后的独立问题，日志同时记录原问题与改写结果。
- A-S6-3：带 `user_id` 说“记住我主要用 Python”后，同一 `user_id` 的新会话能读取该记忆；`memory clear` 后不再读取；不带 `user_id` 时不写入；超过 20 条时删除最早的。
- A-S6-4【真实服务】：切换到 PostgreSQL 后重启进程，同一 `session_id` 历史仍可用；PostgreSQL 不可用时返回 `service_unavailable`。

### S7 服务化与部署（V1.0）

| 任务 | 学习目标 |
|---|---|
| S7-01 | FastAPI `/health` 与 `/v1/ask` |
| S7-02 | SSE：`astream` 输出 token、单一终止事件 |
| S7-03 | 客户端断开时取消与不写历史 |
| S7-04 | Redis 问答缓存与降级 |
| S7-05 | Docker Compose、`.env.example`、README |

验收场景：

- A-S7-1：TestClient 下 `/health` 正常；`/v1/ask` 的请求校验与错误码符合 4.10。
- A-S7-2：SSE 流以且仅以一个 `final` 或 `error` 结束；客户端中途断开后本轮不写入历史。
- A-S7-3：相同问题在 TTL 内命中缓存；重新入库后 `index_id` 改变，旧缓存不再命中。
- A-S7-4：Redis 不可用时问答仍可用，`degraded` 包含 `cache`。
- A-S7-5【真实服务】：`docker compose up` 后 `/health` 正常，`/v1/ask` 完成一次知识问答。

V1.0 完成条件：A-S6、A-S7 全部通过并有证据，V0.1/V0.2 验收测试仍通过；生成 `docs/REVIEW-V1.0.md`。

版本划分是计划，不代表功能已完成。实际进度以 `TASKS.md` 状态与测试证据为准。

## 8. 任务与学习文档规则

### 8.1 任务粒度与字段

每个任务只聚焦一个主要学习目标和一组紧密相关的代码变更。不得把“完成 RAG”“实现 Agent”“完善异常处理”等作为未拆分的任务。

`TASKS.md` 采用滚动细化：当前阶段的每个任务必须填全以下字段；后续阶段的任务可以只列编号、目标、前置任务和验收场景，在进入该阶段前补全（避免为尚不存在的代码编造文件路径）。

完整任务字段：

- 编号、优先级、所属版本与阶段、状态。
- 学习目标与要解决的问题。
- 前置任务。
- 需要阅读的代码（必须是仓库中真实存在的文件；尚不存在时写“无，新建”）。
- 预期修改范围（文件列表）。
- 测试先行步骤：要写的测试及预期的红灯原因。
- 验收标准与覆盖的验收场景编号。
- 测试命令与实际结果（命令、通过/失败数量、日期）。
- 学习文档路径。
- 完成后应具备的解释与操作能力。
- 对应面试知识点。

优先级：

- P0：所在阶段的验收场景直接依赖，不完成则阶段不可验收。
- P1：阶段内重要但可后置的质量项（例如额外边界测试、日志细化）。
- P2：可选实验或对比学习，不影响阶段验收。

一次只执行一个任务。任务完成后等待开发者复盘确认，再进入下一个任务。

### 8.2 任务状态

| 状态 | 含义 |
|---|---|
| `todo` | 未开始 |
| `in_progress` | 正在执行 TDD 流程 |
| `review` | 测试、Ruff、mypy 通过，学习文档已生成，等待开发者复盘确认 |
| `done` | 开发者已完成复盘并确认 |
| `blocked` | 因外部条件无法继续（必须写明原因，例如缺少密钥或依赖） |

### 8.3 学习文档（强制）

每个开发任务完成时，必须生成 `docs/learning/<任务编号>-<英文短名>.md`，例如 `docs/learning/S0-05-minimal-graph.md`。纯文档任务（例如编写 ARCHITECTURE）不要求学习文档。

学习文档必须包含：

1. 本次任务解决的问题。
2. 为什么需要这个功能。
3. 修改前的执行流程。
4. 涉及的真实文件、类、函数和调用关系。
5. 相关 Python、LangChain、LangGraph 或 RAG 原理。
6. 关键代码的执行顺序。
7. 输入、输出、状态变化和异常传播。
8. 为什么采用当前方案，而不是其他方案。
9. 新增或修改的测试，以及每个测试验证了什么。
10. 实际运行的测试命令与真实结果，包括红灯与绿灯输出摘要。
11. 容易混淆的概念。
12. 当前实现的局限和后续改进方向。
13. 至少 3 个与本任务真实实现相关的面试问题及要点。
14. 约 30 秒的口语化面试回答。
15. 一道不看答案、自己解释或修改代码的练习题。
16. 代码作者说明：哪些部分由开发者编写，哪些由 AI 编写或提示。

规则：

- 只描述已实现的行为，不提前描述未完成的功能，不编造测试结果。
- 不大段粘贴源码；引用文件路径和关键片段即可。
- 进入 `review` 前，必须核对文档中的文件名、函数名、测试名和命令输出与仓库实际一致。

## 9. AI 协作约束

AI 是辅助开发与教学工具，不是需求和正确性的最终裁决者。AI 生成的代码不等于开发者已掌握的知识。

每个任务的协作顺序：

1. AI 说明任务目标、关键原理和要读的代码，等待开发者确认理解。
2. AI 给出测试用例清单（输入、期望、预期红灯原因）；测试由开发者编写，或在开发者明确要求时由 AI 编写。
3. 运行测试并确认红灯。
4. 实现默认由开发者完成，AI 先给局部提示；只有开发者明确要求时才提供完整实现。
5. AI 按真实执行顺序解释关键代码，审查开发者的实现与回答，直接指出错误和遗漏，并给出最小修改后的正确表达。
6. 运行目标测试与回归检查，记录真实结果。
7. 生成学习文档并核对一致性，任务进入 `review`，等待开发者确认。

每次任务必须读取相关的 SPEC、ARCHITECTURE、TASKS，检查已有实现和 Git 工作区状态，只修改当前任务所需文件。

未经明确要求，不得：

- 一次性生成整个项目或多个任务的代码。
- 擅自修改已确认的公共接口。
- 删除或覆盖开发者已有修改。
- 自动提交 Git 变更。
- 安装、升级依赖或创建新的虚拟环境。
- 将测试未覆盖的行为描述为已经验证。
- 在缺少必要信息时自行编造业务需求。

SPEC 存在歧义，或设计决策影响公共接口、数据结构、持久化格式和安全行为时，先提出问题或备选方案，确认后再继续。不影响契约的局部实现细节可选择最简单方案，并在学习文档或 DECISIONS 中记录。

## 10. 文档与版本管理

- 开始 S0-01 编码前，必须完成 `docs/ARCHITECTURE.md` 与 `docs/TASKS.md` 初版。
- `ARCHITECTURE.md` 至少包含：模块划分与职责、各阶段图拓扑、State 字段类型与 Reducer、存储边界、外部依赖的封装接口与注入方式。
- `DECISIONS.md` 只记录真正经过权衡的取舍，每条写明备选方案与选择理由。
- 需求变更同步更新 SPEC；架构变更同步更新 ARCHITECTURE；TASKS 必须反映真实进度。
- V0.1 与 V1.0 完成后生成 REVIEW 文档，记录验收结果、测试证据、已知问题和未完成事项。
- Git 提交信息清晰、聚焦；不提交密钥、数据库凭据和真实用户隐私数据。

## 11. 项目级完成标准

项目达到 V1.0 的条件：

1. 第 7 章全部验收场景通过，且有测试证据。
2. RAG 双路召回、融合、重排、引用和评估能够运行，并有实测的消融报告与失败案例分析。
3. 路由、工具调用和 LangGraph 执行流程（条件边、循环、并行、Checkpoint）能够运行并有测试。
4. State、Checkpoint 和记忆之间的职责明确。
5. 关键异常、权限和输入校验具有可验证行为。
6. FastAPI 与 SSE 提供完整请求链路；PostgreSQL 与 Redis 按 3.5 的职责使用；Docker Compose 可启动必要服务。
7. 测试、Ruff、mypy 和部署验证结果有据可查；README 能指导配置、启动、测试和使用。
8. 每个已完成任务都有与代码一致的学习文档。
9. 不存在被隐瞒的关键缺陷或未经验证的性能承诺。
10. 开发者能够不依赖 AI，解释主要模块的职责、数据流、设计取舍、实验结论和异常处理机制，并能现场修改代码。

## 12. 默认决策

第 13–15、18 项已于 2026-10-20 由开发者确认；其余项确认前按此执行。修改任一项时，必须同步更新所引用的章节和验收场景。

保留自上一版：

1. 证据不足时拒答，`knowledge` 不用模型自身知识补充事实（4.10）。
2. 回答使用 `[n]` 内联引用而不是 JSON，以便流式输出（4.1、4.10）。
3. 路由解析失败时回退到 `knowledge`（4.3）。
4. 系统不做身份认证，`user_id` 不作为安全边界（4.5.2）。
5. 工具权限按意图静态授权（4.2）。
6. 入库全量重建，`chunk_id` 为 `{doc_id}#{序号}`，评估集以证据原文标注（4.6、4.8）。
7. 重排为必做项，调用托管服务（3.3）。
8. BM25 中文分词使用字符二元组，jieba 对比为可选（3.3）。
9. Redis 只做问答缓存（3.5）。
10. 长期记忆只通过 `save_memory` 工具写入，读取时全部注入（4.5.2）。
11. 数值默认值：问题长度上限 2000、`top_k` 默认 5、历史 10 轮、每用户 20 条记忆、外部调用最多重试 2 次、检索重试 1 次、工具循环 3 轮、缓存 TTL 1 小时、评估集至少 30 题（至少 5 题无答案）、切分长度 300 与 500、RRF `k=60`。
12. 类型检查使用 mypy（3.1、5.7）。

本版新增：

13. 【已确认】LangChain 与 LangGraph 从 S0 开始使用；V0.1 的 `ask` 由 LangGraph 图执行（2.3、4.4）。
14. 【已确认】图节点使用 `async def`，主入口为 `aask`，`ask` 为同步包装。理由：S5 并行召回、S7 的 SSE 与断开取消都依赖异步；从 S0 统一可避免后期改造。代价：S0 就需要学习 pytest-asyncio；`ask` 不能在已有事件循环中调用（4.10）。
15. 【已确认】CLI 通过 `python -m minirag` 运行，默认不把项目安装进共享 Conda 环境（3.4）。
16. 检索器实现 `BaseRetriever`，分数写入 `Document.metadata`（3.2）。
17. 工具执行节点自行实现，不使用预制 ToolNode 与预制 Agent（2.2、4.2）。
18. 【已确认】长期记忆使用 LangGraph Store 接口，S6 先用内存实现，S6-05 切换到 PostgreSQL（3.2、3.5）。
19. 切分规则在 4.6 中固定为可测试的行为契约；切片默认不重叠。
20. 协作默认由开发者编写实现，AI 提供提示与审查（第 9 章）。开发者 2026-10-20 的补充要求：小任务驱动、TDD 优先、每个任务配套学习文档、完成并确认后再进入下一项。
21. 依赖注入使用 LangGraph `context_schema` / `Runtime[Context]`，不放入 State（3.2）。

## 13. 修订记录

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-10-19 | 补充版本映射、问答契约、存储职责、验收场景和默认决策 | 消除原稿中未定义的行为，使需求可测试 |
| 2026-10-19 | 精简范围：版本由四个合并为三个；删除 SQLite 阶段、幂等键、增量索引、文档管理接口、自研重试框架与 Trace 文件；长期记忆改为工具写入；重排改为必做；新增消融实验与失败案例分析 | 复杂度集中在 RAG 与 Agent 核心机制及其实验证据 |
| 2026-10-20 | 引入阶段 S0–S7 与任务初始拆分；LangChain + LangGraph 从 S0 开始使用；新增框架使用约定（3.2）、State 字段表（4.5.1）、各阶段图拓扑（4.4）、切分与 RRF 的具体规则（4.6）、测试替身与测试标记（6.3、6.4）、任务字段与状态（8.1、8.2）、强制学习文档（8.3）、AI 协作顺序（第 9 章）；验收场景按阶段重新编号；记录实测环境版本；默认决策新增 13–20 | 项目要求从第一阶段使用 LangChain/LangGraph 并采用 TDD 小步学习；上一版把 LangGraph 推迟到 V0.2，且缺少任务粒度与学习产出的约束 |
| 2026-10-20 | 确认默认决策 13–15、18；新增决策 21（Runtime context 注入）；TASKS 改为滚动细化；记录 Reducer 在 Checkpoint 下的重置实测结果 | 开发者确认设计问题；实测 LangGraph 1.2.11 行为 |

**最终原则：项目以学习和工程实践为目的，优先保证正确性、可读性、可测试性和可解释性，不以代码数量、框架数量或功能堆积作为完成标准。**
