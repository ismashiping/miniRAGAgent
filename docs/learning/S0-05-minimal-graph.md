# S0-05 LangGraph 最小图

## 1. 本次解决的问题

`ask` 从 S0 起就要由 LangGraph 执行，而不是在服务函数里直接调用模型。本任务把这条路径落成一张只有一个节点的图。

新增四样东西：

- `AgentState`：一次执行在节点之间传递的数据。`usage_records` 用 `operator.add` 追加。
- `UsageRecord`：一次模型调用的模型名和两个 Token 数。没有用量时 Token 为 `None`。
- `AppContext`：本次运行的 `Settings` 和 `BaseChatModel`。调用图时注入，不放进 State。
- `respond_chat` 与 `build_graph`：`START → respond_chat → END`。节点渲染聊天 Prompt，调用注入的模型，返回 `answer` 和一条用量。

没有 `aask` / `ask`，没有错误码映射，没有 Checkpointer，也没有把 `usage_records` 汇总成响应里的 `Usage`。

## 2. 为什么需要它

SPEC 决策 13 要求 V0.1 的 `ask` 由 LangGraph 执行。如果等到检索或工具出现后再引入图，S0 的调用方式就要推倒重来。先有一张最小的图，后面的节点是往同一张图上加，而不是换一条执行路径。

节点必须能脱离整图测试（A-S0-5）。模型如果在节点内部 `ChatOpenAI(...)` 或 `Settings()`，测试就得访问网络或读取本机 `.env`。`Runtime.context` 把依赖挡在节点签名上：单测自己构造 `Runtime`，整图测试在 `ainvoke` 时传入 `AppContext`。

`usage_records` 现在就用追加，是因为以后一次请求会调用模型多次，也可能并行写。只在第一次写的时候用覆盖，等并行出现再改 Reducer，已经写过的状态会被覆盖而不是合并。

## 3. 修改前的执行流程

修改前没有 `src/minirag/graph/`。测试导入 `minirag.graph.context` 或 `minirag.graph.builder` 会在收集阶段失败。

S0-04 已经能构造 `ChatOpenAI`、渲染聊天 Prompt，并把一条 `AIMessage` 转成 `Usage` 或 `None`。这三步没有被任何节点串起来，也没有 State。

## 4. 涉及的文件、类和调用关系

| 文件 | 职责 |
|---|---|
| `tests/unit/test_chat_node.py` | 直接调用 `respond_chat`，不编译图 |
| `tests/graph/test_chat_graph.py` | `build_graph()` 后 `ainvoke`，并检查 Reducer |
| `src/minirag/graph/__init__.py` | 图包说明。不在导入包时加载节点 |
| `src/minirag/graph/state.py` | `UsageRecord`、`AgentState` |
| `src/minirag/graph/context.py` | `AppContext` |
| `src/minirag/graph/nodes/__init__.py` | 节点包说明。不重新导出函数 |
| `src/minirag/graph/nodes/chat.py` | `RespondChatUpdate`、`respond_chat` |
| `src/minirag/graph/builder.py` | `build_graph` |

单测的调用是：

`Runtime(context=AppContext)` → `respond_chat` → `render_chat_prompt` → `chat_model.ainvoke` → `usage_from_ai_message` → `{answer, usage_records}`

整图的调用是：

`build_graph()` → `ainvoke(state, context=AppContext)` → LangGraph 注入 `Runtime` → 同一个 `respond_chat` → 合并进最终 State

`chat.py` 不导入 `build_chat_model`。`builder.py` 不创建模型。`llm/` 不导入 `graph/`。

## 5. 相关原理

**State 与 Context。** `AgentState` 是这次执行的数据，节点通过返回字典修改它。`AppContext` 是这次执行的依赖。已安装的 langgraph 1.2.11 用 `StateGraph(AgentState, context_schema=AppContext)` 声明后者。节点写成 `async def respond_chat(state, runtime: Runtime[AppContext])`。库在 `langgraph._internal._runnable.RunnableCallable` 里看到参数名 `runtime`，就把当前运行的 `Runtime` 传进来。`runtime.context` 就是调用时传入的 `AppContext`。

直接调用节点时，库不会插手。单测因此自己写 `Runtime(context=...)`。这是 dataclass，只填 `context` 即可，其余字段有默认值。这个构造方式在本环境里对 langgraph 1.2.11 实际运行过。

**部分更新。** 节点不返回完整 State。`respond_chat` 只返回 `answer` 和 `usage_records`。没返回的 `question` 和 `request_id` 保持入口写入的值。没人写过的 `status` 和 `error` 不会出现在最终 State 里。

**Reducer。** `usage_records: Annotated[list[UsageRecord], operator.add]` 让 LangGraph 为这个字段建立 `BinaryOperatorAggregate`，运算符是 `operator.add`。列表相加就是追加。普通字段用的是 `LastValue`：后写的值替换先写的值。S0 只有一个节点写用量，所以一次运行看不出“追加”和“覆盖”的差别，最终都是一条。测试因此同时检查注解和编译后 channel 上的 `operator`，并用 `operator(left, right) == left + right` 看合并结果。

**`ainvoke` 的两层含义。** 节点里的 `chat_model.ainvoke` 是 LangChain Runnable，输入消息列表，返回 `AIMessage`。图上的 `graph.ainvoke` 是编译后的图，输入初始 State 和 `context`。两个方法同名，调用对象不同。

**Fake 模型的计数。** `FakeMessagesListChatModel` 在只准备一条回复时，调用后内部下标 `i` 会回到 0。准备两条回复时，调用一次后 `i` 变成 1。测试用第二条占位回复，才能断言“调用了一次”和“另一个模型一次都没调用”。

## 6. 关键代码的执行顺序

`build_graph` 只做组装：创建 `StateGraph`，加入名为 `respond_chat` 的节点，连接 `START` 和 `END`，然后 `compile()`。不传 Checkpointer，编译结果的 `checkpointer` 为 `None`。

`graph.ainvoke({"request_id", "question"}, context=AppContext)` 之后，库把 context 放进 `Runtime`，调用 `respond_chat`。节点内部按这个顺序执行：

1. 读取 `state["question"]`。键不存在就抛 `KeyError`，模型还没被调用。
2. `render_chat_prompt` 得到系统消息和用户消息。用户消息的内容就是问题原文。
3. `runtime.context.chat_model.ainvoke(messages)`。异常原样向外抛。
4. `message.content` 不是 `str` 时抛 `TypeError`。空字符串可以通过。
5. `usage_from_ai_message(message, model=settings.chat_model)`。返回 `None` 时，记录里的两个 Token 字段写 `None`；返回 `Usage` 时，复制 `usage.model` 和两个 Token 数，不复制 `total_tokens`。
6. 返回只含 `answer` 和 `usage_records` 的字典。图把这条用量追加到 State。

模型名来自 `Settings.chat_model`，不来自 Fake 模型的类名，也不读取 `response_metadata`。

## 7. 输入、输出、状态变化和异常

节点输入是至少含 `question` 的 `AgentState`，以及带 `AppContext` 的 `Runtime`。输出固定两个键。

一次整图调用的例子：初始 State 是 `request_id="req-1"`、`question="今天天气如何"`。Fake 回复 `"图里的回答"`，用量是输入 4、输出 6。最终 State 仍有原来的 `request_id` 和 `question`，新增 `answer` 和长度为 1 的 `usage_records`，没有 `status` 和 `error`。

| 情况 | 结果 |
|---|---|
| 回复带 `usage_metadata` | 一条记录，Token 原样复制，包括 0 |
| 回复没有 `usage_metadata` | 仍是一条记录，`model` 仍是配置模型名，两个 Token 为 `None` |
| 回复是空字符串 | `answer == ""`，仍然有一条用量 |
| `content` 是块列表 | `TypeError`，模型已经调用过 |
| State 没有 `question` | `KeyError`，模型未调用 |
| 模型抛 `TimeoutError` | 同一个异常继续抛出，文本里没有 API Key |

节点不捕获异常，也不写日志。S0-07 才会把模型异常映射成 `llm_unavailable`。

## 8. 为什么采用当前方案，而不是其他方案

**依赖放在 Context，不放在 State。** State 会被以后的 Checkpoint 保存。模型和 `Settings` 放进去，就会碰到密钥和不可稳定序列化的客户端。ARCHITECTURE 3.1 要求用 `context_schema`。节点参数用 `runtime`，而不是在函数里调用 `get_runtime()`。后者依赖图执行时的上下文变量，直接单测节点时没有这个变量。

**单测直接构造 `Runtime`，不编译一个只有一个节点的临时图。** 编译后的注入和手写 `Runtime(context=...)` 给节点的是同一种对象。直接调用能断言“返回值只有两个键”。如果只测整图，没返回的字段会和入口写入的字段混在最终 State 里，看不出节点有没有多写。

**没有用量也追加一条记录。** 如果缺元数据时不写记录，`usage_records` 为空既可能是没调用模型，也可能是调用了但服务没返回用量。S0-06 需要把“任一调用没有用量”汇总成 `usage is None`。一条 Token 为 `None` 的记录把这件事留在 State 里。不能把缺失写成 0，这是 S0-04 已经定下的规则。

**`UsageRecord` 用 TypedDict。** 对外的 `Usage` 仍是 Pydantic 模型。图内部只需要三个键的字典，`operator.add` 连接的是普通列表。不在本任务把 `UsageRecord` 放进 `contracts.py`，因为调用方还看不到它；汇总仍是 S0-06 的事。

**不在节点里写 `status` 或 `intent`。** 任务要求部分更新只包含 `answer` 和 `usage_records`。`intent` 到 S5 才进入 State。`status` 和 `error` 已经出现在 S0 的 State 类型里，但本节点不写它们。最终响应的 `status=answered` 和 `intent=chat` 由 S0-06 的入口组装。

**非字符串回复直接拒绝。** S0 的聊天回复约定是纯文本。把块列表拼成字符串是另一种行为，本任务没有这种测试，也不在节点里猜测拼接规则。

**不在 `UsageRecord` 里记录耗时。** SPEC 4.1 写过每次模型调用要记录耗时。本任务的验收标准只要求 `answer` 和 `usage_records`。请求级 `latency_ms` 在 S0-06 由入口测量，节点耗时在 S5-08。当前记录没有耗时字段。这是留给复盘的决定，不是 SPEC 那句话已经被实现。

**不在 `build_graph()` 里绑定模型。** 图可以编译一次，每次 `ainvoke` 换一个 context。测试因此能证明未放进 context 的另一个 Fake 模型不会被调用。

## 9. 测试以及各自验证的行为

`tests/unit/test_chat_node.py`：

| 测试 | 验证 |
|---|---|
| `test_respond_chat_returns_answer_and_one_usage_record` | 只返回两个键；保留回复和问题中的空白与花括号；用量不含 `total_tokens` |
| `test_respond_chat_keeps_zero_token_counts` | Token 为 0 时仍然是 0 |
| `test_respond_chat_records_null_usage_when_metadata_missing` | 没有元数据时仍有一条记录，Token 为 `None` |
| `test_respond_chat_sends_rendered_chat_prompt` | 模型收到的是系统消息加用户消息，用户内容等于问题原文 |
| `test_respond_chat_keeps_empty_answer` | 空回复保留为空字符串 |
| `test_respond_chat_rejects_non_string_content` | 块列表回复抛 `TypeError` |
| `test_respond_chat_requires_question` | 缺少问题抛 `KeyError`，且 Fake 的 `i` 仍为 0 |
| `test_respond_chat_propagates_model_errors_without_api_key` | `TimeoutError` 原样抛出，异常文本不含测试密钥 |
| `test_respond_chat_uses_the_injected_model` | 只用 context 里的模型；调用期间构造 `Settings` 会失败 |

`tests/graph/test_chat_graph.py`：

| 测试 | 验证 |
|---|---|
| `test_build_graph_connects_start_to_respond_chat` | 只有 `respond_chat`；边是 `__start__` 到该节点，再到 `__end__`；没有 Checkpointer |
| `test_usage_records_uses_append_reducer` | 注解和编译后的 channel 都是 `operator.add`，两个列表会接在一起 |
| `test_chat_graph_writes_fake_answer_and_one_usage_record` | 最终 `answer` 等于 Fake 输出；`usage_records` 长度为 1；`question` 与 `request_id` 保留；没有 `status` 和 `error`；另一个模型的 `i` 仍为 0 |

图测试准备了两条 Fake 回复，所以 `i == 1` 表示调用了一次。只放一条回复时，这个库会把 `i` 拨回 0，断言会失效。

## 10. 实际运行的命令和结果

解释器：`C:\Users\11091\.conda\envs\medical-agent\python.exe`。日期：2026-10-20。

红灯，当时还没有 `src/minirag/graph/`：

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/unit/test_chat_node.py tests/graph/test_chat_graph.py -q` | 收集阶段 2 errors：`ModuleNotFoundError: No module named 'minirag.graph'`，外层 `ImportError`。2 errors in 1.39s。断言未执行 | 2 |

实现后、格式化前：

| 命令 | 结果 | 退出码 |
|---|---|---|
| 同上目标测试 | 12 passed in 4.00s | 0 |
| `python -m pytest -q` | 60 passed in 7.16s | 0 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | `tests/unit/test_chat_node.py` 1 file would be reformatted | 1 |
| `python -m mypy src` | Success: no issues found in 12 source files | 0 |

`ruff format` 只把该测试文件里 `FakeMessagesListChatModel(...)` 收成一行，没有改断言。

格式化之后：

| 命令 | 结果 | 退出码 |
|---|---|---|
| 目标测试 | 12 passed in 4.37s | 0 |
| `python -m pytest -m live -q` | 60 deselected in 4.08s，无未知标记错误 | 5 |
| `python -m pytest -m integration -q` | 60 deselected in 4.00s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 26 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 12 source files | 0 |

退出码 5 表示这些测试全部被标记排除，不是标记未注册，也不能写成测试通过。格式化前的默认 `pytest` 已是 60 passed。格式化后的默认 `pytest` 放在本文第 17 节的复跑里，避免把格式化前的次数写成格式化后的结果。未安装新包。未调用真实模型。

## 11. 容易混淆的概念

- `graph.ainvoke` 跑的是整张图。`chat_model.ainvoke` 跑的是一次模型调用。节点里面只有后者。
- 节点返回的字典不是最终 State。最终 State 还保留节点没有返回的输入字段。
- `usage_records` 长度为 1，不能单独证明 Reducer 是追加。一个节点写一次时，覆盖也会得到长度为 1 的列表。追加要看 `operator.add`。
- `UsageRecord` 不是 `Usage`。前者可以出现 `None`，并且每次调用一条。后者是入口汇总后的结果，本任务还没有汇总。
- Token 为 `None` 是没有用量。Token 为 0 是模型报告了 0。两条都会留下一条记录。
- `AppContext` 被冻结，只是不能换掉里面的模型对象。Fake 模型的 `i` 仍然会增加。
- `Runtime` 由库在图运行时注入。单测里要自己构造，否则参数没有人传。
- State 里声明了 `status` 和 `error`，不表示这次聊天节点已经写了它们。没写的可选字段不会出现在结果里。

## 12. 局限与后续

- 没有服务入口。`status=answered`、`intent=chat`、`request_id` 的生成和 `usage` 汇总都在 S0-06。
- 模型异常现在会直接抛出。映射成 `llm_unavailable` 是 S0-07。
- `UsageRecord` 没有耗时。见第 8 节。
- 非字符串回复不会被拼成文本。
- 没有 Checkpointer。两次 `ainvoke` 不会把上一轮的 `usage_records` 带进来。同一 `thread_id` 下用 `Overwrite` 重置，是 S6-01 已经记录的行为，本任务没有测。
- `AppContext` 只有 `settings` 和 `chat_model`。检索和重排字段留到对应阶段，并要带默认值。
- 节点不校验问题长度。空白问题和超长问题仍由 `AskRequest` 拒绝，那是入口的职责。
- S0-01 至 S0-04 仍是 `review`。本任务没有把它们改成 `done`。

## 13. 面试问题

**问：为什么不在节点里直接 `ChatOpenAI(...)`，而要从 `Runtime` 拿模型？**  
答：节点要能换成 Fake 做离线测试。模型、地址和密钥属于这一次运行的依赖，放进 `AppContext`，在 `ainvoke(..., context=...)` 时注入。放进 State 会把它们卷进以后的 Checkpoint。节点里再读全局 `Settings()`，测试就躲不开本机环境和网络。

**问：节点为什么只返回两个字段？没返回的 `question` 会丢吗？**  
答：LangGraph 节点返回的是部分更新。`question` 和 `request_id` 由入口写入，节点不返回它们，图就保留原值。`answer` 是普通字段，后写覆盖。`usage_records` 带 `operator.add`，返回的列表会追加，而不是把整个字段换成这一次的列表。只看一个节点的最终长度，区分不了这两种写法。

**问：没有 `usage_metadata` 时，为什么还要放一条记录，而不是省略或写成 0？**  
答：省略之后，空列表分不清“没调用”和“调用了但没有用量”。0 表示模型明确计数为 0。SPEC 要求缺失是 `null`。所以记录还在，两个 Token 字段为 `None`，模型名仍然是这次配置的 `chat_model`。

## 14. 约 30 秒的口述

S0 的图是 `START` 到 `respond_chat` 再到 `END`。状态用 `TypedDict`，节点只返回 `answer` 和一条 `usage_records`，没返回的问题会被保留。用量字段用 `operator.add` 追加，因为以后一次请求会调用多次模型。模型和配置放在 `AppContext`，通过 `Runtime` 注入，不放进 State，测试就可以换 Fake，也不会把密钥写进检查点。没有用量时仍然记一条，Token 用 `None`，不用 0。

## 15. 练习

不看 `chat.py` 和 `builder.py`，先说出结果，再在解释器里核对。使用项目解释器，让它能导入 `minirag`。只用 Fake 模型，不要调用真实接口，也不要打印密钥。做完后不要把试验代码留在仓库里。

1. 初始 State 只有 `question="你好"`。节点返回的 `answer` 是 `"ok"`，并且没有返回 `question`。`ainvoke` 的最终 State 里还有没有 `question`？有没有 `status`？
2. Fake 回复没有 `usage_metadata`。`usage_records` 的长度是 0 还是 1？其中的 `input_tokens` 是 `None` 还是 0？
3. 同一个编译后的图连续 `ainvoke` 两次，每次 context 里是同一个只含一条回复的 Fake。第二次结果里的 `usage_records` 长度是 1 还是 2？为什么？

## 16. 代码作者说明

S0-05 的测试、`src/minirag/graph/` 下的文件、`docs/TASKS.md` 中本任务的状态与结果，以及本文，都由 AI 在开发者明确要求实施 S0-05 后编写。开发者尚未手写这些代码。S0-01 至 S0-04 的状态仍是 `review`。开始本任务时，S0-04 也还在 `review`；没有把它改成 `done`。

## 17. 复跑

2026-10-20，第 1 至 16 节和 `docs/TASKS.md` 写入后，用同一解释器重跑。这次默认 `pytest` 发生在测试文件格式化之后。`-m live` 与 `-m integration` 的输出里没有未知标记错误。退出码 5 表示 60 个测试都被取消选择。`ruff format` 的 27 个文件包含 Python 和本仓库里的 Markdown，因为当前 Ruff 会把这些 Markdown 算进格式化范围；写入本节之前那次检查已经是 27 files already formatted。

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/unit/test_chat_node.py tests/graph/test_chat_graph.py -q` | 12 passed in 4.02s | 0 |
| `python -m pytest -q` | 60 passed in 5.87s | 0 |
| `python -m pytest -m live -q` | 60 deselected in 4.27s，无未知标记错误 | 5 |
| `python -m pytest -m integration -q` | 60 deselected in 4.06s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 27 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 12 source files | 0 |

本节补上之后又执行了一次 `ruff format --check .` 和 `ruff check .`：仍是 27 files already formatted，以及 All checks passed，退出码都是 0。没有再跑 pytest 和 mypy，因为这次只改了 Markdown。
