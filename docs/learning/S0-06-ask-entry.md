# S0-06 `aask` / `ask` 入口与日志关联

## 1. 本次解决的问题

S0-05 的图可以单独跑，但调用方还没有统一入口。本任务补上这条入口：

- `aask` 生成 `request_id`，在请求没有 `session_id` 时生成会话标识，测量耗时，用注入的 `AppContext` 执行 `build_graph()`，再把最终 State 组装成 `AskResponse`。
- `ask` 在没有正在运行的事件循环时，用 `asyncio.run` 调用 `aask`。
- `summarize_usage` 把 `usage_records` 收成一个 `Usage`。任一记录缺少 Token，或记录之间的模型名不同，结果都是 `None`。
- `logging_setup` 用 `contextvars` 保存当前 `request_id`，并在日志发出时写到 `LogRecord.request_id`。

S0 的成功路径固定为 `status=answered`、`intent=chat`。模型异常继续向外抛。错误码映射、CLI 和 Checkpointer 都没有做。

## 2. 为什么需要它

SPEC 4.10 要求 CLI、以后的 HTTP 和测试都走同一组函数。图只负责算出 `answer` 和用量记录。`request_id`、`session_id`、`status`、`intent`、汇总后的 `usage` 和 `latency_ms` 是响应契约，由入口填写。聊天节点不写 `status`，State 里也还没有 `intent`。

日志要能把同一次请求的多行串起来。异步任务跑在同一个线程上，一个全局变量会被并发请求盖掉。`contextvars` 让每个任务保留自己的标识，过滤器在写日志的那一刻读取它。

## 3. 修改前的执行流程

修改前没有 `service.py` 和 `logging_setup.py`。测试导入它们会在收集阶段失败。

已经能做的是：构造 `AskRequest` / `AskResponse`，用 Fake 模型 `ainvoke` 最小图，在最终 State 里看到 `answer` 和一条 `usage_records`。没有人生成 UUID，没有人把记录汇总成 `Usage`，也没有日志上下文。

## 4. 涉及的文件、类和调用关系

| 文件 | 职责 |
|---|---|
| `tests/graph/test_service_ask.py` | Fake 模型下的入口、汇总、日志和同步包装 |
| `src/minirag/service.py` | `summarize_usage`、`_elapsed_ms`、`aask`、`ask` |
| `src/minirag/logging_setup.py` | `request_id_var`、`RequestIdFilter`、`RequestIdFormatter`、`configure_logging`、`request_id_context` |

成功路径：

`ask` → 确认当前没有运行中的事件循环 → `asyncio.run(aask)` → `configure_logging` → 生成标识 → `request_id_context` → `build_graph().ainvoke` → `respond_chat` → `summarize_usage` → `AskResponse`

`aask` 不调用 `build_chat_model`，也不读取环境变量。模型和配置来自参数 `context`。`logging_setup` 不导入 `service` 或 `graph`。

## 5. 相关原理

**协程和事件循环。** `aask` 是协程函数。调用它只得到协程对象，要有事件循环才会执行到图。`asyncio.run` 创建循环、跑完这次协程、再关闭循环。Python 3.10 里，当前线程已经有运行中的循环时，`asyncio.run` 会抛出 `RuntimeError: asyncio.run() cannot be called from a running event loop`。循环不能在同一个线程里嵌套。FastAPI 这类环境应直接 `await aask`。

**先检查循环，再创建协程。** 参数在函数调用前求值。写成 `asyncio.run(aask(...))` 时，即使 `asyncio.run` 马上失败，协程也已经创建且没有人 `await`，解释器在回收时给出 `RuntimeWarning`。现在的 `ask` 先调用 `asyncio.get_running_loop()`。没有循环时这个调用自己抛出 `RuntimeError`，然后才 `asyncio.run`。已有循环时直接抛出和 `asyncio.run` 相同的那句错误，图不会执行。

**`contextvars`。** `ContextVar.set` 返回 token，`reset(token)` 恢复进入 `with` 之前的值，包括外层请求的标识。`asyncio` 创建任务时复制当前上下文，所以 `asyncio.gather` 里的两个 `aask` 各自持有自己的 `request_id`。`threading.local` 按线程隔离；这两个任务在同一个线程里，用它会读到同一个值。

**日志过滤器加在哪里。** 记录由子 logger 创建时，Python 只调用这个 logger 自己的过滤器，不调用父 logger 的过滤器。子 logger 默认把记录传播到根 handler。因此 `configure_logging` 把 `RequestIdFilter` 加到已经存在的根 handler 上，也加到名为 `minirag` 的 logger 及其已有 handler 上。过滤器在 handler 发出记录前执行，读的是当时的 `ContextVar`。pytest 的 `caplog` 把 handler 挂在根 logger 上，所以测试里能看到 `record.request_id`。

**部分 State 和响应是两层数据。** 图的最终 State 仍只有节点和入口写过的字段。`respond_chat` 不写 `status`。`AskResponse.status` 和 `intent` 在入口写成 `answered` 和 `chat`。响应里的 `request_id` 用入口生成的那个值，和日志上下文是同一个；它也会放进初始 State，但响应不从 State 里再读回来。

## 6. 关键代码的执行顺序

`aask` 进入后立刻用 `time.perf_counter()` 记起点，然后：

1. `configure_logging()`。已经加过的 `RequestIdFilter` 不会重复添加。本函数不新建 handler，也不改已有格式串。
2. `uuid.uuid4()` 生成 `request_id`。`session_id is None` 时再生成一个 UUID；否则用请求里的原值，包括空字符串和只含空白的字符串。
3. `with request_id_context(request_id)`。块内第一条日志是 `开始问答`。
4. `build_graph()`，再 `ainvoke({"request_id", "question"}, context=context)`。`user_id` 和 `top_k` 留在 `AskRequest` 上，不放进 State。
5. `state["answer"]` 原样进入响应。`usage_records` 交给 `summarize_usage`。`latency_ms` 在这里收成整数毫秒。
6. 再写一条 `问答完成`，返回响应。这条日志在计时之后，不计入 `latency_ms`。

`summarize_usage` 的顺序是：空列表直接 `None`；否则以第一条的模型名为准，逐条检查。模型名不同，或任一 Token 为 `None`，整次返回 `None`。全部通过时把输入 Token 和输出 Token 分别相加。0 按 0 相加。

图内部仍是 `START → respond_chat → END`。节点把一条 `UsageRecord` 追加进 State。入口看到的是追加之后的列表。

## 7. 输入、输出、状态变化和异常

输入是已经构造好的 `AskRequest`，以及带 `Settings` 和 `BaseChatModel` 的 `AppContext`。输出是 `AskResponse`。

一次带用量的调用：问题经过 `AskRequest` 去掉首尾空白，Fake 回复可以保留首尾空白。响应里 `status` 为 `answered`，`intent` 为 `chat`，`citations` 和 `degraded` 为空，`error` 为 `None`。`usage.model` 来自配置里的 `chat_model`，本测试配置是 `demo-chat`。

| 情况 | 结果 |
|---|---|
| 回复带 `usage_metadata` | `usage` 的两个 Token 与元数据一致，包括 0 |
| 回复没有 `usage_metadata` | 图里仍有一条 Token 为 `None` 的记录；响应 `usage` 为 `None` |
| 两条完整记录、同一模型 | Token 分别相加 |
| 多条里有一条 Token 为 `None`，或模型名不同 | 整个 `usage` 为 `None` |
| 回复是空字符串 | `answer == ""`，用量仍按记录汇总 |
| 未传 `session_id` | 响应里是新的 UUID，且和本次 `request_id` 不同 |
| 传入 `session_id`，包括 `""` 和 `"  "` | 原样返回 |
| 模型抛出 `TimeoutError` | 同一个异常继续抛出；至少有一条带本次 `request_id` 的日志；离开后 `request_id_var` 为 `None` |
| 已有事件循环时调用 `ask` | `RuntimeError`，Fake 模型的 `i` 仍为 0 |

初始 State 写入 `request_id` 和 `question`。节点返回 `answer` 和 `usage_records`。最终响应另外带上入口决定的 `session_id`、`status`、`intent`、`usage` 和 `latency_ms`。

日志上下文在 `with` 结束时恢复。成功、超时和内层 `request_id_context` 都会回到外层的值；最外层结束后变量是 `None`。

## 8. 为什么采用当前方案，以及容易混淆的做法

**依赖由调用方传入。** `aask(request, context)` 的第二个参数是 `AppContext`。入口里再调用 `Settings()` 或 `build_chat_model`，测试就会碰到本机 `.env` 和网络。ARCHITECTURE 3.1 写的就是每次调用传入 `context`。

**`status` 和 `intent` 写在入口。** S0 图没有路由。节点测试要求 `respond_chat` 只返回 `answer` 和 `usage_records`。响应契约又要求这两个字段。入口是目前唯一知道“这是聊天成功路径”的地方。

**模型名不一致时返回 `None`。** `Usage` 只有一个 `model`。把 Token 加总后记到第一个模型名上，会把别的模型的用量算进去。SPEC 没有写混合模型怎么汇总。当前 S0 图一次只用 `Settings.chat_model`。这条规则留在复盘里确认。

**空 `usage_records` 也是 `None`。** 没有记录就没有模型名。写成 0 会和“模型报告了 0 Token”混在一起。S0 的聊天节点每次都会留下一条记录，所以正常的 `aask` 不会走到空列表；空列表由 `summarize_usage` 的直接测试覆盖。

**每次请求都 `build_graph()`。** 这张图没有 Checkpointer，依赖在 `ainvoke` 时传入。编译一次再缓存也可以，但会多一个进程级对象。S0 只有一个节点，入口里现编译，调用关系看得更直接。

**过滤器加在现有 handler 上，不新增 handler。** 再挂一个 `StreamHandler` 会和 pytest、以后的服务进程各打一遍。`configure_logging` 也不替换别人的格式串。文本里要出现 `request_id`，handler 需要使用 `RequestIdFormatter` 或包含 `%(request_id)s` 的格式。`caplog` 的默认格式没有这个字段，测试因此直接读 `record.request_id`。`RequestIdFormatter` 在属性缺失时先写成 `-`，避免格式化抛错。

**`session_id` 先只出现在响应里。** 它以后会作为 Checkpoint 的 `thread_id`。S0 的图没有 Checkpointer，State 里也没有这个字段。现在把它放进 `ainvoke` 的配置，没有对应行为可以断言。

**异常不在本任务收成错误响应。** ARCHITECTURE 6.1 的第一步是校验失败直接返回 `invalid_request`。TASKS 把错误映射放在 S0-07。本入口只接受已经构造好的 `AskRequest`。非法问题在构造请求时就抛 `ValidationError`，到不了 `aask`。模型超时也原样抛出。

## 9. 测试以及各自验证的行为

`tests/graph/test_service_ask.py` 共 12 个测试。解释器能导入 `minirag` 是因为 pytest 的 `pythonpath = ["src"]`。

| 测试 | 验证 |
|---|---|
| `test_ask_returns_answered_chat_and_ids` | A-S0-1：`answered`、`intent=chat`、回复保留空白、问题中的花括号不影响结果、给定 `session_id`、`request_id` 可被 `uuid.UUID` 解析、`latency_ms` 是非负 `int`、响应 JSON 不含测试密钥 |
| `test_ask_keeps_given_session_id_including_blank` | `"sess-1"`、`""`、`"  "` 都原样返回 |
| `test_ask_generates_session_id_when_missing` | 缺省时 `session_id` 与 `request_id` 都是 UUID，两次调用互不相同，同一次响应里这两个标识也不同 |
| `test_aask_usage_follows_metadata` | A-S0-4：有元数据时填充 `Usage`，0 仍是 0，缺失时 `usage is None`，空回复保留为空字符串 |
| `test_summarize_usage_sums_only_complete_records_of_one_model` | 空列表、部分 Token、混合模型、其中一条缺失都得到 `None`；同一模型的完整记录相加 |
| `test_ask_fields_match_aask` | 去掉各自的 `request_id` 和 `latency_ms` 后，其余字段相同；两个 `request_id` 都是 UUID 且彼此不同 |
| `test_request_logs_share_one_request_id` | 连续两次 `ask` 的 `minirag.*` 日志，其 `request_id` 集合正好是这两个响应的标识；日志文本不含密钥；结束后上下文为 `None` |
| `test_concurrent_aask_keeps_separate_request_ids` | `asyncio.gather` 下两个请求的回答、会话标识和日志标识都分开 |
| `test_ask_cannot_run_inside_running_loop` | 运行中的循环里调用 `ask` 得到 `RuntimeError`，且 Fake 的 `i` 仍为 0 |
| `test_model_timeout_propagates_and_clears_request_id` | `TimeoutError` 原样抛出；已写出的日志共享一个非 `-` 的标识；上下文被恢复；日志不含密钥 |
| `test_filter_stamps_child_logger_and_formatter` | 子 logger `minirag.graph.nodes.chat` 在上下文内被标上标识，上下文外是 `-`；没有该属性的记录经 `RequestIdFormatter` 得到 `[-]` |
| `test_request_id_context_restores_outer_value` | 内层 `with` 结束后外层标识还在，最外层结束后为 `None` |

直接测 `summarize_usage`，是因为 S0 图一次只会写出一条记录。两条记录的相加规则如果不单独喂数据，就无法从当前的图观察到。

`test_ask_fields_match_aask` 比较的是同一次输入下的字段含义。它不要求两次生成的 `request_id` 或两次测量的 `latency_ms` 相等。

## 10. 实际运行的命令和结果

解释器：`C:\Users\11091\.conda\envs\medical-agent\python.exe`。日期：2026-10-20。工作区在开始时没有未提交改动。

红灯。当时最终测试文件已写好，还没有 `logging_setup.py` 和 `service.py`。更早一次收集失败是同一错误，`1 error in 0.85s`；补上空回复和格式器断言后重跑，结果如下。

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/graph/test_service_ask.py -q` | 收集阶段 1 error：`ModuleNotFoundError: No module named 'minirag.logging_setup'`，外层 `ImportError`。`1 error in 0.84s`。断言未执行 | 2 |

第一次实现后的目标测试是 `12 passed, 1 warning in 3.63s`，退出码 0。警告是 `RuntimeWarning: coroutine 'aask' was never awaited`，来自已有事件循环里先创建协程、再让 `asyncio.run` 失败。随后 `ask` 改为先检查循环。检查后的目标测试是 `12 passed in 4.36s`，退出码 0，没有这条警告。

接着的静态检查曾经失败：`ruff check .` 报两处 B010，`logging_setup.py` 用 `setattr` 写固定属性名；`mypy src` 报 `service.py` 里把 `ainvoke` 的 `dict[str, Any] | Any` 赋给 `AgentState`，`Found 1 error in 1 file (checked 14 source files)`。当时 `ruff format --check .` 已是 `30 files already formatted`。改为直接赋值，并用 `cast` 标出图的返回值之后，下面是文档写入前的回归。

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/graph/test_service_ask.py -q` | 12 passed in 3.75s | 0 |
| `python -m pytest -q` | 72 passed in 5.38s | 0 |
| `python -m pytest -m live -q` | 72 deselected in 3.52s，无未知标记错误 | 5 |
| `python -m pytest -m integration -q` | 72 deselected in 3.50s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 30 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 14 source files | 0 |

退出码 5 表示这些测试全部被标记排除，不能写成测试通过。未安装新包。未调用真实模型。未实现错误码映射、CLI 或 Checkpointer。S0-01 至 S0-05 仍是 `review`。本文写入后的复跑见第 17 节。

## 11. 容易混淆的概念

- `ask` 会新建事件循环。`aask` 使用调用方已经有的循环。在异步测试里调用 `ask`，测量的是“拒绝嵌套循环”，图不会跑。
- `asyncio.run(aask(...))` 这行即使马上抛错，括号里的协程也已经创建。检查循环必须发生在创建协程之前。
- 响应里的 `usage is None` 有三种来源：没有记录、记录里有缺失 Token、模型名无法放进一个字段。图里的那条 `UsageRecord` 仍然可以带 `None`，用来区分“没调用”和“调用了但没有用量”。响应字段按 SPEC 收成一个 `null`。
- Token 为 0 会得到 `Usage`，并且 0 参与相加。Token 为 `None` 让整次 `usage` 变成 `None`。
- `caplog.text` 默认不包含 `request_id`。标识在 `LogRecord.request_id` 上。格式串要自己包含 `%(request_id)s`。
- 父 logger 上的过滤器不会自动作用到子 logger。子 logger 的记录是在传到根 handler 时被过滤器写上属性的。
- `session_id` 现在只回到响应里。它还不是图的 `thread_id`。
- 入口写进 State 的 `request_id` 和响应里的 `request_id` 当前相同。响应使用的是入口手里的变量，不是图执行完再读出来的字段。
- `latency_ms` 可以是 0。Fake 模型很快时，向下取整后就是 0。测试只要求类型是 `int` 且大于等于 0。

## 12. 局限与后续

- 非法 `question` 或 `top_k` 仍由 `AskRequest` 在进入 `aask` 之前抛 `ValidationError`。返回 `invalid_request` 是 S0-07。
- 模型超时现在继续抛出，不会变成 `llm_unavailable`。响应里因此也还没有面向用户的错误说明。S0-07 负责映射。
- 混合模型名汇总为 `None` 是本任务的决定，SPEC 没有单独写这一条。
- `configure_logging` 只给调用当时已经存在的 handler 加过滤器。更晚创建的 handler 要等下一次 `aask` 或再次调用 `configure_logging`。
- 入口日志只有 `开始问答` 和 `问答完成` 两句固定文本，不记录问题，也不记录节点耗时。节点耗时在 S5-08。
- `session_id` 还没有交给 Checkpointer。同一会话的下一轮不会看到这一轮 State。
- 每次请求都重新编译图。图变大以后可以改成编译一次、多次 `ainvoke`。
- 没有 CLI，也没有用真实模型跑过 `ask`。A-S0-7 仍未验证。
- 日志测试证明测试密钥字符串没有出现在 `caplog.text` 和响应 JSON 里。它不能证明将来的真实客户端日志一定不打印密钥。

## 13. 面试问题

**问：为什么 `ask` 不能在 FastAPI 的请求函数里直接调用？**  
答：`ask` 通过 `asyncio.run` 跑 `aask`。`asyncio.run` 要自己创建并关闭事件循环。请求函数执行时循环已经在跑，同一个线程不能再套一层，所以抛 `RuntimeError`。服务里应该 `await aask(request, context)`。实现上还要先判断循环，再创建协程，否则失败路径会留下一个从未等待的协程。

**问：并发的两个请求为什么不能把 `request_id` 放在全局变量里？**  
答：两个 `aask` 会在同一个线程里交替执行。全局变量只有一份，后写入的标识会覆盖前一个，日志就会串。`ContextVar` 存在任务上下文里，`asyncio` 创建任务时会复制上下文。过滤器在真正输出日志时读取当前任务的值，所以每个 `LogRecord.request_id` 属于发出它的那个任务。

**问：没有 `usage_metadata` 时，为什么图里还有记录，响应里的 `usage` 却是 `None`？**  
答：记录留在 State 里，是为了区分“没调用模型”和“调用了但服务没给用量”。响应契约只有一个 `usage`。SPEC 要求任一调用拿不到用量时整个字段为 `null`，不能把缺失写成 0。入口看到 `None` Token 就返回 `None`。0 是另一回事，会汇总成 `Usage`。

## 14. 约 30 秒的口述

S0 的入口是异步的 `aask`。它生成 `request_id`，必要时生成 `session_id`，把标识放进 `contextvars`，再用注入的 Fake 或真实模型跑 LangGraph。图只写出 `answer` 和用量记录；`answered`、`chat`、Token 汇总和耗时由入口组装。`ask` 是 `asyncio.run` 的同步包装，已经有事件循环时不能调用。日志过滤器在输出时读取当前任务的 `request_id`，所以并发请求的日志不会混。任何一次调用缺少 Token，整次 `usage` 就是 `None`，不用 0 代替。

## 15. 练习

不看 `service.py` 和 `logging_setup.py`，先说出结果，再在解释器里核对。使用项目解释器，让它能导入 `minirag`。只用 Fake 模型，不要调用真实接口，也不要打印密钥。做完后不要把试验代码留在仓库里。

1. 在 `async` 测试里直接调用 `ask`。Fake 模型准备了两条回复。调用之后模型的 `i` 是 0 还是 1？抛出的异常类型是什么？
2. `summarize_usage` 收到两条记录，模型名都是 `demo-chat`。第一条输入 1、输出 2，第二条两个 Token 都是 `None`。返回值是 `Usage` 还是 `None`？如果第二条改成输入 0、输出 0，输入 Token 的总和是多少？
3. 用 `asyncio.gather` 同时跑两个 `aask`，各自的日志都在 `with request_id_context` 里写出。两条日志的 `request_id` 会相同吗？把 `request_id_var` 换成一个普通全局字符串之后，结果会怎样？

## 16. 代码作者说明

S0-06 的测试、`src/minirag/service.py`、`src/minirag/logging_setup.py`、`docs/TASKS.md` 中本任务的状态与结果，以及本文，都由 AI 在开发者明确要求实施 S0-06 后编写。开发者尚未手写这些代码。开始时 S0-05 仍是 `review`；开发者的实施请求被当作可以开始本任务的确认。S0-01 至 S0-05 没有改成 `done`。

## 17. 复跑

2026-10-20，第 1 至 16 节和 `docs/TASKS.md` 写入后，用同一解释器重跑。代码与第 10 节的那次回归相同，新增的是本文和任务状态。`-m live` 与 `-m integration` 的输出里没有未知标记错误。退出码 5 表示 72 个测试都被取消选择。`ruff format` 的 31 个文件包含本文件；写入本节表格之前，那次检查已经是 31 files already formatted。

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/graph/test_service_ask.py -q` | 12 passed in 3.45s | 0 |
| `python -m pytest -q` | 72 passed in 5.01s | 0 |
| `python -m pytest -m live -q` | 72 deselected in 3.46s，无未知标记错误 | 5 |
| `python -m pytest -m integration -q` | 72 deselected in 3.32s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 31 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 14 source files | 0 |

本节表格补上之后又执行了一次 `ruff check .` 和 `ruff format --check .`：仍是 All checks passed，以及 31 files already formatted，退出码都是 0。这次只改了 Markdown，没有再跑 pytest 和 mypy。
