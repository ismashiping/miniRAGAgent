# MiniRAG Agent — Architecture

**状态：** 初版（2026-10-20），对应 SPEC Draft v2  
**说明：** 本文所有源码与测试路径均为规划路径，截至 2026-10-20 仓库中尚未创建。每个任务实现后，以实际代码为准回头修正本文。

---

## 1. 分层与依赖方向

```
cli.py / api/ (S7)          传输层：参数解析、HTTP、SSE
        │
service.py                  入口：aask / ask / ingest；request_id、计时、错误映射
        │
graph/                      编排层：State、节点、边、图构建
        │
llm/  retrieval/  ingest/   领域层：模型适配、检索算法、入库流水线、
answer/  tools/  evaluation/        引用校验、工具、评估
        │
contracts.py  config.py  errors.py   基础层：Schema、配置、领域异常
```

规则：

- 依赖只能自上而下。领域层不导入 `graph/`、`service.py`；基础层不导入任何项目模块。
- 检索、RRF、分词、指标、引用解析、计算器都是不依赖 LangGraph 的纯函数或类，可直接单测。
- 节点只做“从 State 取字段 → 调用领域函数 → 返回要更新的字段”，不写业务算法。

## 2. 规划目录

```
pyproject.toml
.env.example
src/minirag/
  __init__.py
  __main__.py            python -m minirag 入口                     S0-08
  cli.py                 子命令 ask / ingest / eval / memory         S0-08, S1-05, S4-04, S6-04
  config.py              Settings（pydantic-settings）               S0-03
  contracts.py           AskRequest、AskResponse、Citation、
                         ErrorInfo、Usage、IngestReport              S0-02, S1-05
  errors.py              领域异常与错误码映射                         S0-07
  logging_setup.py       request_id 上下文与日志格式                  S0-06
  service.py             aask / ask / ingest                         S0-06, S1-05
  llm/
    chat_model.py        build_chat_model、usage 转换                 S0-04
    prompts.py           聊天、证据、路由、改写 Prompt                 S0-04, S3-01, S5-01, S6-02
  graph/
    state.py             AgentState 与 Reducer                       S0-05 起逐步扩展
    context.py           AppContext（Runtime 注入的依赖）             S0-05 起逐步扩展
    builder.py           build_graph()                               S0-05 起逐步扩展
    nodes/
      chat.py            respond_chat                                S0-05
      retrieval.py       recall_* / fuse / rerank / filter_evidence  S2-07
      answer.py          generate_answer / refuse                    S3-03
      route.py           route 与路由函数                             S5-01, S5-02
      tools.py           call_model / execute_tools                  S5-04
      memory.py          load_history / save_turn / rewrite_query    S6-01, S6-02
  ingest/
    loader.py            读取与清洗                                   S1-01
    splitter.py          切分为 Document                              S1-02
    embeddings.py        build_embeddings                            S1-03
    index_store.py       索引写入、原子替换、加载                       S1-04
  retrieval/
    vector.py            VectorRetriever(BaseRetriever)              S2-01
    tokenizer.py         BM25 分词                                    S2-02
    bm25.py              BM25Retriever(BaseRetriever)                S2-03
    fusion.py            rrf_fuse                                    S2-04
    rerank.py            Reranker 接口与 HTTP 实现                    S2-05
    evidence.py          filter_evidence                             S2-06
  answer/
    citations.py         引用解析、校验、拒答判定                       S3-02, S3-03
  tools/
    calculator.py        AST 求值与 calculate 工具                     S5-03
    memory_tool.py       save_memory 工具                             S6-03
  evaluation/
    dataset.py, metrics.py, runner.py, report.py                     S4-01 – S4-04
  api/
    app.py, sse.py                                                   S7-01 – S7-03
  cache.py               Redis 问答缓存                               S7-04
tests/
  conftest.py            公共 fixture（Fake 模型、临时索引目录）
  fakes.py               项目自定义测试替身（S5 起支持 bind_tools）
  unit/                  纯函数、Schema、单节点
  graph/                 整图测试（Fake 依赖）
  integration/           @pytest.mark.integration
  live/                  @pytest.mark.live
data/corpus/             评估语料                                     S4-05
eval/datasets/  eval/reports/                                        S4
```

模块名 `evaluation` 而不是 `eval`，避免与内置函数 `eval` 混淆。

## 3. 外部依赖封装与注入

### 3.1 AppContext

```python
@dataclass(frozen=True)
class AppContext:
    settings: Settings
    chat_model: BaseChatModel
    # S2 起
    vector_retriever: BaseRetriever | None = None
    bm25_retriever: BaseRetriever | None = None
    reranker: Reranker | None = None
```

- 图通过 `StateGraph(AgentState, context_schema=AppContext)` 声明上下文；节点签名为 `async def node(state: AgentState, runtime: Runtime[AppContext]) -> dict`。
- `service.aask(request, context=...)` 在每次调用时传入 `context`；测试传入 Fake 依赖构造的 `AppContext`。
- 依赖不放入 State，因此不会被 Checkpoint 序列化。
- 字段按阶段增加；新增字段必须有默认值或同步更新所有构造处。

### 3.2 接口

| 依赖 | 生产实现 | 测试替身 |
|---|---|---|
| ChatModel | `ChatOpenAI(model, base_url, api_key, timeout, max_retries=2)` | `GenericFakeChatModel` / `FakeMessagesListChatModel`；S5 起用 `tests/fakes.py` 中支持 `bind_tools` 的替身 |
| Embeddings | `OpenAIEmbeddings(model, base_url, api_key, ...)` | `DeterministicFakeEmbedding` 或固定向量 Fake |
| Retriever | `VectorRetriever`、`BM25Retriever`（项目实现 `BaseRetriever`） | 返回固定 `Document` 或抛异常的 Fake |
| Reranker | 项目定义的接口：`async def rerank(query, documents) -> list[Document]`，分数写入 `metadata["rerank_score"]`；HTTP 实现调用托管 rerank 接口 | 返回固定分数或抛异常的 Fake |
| Checkpointer | S6：`InMemorySaver` → PostgreSQL | `InMemorySaver` |
| Store | S6：`InMemoryStore` → PostgreSQL | `InMemoryStore` |

Checkpointer 与 Store 在 `build_graph()` 编译时传入，节点通过 `runtime.store` 访问 Store。

## 4. State

### 4.1 字段类型（按阶段增加）

```python
class AgentState(TypedDict, total=False):
    # S0
    request_id: str
    question: str
    answer: str
    status: Literal["answered", "insufficient_evidence", "error"]
    error: ErrorInfo | None
    usage_records: Annotated[list[UsageRecord], operator.add]
    # S2
    top_k: int
    retrieval_query: str
    recall_results: Annotated[dict[str, list[Document]], merge_by_source]
    fused: list[Document]
    ranked: list[Document]
    evidence: list[Document]
    degraded: Annotated[list[str], union_sorted]
    # S3
    citations: list[Citation]
    # S5
    intent: Literal["chat", "knowledge", "calculate"]
    route_source: Literal["model", "fallback"]
    messages: Annotated[list[AnyMessage], add_messages]
    tool_rounds: int
    retrieval_attempts: int
    node_timings: Annotated[list[NodeTiming], operator.add]
    # S6
    history: list[ConversationTurn]
```

`UsageRecord`、`NodeTiming`、`ConversationTurn` 的具体字段在对应任务中定义。

### 4.2 Reducer

| Reducer | 行为 | 测试要点 |
|---|---|---|
| `operator.add` | 列表追加 | 并行两路写入后总数正确 |
| `merge_by_source` | 字典按键合并，同键覆盖 | 两路以不同顺序完成，结果相同 |
| `union_sorted` | 并集去重后排序 | 重复写入同一组件只出现一次 |
| `add_messages` | 按消息 ID 追加或替换 | 工具消息与 `tool_call_id` 对应 |

### 4.3 Checkpoint 下的请求级字段重置（S6-01）

实测（langgraph 1.2.11）：同一 `thread_id` 下，向 `operator.add` 字段传入 `[]` 会累积旧值；传入 `Overwrite([])` 才会重置。S6-01 的入口必须对请求级的 Reducer 字段传入 `Overwrite(...)`，对普通字段传入初始值，并用两轮调用的测试验证。

## 5. 各阶段图拓扑

```
S0:  START → respond_chat → END

S3:  START → recall_vector → recall_bm25 → fuse → rerank → filter_evidence
                                                              │ has_evidence?
                                                   ┌──────────┴──────────┐
                                             generate_answer           refuse
                                                   └──────────┬──────────┘
                                                             END

S5:  START → route ─┬─ chat → respond_chat → END
                    ├─ calculate → call_model ⇄ execute_tools（≤3 轮）→ END
                    └─ knowledge → prepare_retrieval ─┬─ recall_vector ─┬─ fuse → rerank → filter_evidence
                                                      └─ recall_bm25 ───┘        │
                                         （无证据且 retrieval_attempts < 1）→ rewrite_query → prepare_retrieval
                                         （有证据）→ generate_answer → END   （仍无证据）→ refuse → END

S6:  在 START 后加入 load_history；knowledge 分支前加入 rewrite_for_history；正常结束前加入 save_turn
```

S3 的线性召回在 S5-05 改为并行分支；S3 中任一路召回异常直接映射为 `retrieval_failed`，S5-06 改为单路降级。

## 6. 主要数据流

### 6.1 问答（S3 起）

1. `service.aask` 校验 `AskRequest`；失败时直接返回 `invalid_request`，不进入图。
2. 生成 `request_id`、`session_id`，设置日志上下文，开始计时。
3. 以初始 State 和 `AppContext` 调用 `graph.ainvoke`。
4. 召回节点把 `Document`（分数在 `metadata`）写入 `recall_results`；`fuse` 调用 `rrf_fuse`；`rerank` 失败时写入 `degraded=["rerank"]` 并沿用 RRF 顺序；`filter_evidence` 按阈值筛选。
5. 条件边：`evidence` 为空 → `refuse`；否则 `generate_answer` 渲染证据 Prompt、调用模型、解析并校验引用。
6. 入口把最终 State 转为 `AskResponse`：汇总 `usage_records` 为 `usage`，计算 `latency_ms`。
7. 节点抛出的领域异常在入口映射为错误码（见第 7 节）。

### 6.2 入库（S1）

`loader` 读取并清洗 → `splitter` 生成 `Document` → `embeddings.embed_documents` 批量向量化 → `index_store` 写入临时目录（`chunks.jsonl`、`vectors.npy`、`manifest.json`）→ 全部成功后替换正式目录 → 返回 `IngestReport`。

索引目录默认 `data/index/`（可配置），清单包含 `index_id`、切分配置、Embedding 模型名与维度、切片数、构建时间。

## 7. 错误处理

| 领域异常（`errors.py`） | 来源 | 错误码 |
|---|---|---|
| Pydantic `ValidationError`（入口） | `AskRequest` 校验 | `invalid_request` |
| `LLMUnavailableError` | 模型 SDK 超时、连接、限流等异常在适配层转换 | `llm_unavailable` |
| `RetrievalFailedError` | 召回全部失败 | `retrieval_failed` |
| `ServiceUnavailableError` | PostgreSQL 不可用（S6） | `service_unavailable` |
| 其他异常 | — | `internal_error`，堆栈只写日志 |

- 可降级的故障（重排、单路召回、Redis）不抛出，由节点写入 `degraded`。
- 工具错误转换为 `ToolMessage` 内容，不抛出。
- 转换异常时使用 `raise ... from exc` 保留原因。

## 8. 可观测性

- `logging_setup.py` 用 `contextvars` 保存 `request_id`，通过日志 Filter 注入每条日志。
- 节点耗时（S5-08）由图构建时统一包装节点或使用 LangChain 回调实现，具体方式在任务中决定并记录。
- Token 用量来自每次模型调用返回的 `AIMessage.usage_metadata`。
- 密钥使用 `SecretStr`，日志测试检查输出中不出现配置的 API Key。

## 9. 测试组织

- 默认 `pytest` 只运行 `tests/unit` 与 `tests/graph`（通过排除 `live`、`integration` 标记）。
- `pyproject.toml` 中配置：`pythonpath = ["src"]`、`asyncio_mode = "auto"`、标记声明、默认 `-m "not live and not integration"`。具体配置在 S0-01 中实测确认。
- 整图测试通过 `build_graph()` 加 Fake `AppContext` 运行，断言最终 State 和 Fake 的调用次数。

## 10. 待在任务中决定的实现细节

| 问题 | 决定于 |
|---|---|
| 标题分节使用 `MarkdownHeaderTextSplitter` 还是自写 | S1-02 |
| 重排重试使用 HTTP 客户端机制还是 `Runnable.with_retry` | S2-05 |
| 节点耗时记录方式（节点包装 vs 回调） | S5-08 |
| 支持 `bind_tools` 的测试替身实现方式 | S5-01 |

决定后记录到 `docs/DECISIONS.md`，并更新本文。
