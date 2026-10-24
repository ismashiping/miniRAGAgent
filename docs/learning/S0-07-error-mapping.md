# S0-07 错误映射

## 1. 本次解决的问题

S0-06 的 `aask` 只处理成功路径。非法请求在构造 `AskRequest` 时就抛 `ValidationError`，模型故障则原样抛出。调用方看到的是 Python 异常，不是契约里的 `AskResponse`。

本任务让入口自己收口：

- 空白问题、超过 2000 字符、`top_k` 越界，返回 `status=error`、`code=invalid_request`，`intent` 为 `None`，不调用模型。
- openai SDK 的超时、连接失败、429 和 5xx，先转成 `LLMUnavailableError`，再返回 `llm_unavailable`。
- 其他异常返回 `internal_error`。堆栈写入日志。响应里只有固定短句。
- `answer` 与 `error.message` 是同一句说明。响应 JSON 不含堆栈、异常原文和测试用的 API Key。

`build_chat_model` 仍然返回 `ChatOpenAI`。没有 CLI，也没有定义 `RetrievalFailedError` 或 `ServiceUnavailableError`。

## 2. 为什么需要它

SPEC 4.10 的错误码要让 CLI 和以后的 HTTP 用同一份响应判断成败，而不是各自捕获异常。A-S0-2 要求非法输入不调用模型。A-S0-3 要求超时和连接失败变成 `llm_unavailable`，响应里看不到堆栈和密钥。

ARCHITECTURE 第 7 节把转换放在两层：适配层用 `raise ... from` 把供应商异常收成领域异常，入口再把领域异常写成错误码。未知异常的堆栈只留在日志里。SPEC 5.5 禁止 `except Exception: return None` 这种把失败伪装成成功的写法。

## 3. 修改前的执行流程

修改前，`aask` 假定 `request` 已经是合法的 `AskRequest`。它直接读 `request.session_id` 和 `request.question`，然后 `ainvoke`。图或模型抛出的异常穿过 `aask` 和 `ask`。聊天节点也不捕获异常。

因此：

- 字典形式的非法请求到不了校验，`ask` 在读 `session_id` 时抛 `AttributeError`。
- `AskRequest.model_construct` 可以绕过 Pydantic 校验。空白问题和 `top_k=0` 仍会进入图，返回 `answered`。
- `openai.APITimeoutError`、`APIConnectionError`、`RateLimitError`、`InternalServerError`、内置 `TimeoutError`、`AuthenticationError`，以及用量为负数时的 `ValidationError`，都会原样离开入口。

`errors.py` 不存在。`chat_model.py` 只会构造模型和转换用量。

## 4. 涉及的文件、类和调用关系

| 文件 | 职责 |
|---|---|
| `src/minirag/errors.py` | `LLMUnavailableError`、三句固定说明、`invalid_request_info`、`error_info_for_exception` |
| `src/minirag/llm/chat_model.py` | `raise_provider_failure`。按已安装的 openai 3.13.0 判断哪些异常算模型不可用 |
| `src/minirag/service.py` | `aask` 再校验请求，捕获图异常，组装错误响应 |
| `tests/unit/test_errors.py` | 分类和固定文案，不跑图 |
| `tests/graph/test_service_errors.py` | 入口的错误响应、调用次数、日志 |
| `tests/graph/test_service_ask.py` | 原“内置超时继续抛出”的测试改为 `internal_error` |

成功路径不变：`ask` → 没有运行中的循环 → `asyncio.run(aask)` → 校验 → `build_graph().ainvoke` → `respond_chat` → `summarize_usage` → `AskResponse`。

失败路径在 `aask` 里分叉。聊天节点 `respond_chat` 仍然不捕获异常。节点单测里的内置 `TimeoutError` 还是会从节点抛出。

`errors.py` 不导入 openai。`chat_model.py` 不导入 `service`。入口调用 `raise_provider_failure`，避免让基础层的错误说明依赖 SDK。

## 5. 相关原理

**异常分层。** 供应商异常的类型和文本属于适配层。领域异常 `LLMUnavailableError` 只表示“模型现在不可用”。响应里的 `ErrorInfo` 再去掉类型名和原因。调用方只看 `code` 和固定 `message`。调试的人看日志和 `__cause__`。

**`raise ... from`。** `raise LLMUnavailableError(固定句子) from exc` 把原来的异常放在 `__cause__`，并让 `__suppress_context__` 为 `True`。`str(新异常)` 只有固定句子，不会自动带上原因里的密钥。入口随即捕获这个领域异常，不把它再抛给调用方。

**为什么不把所有 `ValidationError` 都当成 `invalid_request`。** 请求不合法是客户端问题。图内部构造 `Usage` 时 Token 为负数，也是 `ValidationError`，但那是我们自己的数据不合契约。第二种如果也返回 `invalid_request`，调用方会以为自己把问题写错了。所以只有进入图之前的那一次 `AskRequest` 校验使用 `invalid_request`。`error_info_for_exception` 看到 `ValidationError` 时返回 `internal_error`。

**日志里的堆栈不能用 `logger.exception`。** 它会格式化 `str(exc)`。openai 的 401 文本和测试里故意放进异常的 API Key 会跟着出现。`traceback.format_tb` 只保留栈帧和对应的源代码行，不保留异常消息。日志开头仍写上 `Traceback (most recent call last):`，方便认出这是堆栈。

**SDK 实际抛什么。** 已安装的 openai 3.13.0 在客户端里把 httpx 超时收成 `APITimeoutError`，把其他连接问题收成 `APIConnectionError`。`APITimeoutError` 继承 `APIConnectionError`。429 是 `RateLimitError`，5xx 是 `InternalServerError`。这几类都会被 SDK 重试，次数用尽后仍抛原来的类型。langchain-openai 1.6.2 再包成 `OpenAITimeoutError`、`OpenAIConnectionError`、`OpenAIRateLimitError`、`OpenAIAPIError`，它们分别继承上面的 openai 类型，所以 `isinstance` 能同时认出两层。400、401、403、404、408、409、422 不在这个元组里。内置 `TimeoutError` 也不是这些类。

**入口上的 `except Exception`。** 未知故障的定义就是“不是上面那些已知类型”。Python 3.10 里 `asyncio.CancelledError` 继承 `BaseException`，不会被这个 `except` 接住。Ruff 的 BLE001 禁止笼统捕获，这里是入口边界，用 `# noqa: BLE001` 标出原因。捕获之后要么返回 `llm_unavailable`，要么写堆栈并返回 `internal_error`，不会 `return None`。

## 6. 关键代码的执行顺序

`aask` 一进来就用 `time.perf_counter()` 记起点，调用 `configure_logging()`，生成 `request_id`。然后：

1. `_coerce_request`。已经是 `AskRequest` 时先 `model_dump()` 再 `model_validate`。字典直接 `model_validate`。失败则进入下面的校验失败路径，不再执行 2。
2. 校验失败：从原始对象里取出字符串形式的 `session_id`，没有就生成 UUID。空字符串保留。进入 `request_id_context`，写一条“请求校验失败”，返回 `invalid_request`。模型的调用计数保持 0。
3. 校验通过：`session_id is None` 时生成 UUID，否则用请求里的值。进入日志上下文，写“开始问答”。
4. `build_graph().ainvoke`。异常进入 `except Exception`。
5. `raise_provider_failure(exc)`。属于供应商不可用时抛出 `LLMUnavailableError`。入口记录异常类型名，不记录 `str(exc)`，返回 `llm_unavailable`。
6. 不能归类时 `_log_unhandled` 写类型名和 `format_tb`，返回 `internal_error`。
7. 没有异常时，仍按 S0-06 组装 `answered` / `chat`。

`ask` 仍先看当前线程有没有正在运行的事件循环。没有循环才 `asyncio.run(aask(...))`。错误响应从 `aask` 返回，`ask` 不再额外捕获。

## 7. 输入、输出、状态变化和异常

输入可以是 `AskRequest` 或字段映射，外加 `AppContext`。输出始终是 `AskResponse`，除非当前线程已经有事件循环：那时 `ask` 仍抛 `RuntimeError`，图不执行。

| 输入 | 结果 |
|---|---|
| 问题为空白、空串或 2001 字符；`top_k` 为 0 或 21 | `invalid_request`，模型调用次数 0 |
| `model_construct` 做出的空白问题和 `top_k=0` | 同样是 `invalid_request`，给定的 `session_id` 原样返回 |
| 合法字典，例如去掉空白后的“你好” | `answered`，`intent=chat` |
| `APITimeoutError`、`APIConnectionError`、429、500 | `llm_unavailable`，模型调用次数 1 |
| 内置 `TimeoutError`、401、`RuntimeError`、图内负 Token 的 `ValidationError` | `internal_error`，模型确实被调用过 |
| 任何错误 | `intent is None`，`usage is None`，`citations` 和 `degraded` 为空，`latency_ms` 是非负 `int` |

三句固定说明是：

- `invalid_request`：请求参数不合法。
- `llm_unavailable`：模型暂时不可用，请稍后重试。
- `internal_error`：服务内部出错，请稍后重试。

错误响应的 `request_id` 仍是新的 UUID。日志上下文在返回后恢复为 `None`。未知异常的 `minirag` 日志带有这个 `request_id`，并且含有 `Traceback (most recent call last):`。测试密钥放在异常消息里时，不出现在响应 JSON 里，也不出现在 `caplog.text` 里。

图的 State 在失败路径上不会被组装成成功响应。节点没有把 `error` 写进 State；错误码只存在于入口返回的 `AskResponse`。

## 8. 为什么采用当前方案

**入口再校验一次，并接受字典。** 若只依赖调用方先构造 `AskRequest`，非法数据在进 `aask` 之前就变成 `ValidationError`，A-S0-2 要求的“返回错误响应”不会发生。`model_construct` 又能绕过第一次校验。入口用 `model_dump` 后再 `model_validate`，两条路都归到同一次判断。

**分类函数放在 `chat_model.py`，错误文案放在 `errors.py`。** 哪些 SDK 类型算不可用，要对照 openai 和 langchain-openai 的继承关系。这个知识和 `ChatOpenAI` 放在一起。`errors.py` 若导入 openai，基础层就会绑死一家供应商。入口只负责捕获和写响应。

**不包装 `build_chat_model` 的返回值。** S0-04 的测试要求它就是 `ChatOpenAI`，并能读到 `model_name`、`request_timeout`。再套一层 `BaseChatModel` 会让这些断言失效，还可能让回调走两次。Fake 模型是测试直接放进 `AppContext` 的，本来就不会经过 `build_chat_model`。所以由入口在图抛出异常后调用 `raise_provider_failure`。节点仍然抛原始异常；领域异常在入口边界生成并马上被写成响应。这和“节点抛出领域异常”的最终形态差一步，原因是 S0 的节点保持薄，而且不改 S0-04 的返回类型。

**5xx 归入 `llm_unavailable`，408 和 409 不归入。** SDK 对超时、连接错误、408、409、429 和 5xx 都会重试。SPEC 的表把“模型调用重试耗尽”写成 `llm_unavailable`。429 和 5xx 有专门的异常类，和 ARCHITECTURE 写的超时、连接、限流放在一起。408 在 openai 3.13.0 里只是普通 `APIStatusError`，409 是 `ConflictError`。若捕获整个 `APIStatusError`，400 和 401 也会变成“模型不可用”。当前把 408、409 留成 `internal_error`。

**401 是 `internal_error`。** 密钥错误不是模型宕机。调用方若按 `llm_unavailable` 自动重试，只会重复用同一把错误的钥匙。响应文案同样不包含密钥。

**内置 `TimeoutError` 不是 `llm_unavailable`。** 它不是 openai 包里的类型。聊天节点的单测仍用它证明节点不吞异常。入口把它当成未知异常。

**错误响应的 `intent` 一律是 `None`。** SPEC 只规定校验失败时为 `null`。S0 没有路由节点，模型失败时也没有算出意图。不用 `chat` 冒充已经路由成功。

**不在本任务定义另外两个领域异常。** 契约里已有 `retrieval_failed` 和 `service_unavailable`，但还没有代码会抛它们。现在加上类却没有来源，属于后面阶段的事。

## 9. 测试以及各自验证的行为

`tests/unit/test_errors.py` 21 个测试，不编译图。

| 测试 | 验证 |
|---|---|
| `test_invalid_request_info_is_stable_and_hides_input` | 固定文案，不出现 `top_k` 或密钥 |
| `test_llm_unavailable_exception_uses_stable_message` | 默认文案稳定；即使构造时塞进密钥，`ErrorInfo` 也不复制那段文本 |
| `test_unknown_exception_becomes_internal_error_without_its_text` | `RuntimeError` 的文本、类型名和 `Traceback` 都不进说明 |
| `test_validation_error_is_not_treated_as_invalid_request` | 任意 `ValidationError` 经 `error_info_for_exception` 得到 `internal_error` |
| `test_api_timeout_is_reraised_from_the_sdk_error` | `APITimeoutError` 变成领域异常，`__cause__` 是原对象，`__suppress_context__` 为真，说明里没有 “Request timed out” |
| `test_langchain_timeout_wrapper_is_provider_unavailable` | `OpenAITimeoutError` 同样被认出 |
| `test_connection_rate_limit_and_server_errors_are_provider_failures` | 连接失败、LangChain 连接包装、429、LangChain 429、500、503 都转换，说明里没有密钥。共 6 个参数 |
| `test_existing_domain_error_is_not_wrapped_again` | 已经是 `LLMUnavailableError` 时原对象再抛出 |
| `test_non_availability_errors_are_left_unchanged` | 内置 `TimeoutError` 和 400、401、403、404、408、409、422 不转换。共 8 个参数 |

`tests/graph/test_service_errors.py` 18 个测试。Fake 列表模型准备两条回复：只准备一条时，调用一次后 `i` 会回到 0，无法证明“没有调用”。

| 测试 | 验证 |
|---|---|
| `test_invalid_payload_returns_invalid_request_without_calling_model` | 六个非法字典：`i == 0`，有内容的问题原文不进响应和日志，空 `session_id` 保留，缺省时生成另一个 UUID |
| `test_model_construct_is_validated_again` | 绕过构造校验的对象仍被拒绝，`session_id` 为 `sess-keep` |
| `test_aask_invalid_question_matches_ask` | 异步入口对空白问题同样返回 `invalid_request` |
| `test_valid_dict_still_answers` | 合法字典仍是 `answered` / `chat`，回复保留空白，模型调用一次 |
| `test_provider_failure_returns_llm_unavailable` | 超时、带密钥的连接错误、429、500。响应不含 SDK 原文和密钥，日志不含 `Traceback` 和密钥。共 4 个参数 |
| `test_aask_timeout_returns_llm_unavailable` | `aask` 直接面对 `APITimeoutError` |
| `test_unknown_exception_returns_internal_error_and_logs_stack` | `RuntimeError` 的文本不进响应；日志有堆栈头和同一个 `request_id`，没有密钥 |
| `test_builtin_timeout_is_internal_error` | 内置 `TimeoutError` 不是 `llm_unavailable` |
| `test_authentication_error_is_internal_and_hides_key` | 401 不伪装成模型不可用，密钥不进日志 |
| `test_negative_usage_inside_graph_is_internal_error` | 图内部的负 Token 是 `internal_error`，而且模型已经被调用 |

`tests/graph/test_service_ask.py` 的 `test_builtin_timeout_returns_internal_error_and_clears_request_id` 替换了原来的 `test_model_timeout_propagates_and_clears_request_id`。它继续检查日志标识和上下文恢复，并确认响应里没有 `timeout` 和 `Traceback`。聊天节点的单测没有改，节点仍向外抛内置 `TimeoutError`。

## 10. 实际运行的命令和结果

解释器：`C:\Users\11091\.conda\envs\medical-agent\python.exe`。日期：2026-10-22。开始时 S0-06 仍是 `review`，工作区里有 S0-06 尚未提交的文件。开发者明确要求实施 S0-07，因此开始本任务，没有把 S0-06 标为 `done`。

红灯分两次看，因为两个测试文件的失败点不同。

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/graph/test_service_errors.py -q` | 18 failed in 3.68s。字典请求在 `service.py` 读 `session_id` 时 `AttributeError`。`model_construct` 的空白问题得到 `answered`，断言期望 `error`。超时、连接、429、500、内置 `TimeoutError`、401、`RuntimeError` 和负 Token 的 `ValidationError` 都原样抛出 | 1 |
| `python -m pytest tests/unit/test_errors.py -q` | 收集阶段 1 error：`ModuleNotFoundError: No module named 'minirag.errors'`，外层 `ImportError`。`1 error in 3.14s`。断言未执行 | 2 |

实现后第一次跑这两个文件：39 个里 2 个失败，37 个通过。失败原因是测试只给了 Fake 模型一条回复，调用一次后 `i` 回到 0。这是测试写错，不是映射写错。补上第二条回复后，目标测试 `39 passed in 4.12s`，退出码 0。

接着 `tests/graph/test_service_ask.py` 里原来的超时测试失败：`Failed: DID NOT RAISE TimeoutError`。内置超时已被收成 `internal_error`。该测试已改成断言这个新行为。

文档写入前的回归：

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/unit/test_errors.py tests/graph/test_service_errors.py -q` | 39 passed in 3.66s | 0 |
| `python -m pytest -q` | 111 passed in 4.84s | 0 |
| `python -m pytest -m live -q` | 111 deselected in 3.14s，无未知标记错误 | 5 |
| `python -m pytest -m integration -q` | 111 deselected in 2.90s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 34 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 15 source files | 0 |

退出码 5 表示这些测试全部被标记排除，不能写成测试通过。实现过程中 `ruff check` 曾因 `service.py` 的 `except Exception` 报 BLE001。加上说明原因的 `# noqa: BLE001` 后通过。未安装新包。未调用真实模型。未把 S0-01 至 S0-06 标为 `done`。本文写入后的复跑见第 17 节。

## 11. 容易混淆的概念

- `AskRequest(...)` 在调用方手里失败，异常发生在 `aask` 之外。要得到 `invalid_request` 响应，应把字典交给 `aask` / `ask`，或让入口重新校验。
- `model_construct` 跳过校验。入口若直接信任已经是 `AskRequest` 的对象，非法 `top_k` 会进入图。
- `APITimeoutError` 是 `APIConnectionError` 的子类。捕获父类就已经包含超时。测试仍单独抛超时，避免以后改成只处理连接失败时看不出来。
- 内置 `TimeoutError` 和 `openai.APITimeoutError` 不是同一个类。前者到入口是 `internal_error`，后者是 `llm_unavailable`。
- `LLMUnavailableError` 的字符串是给领域层看的固定句子。响应不使用 `str(exc)`，而使用 `error_info_for_exception` 里的常量。两边现在文案相同，但是两条赋值。
- 错误响应的 `usage is None`，是因为失败路径不汇总用量。它和“调用成功但没有 `usage_metadata`”的 `None` 在响应里长得一样，要用 `status` 区分。
- Fake 模型只有一条回复时，`i` 在调用后回到 0。`i == 0` 不能单独证明没调用过。
- 父日志级别设成 WARNING 时，看不到 INFO 的“开始问答”。模型不可用的测试看的是 WARNING 那条，并且要求其中没有堆栈。

## 12. 局限与后续

- 节点抛出的仍是 SDK 异常或别的原始异常。`LLMUnavailableError` 在入口里生成后立刻变成响应，不会从节点边界抛出。
- HTTP 408 和 409 会被 SDK 重试，但当前映射为 `internal_error`。
- `retrieval_failed`、`service_unavailable` 还没有领域异常，也没有入口分支。
- LangGraph 的 `GraphInterrupt` 若在以后出现，当前的 `except Exception` 会把它收成 `internal_error`。
- 堆栈帧里的源代码行仍可能含有写死在 `raise` 那一行上的密钥。日志避免的是异常消息，不是源码本身。
- 错误响应的 `intent=None` 比 SPEC 字面多覆盖了模型失败和未知失败。SPEC 只点名了校验失败。
- 没有 CLI。A-S0-7 仍未用真实模型验证。
- 没有把 S0-06 学习文档里的历史描述改掉。那份文档记录的是当时的行为。

## 13. 面试问题

**问：为什么非法 `top_k` 不让 Pydantic 的 `ValidationError` 直接冒给调用方？**  
答：CLI 和以后的 HTTP 需要稳定的 `code=invalid_request`，并且 `intent` 为 `null`。`ValidationError` 的文本会带上用户输入，也不能保证不调用模型。入口在进图之前 `model_validate`，失败就返回固定说明。`model_construct` 绕得过构造函数，所以已经是 `AskRequest` 的对象也要再校验一次。

**问：模型超时为什么不在聊天节点里 `except` 后返回一段错误文本？**  
答：节点的契约是返回 `answer` 和用量，或者让异常继续走。它不知道响应码。入口同时看到校验错误、供应商错误和未知错误，才能保证响应里没有堆栈。供应商类型的判断放在 `chat_model.py`，用 `raise LLMUnavailableError from exc` 保留原因，但响应只写固定句子。

**问：未知异常既要记堆栈，又不能把 API Key 写进日志，这两件事怎么同时成立？**  
答：堆栈用 `traceback.format_tb`，里面是文件、行号和源代码，不是 `str(exc)`。`logger.exception` 会把异常消息一起打出，而 401 或连接错误的消息可能含有密钥。响应则完全不使用异常文本，只使用按错误码写死的三句话。

## 14. 约 30 秒的口述

问答入口先校验请求。问题为空、超长或者 `top_k` 越界，就返回 `invalid_request`，模型一次都不调。图里如果抛出 openai 的超时、连接失败、限流或 5xx，适配层用 `raise ... from` 转成 `LLMUnavailableError`，入口返回 `llm_unavailable`。别的异常返回 `internal_error`，堆栈只进日志。三种失败的响应都是固定短句，不带堆栈，也不带异常原文，所以密钥不会从错误文本漏出去。

## 15. 练习

不看 `errors.py`、`chat_model.py` 和 `service.py`，先说出结果，再在解释器里核对。使用项目解释器，让它能导入 `minirag`。只用 Fake 或自行构造的异常，不要调用真实接口，也不要打印密钥。做完后不要把试验代码留在仓库里。

1. `ask({"question": "  ", "top_k": 5}, context)` 的 `status`、`error.code` 和 Fake 模型的 `i` 分别是什么？若改成 `AskRequest.model_construct(question="你好", top_k=0, session_id="s", user_id=None)` 呢？
2. Fake 模型抛出 `openai.APITimeoutError`。响应的 `code` 是什么？若抛出的是内置 `TimeoutError("timeout")`，`code` 变不变？节点单测里直接调用 `respond_chat` 时，第二种异常还会不会变成响应？
3. 把 `logger.exception("失败")` 用在一条消息里含有密钥的 `APIConnectionError` 上。`caplog.text` 里为什么会出现密钥？当前实现用哪一个 traceback 函数避开它？

## 16. 代码作者说明

S0-07 的测试、`src/minirag/errors.py`、`chat_model.py` 与 `service.py` 的错误映射、`tests/graph/test_service_ask.py` 中那一个超时测试的新断言、`docs/TASKS.md` 里本任务的状态与结果，以及本文，都由 AI 在开发者明确要求实施 S0-07 后编写。开发者尚未手写这些代码。开始时 S0-06 仍是 `review`；这次实施请求被当作可以开始本任务的确认。S0-01 至 S0-06 没有改成 `done`。`service.py` 里开发者写在 `ask` 文档字符串和 `get_running_loop` 旁的说明保持原样。

## 17. 复跑

2026-10-22，第 1 至 16 节和 `docs/TASKS.md` 写入后，用同一解释器重跑。代码与第 10 节文档写入前的那次回归相同，新增的是本文和任务状态。`-m live` 与 `-m integration` 的输出里没有未知标记错误。退出码 5 表示 111 个测试都被取消选择。`ruff format` 的 35 个文件包含本文；写入本节之前，那次检查已经是 35 files already formatted。

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/unit/test_errors.py tests/graph/test_service_errors.py -q` | 39 passed in 4.22s | 0 |
| `python -m pytest -q` | 111 passed in 6.82s | 0 |
| `python -m pytest -m live -q` | 111 deselected in 3.77s，无未知标记错误 | 5 |
| `python -m pytest -m integration -q` | 111 deselected in 6.53s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 35 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 15 source files | 0 |

本节表格补上之后又执行了一次 `ruff check .` 和 `ruff format --check .`：仍是 All checks passed，以及 35 files already formatted，退出码都是 0。这次只改了 Markdown，没有再跑 pytest 和 mypy。
