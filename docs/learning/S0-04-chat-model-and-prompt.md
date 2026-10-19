# S0-04 ChatModel 工厂与聊天 Prompt

## 1. 本次解决的问题

问答流程需要一个可替换的聊天模型入口，一份渲染结果可以单测的聊天 Prompt，以及把单次模型回复里的 Token 用量转成契约 `Usage` 的函数。

本任务新增三样东西：

- `build_chat_model`：按 `Settings` 构造 `ChatOpenAI`，构造时不调用模型。
- `build_chat_prompt` / `render_chat_prompt`：把问题渲染成一条系统消息和一条用户消息。
- `usage_from_ai_message`：有 `usage_metadata` 时生成 `Usage`，没有时返回 `None`。

没有把它们接进 LangGraph，也没有汇总多次调用，也没有把模型异常映射成错误响应。

## 2. 为什么需要它

S0-05 的 `respond_chat` 节点要调用模型。如果节点里直接写 `ChatOpenAI(...)`，模型名、地址、密钥和超时就散落在图代码里，测试也很难在不访问网络的情况下换掉实现。SPEC 4.1 要求用工厂函数返回 `BaseChatModel`，这些值都来自配置。

Prompt 和调用要分开。`ChatPromptTemplate` 把系统指令和用户问题写成模板，测试可以只检查渲染出的消息，不必真的请求模型。SPEC 3.2 把这一点列为 S0 就要用的原因。

`AskResponse.usage` 的字段是 `model`、`input_tokens`、`output_tokens`。LangChain 的 `AIMessage.usage_metadata` 用同名的 Token 字段，但没有模型名，还多了 `total_tokens`。缺用量时 SPEC 要求是 `null`，不能写成 0。转换函数把这条约定落在一个地方，后面的节点只调用它。

## 3. 修改前的执行流程

修改前没有 `src/minirag/llm/`。测试导入 `minirag.llm.chat_model` 或 `minirag.llm.prompts` 会在收集阶段失败。配置停在 `Settings`，契约停在 `Usage`，两者之间没有模型对象，也没有消息列表。

## 4. 涉及的文件、类和调用关系

| 文件 | 职责 |
|---|---|
| `tests/unit/test_chat_model.py` | 工厂配置、离线构造、密钥不出现在显示文本中、用量转换 |
| `tests/unit/test_prompts.py` | 聊天 Prompt 渲染成系统消息和用户消息 |
| `src/minirag/llm/__init__.py` | 领域层包说明。不重新导出函数，调用方从子模块导入 |
| `src/minirag/llm/chat_model.py` | `build_chat_model`、`usage_from_ai_message` |
| `src/minirag/llm/prompts.py` | `CHAT_SYSTEM_PROMPT`、`build_chat_prompt`、`render_chat_prompt` |

本任务的调用关系是三条互不调用的路径：

`Settings` → `build_chat_model` → `ChatOpenAI`

`question` → `render_chat_prompt` → `build_chat_prompt` → `ChatPromptTemplate.format_messages` → `[SystemMessage, HumanMessage]`

`AIMessage` + 模型名 → `usage_from_ai_message` → `Usage` 或 `None`

`chat_model.py` 只导入 `Settings` 和 `Usage`。`prompts.py` 不导入项目模块。两者都不导入 `graph/` 或 `service.py`。

`config.py` 第 64 行有一条关于 `AliasChoices` 的中文注释。那不是本任务写的。检查过程中它的空格曾不符合 Ruff 格式，后来文件里已经带上空格。本任务没有改 `config.py`。

## 5. 相关原理

**`BaseChatModel` 与 Runnable。** 已安装的 langchain-openai 1.6.2 里，`ChatOpenAI` 的继承顺序是 `ChatOpenAI` → `BaseChatOpenAI` → `BaseChatModel`。`BaseChatModel` 实现 Runnable 的 `invoke` / `ainvoke`。工厂的返回类型写成 `BaseChatModel`，是为了让后面的节点依赖这个接口，测试可以换成 Fake 模型。本任务只构造对象，不调用这两个方法。

**构造参数和字段名不是同一套。** 对照 `langchain_openai/chat_models/base.py` 里的 `BaseChatOpenAI`：

| 传给 `ChatOpenAI` 的参数 | 存在实例上的字段 | 本项目的来源 |
|---|---|---|
| `model` | `model_name` | `settings.chat_model` |
| `base_url` | `openai_api_base` | `settings.base_url` |
| `api_key` | `openai_api_key` | `settings.api_key` |
| `timeout` | `request_timeout` | `settings.timeout` |
| `max_retries` | `max_retries` | `settings.max_retries` |

`validate_environment` 会在构造时创建 `openai.OpenAI` 和 `openai.AsyncOpenAI`，并把 `base_url`、`timeout`、`max_retries` 放进客户端。实测这个过程不调用 `socket.create_connection`、`socket.socket.connect` 或 `socket.getaddrinfo`。真正的 HTTP 请求发生在之后的 `invoke` / `ainvoke`。

客户端里的 `base_url` 会被 openai SDK 规范成带末尾斜杠的地址。`ChatOpenAI.openai_api_base` 仍保持传入的原字符串。

**显式配置优先于 OpenAI 环境变量。** `langchain_core.utils._gateway._resolve_gateway_config` 的顺序是：调用方传入的 `base_url` 和 `api_key` 优先，其次才是 `OPENAI_API_BASE`、`OPENAI_API_KEY`。工厂把 `Settings` 里的值传进去，所以进程里即使还有一套 `OPENAI_*`，也不会改掉本次配置。

**SDK 重试。** 当前 openai 客户端在 `_base_client.py` 里用 `for retries_taken in range(max_retries + 1)` 发请求。`max_retries=2` 表示首次失败后最多再试 2 次；`0` 表示不重试。SPEC 4.7 要求模型和 Embedding 用 SDK 自带的超时与重试，不自写通用重试。因此这里只把 `settings.max_retries` 交出去，没有使用 `Runnable.with_retry`。

**`ChatPromptTemplate`。** `from_messages` 接受 `("system", 文本)` 和 `("human", "{question}")`。默认按 f-string 解析模板，所以系统文本里不能出现花括号。用户问题是 `{question}` 的值，代入之后不会再被当成模板。`format_messages` 直接给出消息列表；`invoke` 走 Runnable，返回的 `ChatPromptValue.to_messages()` 与前者一致。

**用量。** `UsageMetadata` 是 `TypedDict`，必填 `input_tokens`、`output_tokens`、`total_tokens`，可选明细。`AIMessage.usage_metadata` 默认 `None`。`Usage` 只要模型名和两个 Token 数，且都 `ge=0`。0 是合法计数。`None` 表示这条回复没有用量。

## 6. 关键代码的执行顺序

构造模型时，`build_chat_model` 只做一件事：把 `Settings` 的五个字段传给 `ChatOpenAI`。随后库自己执行：

1. 按别名写入 `model_name`、`openai_api_base`、`openai_api_key`、`request_timeout`、`max_retries`。
2. `validate_environment` 看到调用方已经传入地址和密钥，就不再采用 `OPENAI_API_BASE` / `OPENAI_API_KEY`。
3. 创建同步 `root_client` 和异步 `root_async_client`。`max_retries` 不是 `None` 时写入客户端，因此 `0` 也会写入，不会落回 SDK 默认的 2。
4. 函数返回。没有 `invoke`，也没有日志。

渲染 Prompt 时，`render_chat_prompt` 调用 `build_chat_prompt().format_messages(question=question)`。模板每次新建。系统消息内容固定，用户消息内容等于传入的字符串。

转换用量时，先看 `message.usage_metadata`。是 `None` 就返回 `None`。否则用调用方传入的 `model` 和两个 Token 字段构造 `Usage`。不读 `total_tokens`，也不读 `response_metadata`。

## 7. 输入、输出、状态变化和异常

这三个函数都不保存全局状态，也不写日志。

`build_chat_model` 的输入是 `Settings`。输出是 `ChatOpenAI`。密钥以 `SecretStr` 传入，本函数不调用 `get_secret_value()`。实测 `str` / `repr` 中不出现密钥原文。构造失败时异常直接抛出，没有捕获。

`render_chat_prompt` 的输入是问题字符串。输出是两条消息。它不去空白，也不检查长度。空字符串会变成空的用户消息。问题里的 `{name}` 按字面保留。

`usage_from_ai_message` 的输入是一条 `AIMessage` 和一个模型名。输出是 `Usage` 或 `None`。Token 为负数时，`Usage` 的 `ge=0` 抛出 `ValidationError`，函数不把它变成 `None` 或 0。`AIMessage` 自己会拒绝缺少 `output_tokens` 的 `usage_metadata`，所以不完整的字典到不了这个函数。

## 8. 为什么用当前方案

模型名由调用方传入，而不是从 `response_metadata["model_name"]` 读取。`usage_metadata` 没有模型名；不同服务放模型名的键也不一样。S0 每次调用用的就是 `settings.chat_model`，调用方知道这个名字。

没有在本任务汇总多次调用。SPEC 4.10 的 `usage` 是整次请求的汇总，TASKS 把这件事放在 S0-06。这里一次只转换一条 `AIMessage`。

系统指令写成固定中文：直接回答，不声称查阅了知识库，不编造引用。S0 到 S2 的 `ask` 只走闲聊。证据编号、拒答、路由和历史都是后面的 Prompt，放进这份模板会让“恰好两条消息”不再成立。

重试次数使用 `settings.max_retries`，不在工厂里写死 2。默认配置仍然是 2，因为 `Settings` 的默认值是 2。配置成 0 时客户端必须真的是 0，否则“可配置”只停留在字段上。

返回类型是 `BaseChatModel`，实际对象是 `ChatOpenAI`。测试同时检查这两个类型：前者是 SPEC 的接口，后者才能断言 `model_name` 这些字段。

没有包一层自己的 ChatModel 类。库已经提供统一接口，再包一层只是把属性转发一遍。

## 9. 测试验证了什么

| 测试 | 验证 |
|---|---|
| `test_build_chat_model_applies_settings_without_network` | 模型名、地址、超时 30.5、重试 2 写到模型和同步/异步客户端；密钥可取出但显示文本不含原文；构造期间 DNS 和 TCP 被禁止 |
| `test_build_chat_model_uses_settings_defaults` | 未传入时超时 600、重试 2，并出现在 `ChatOpenAI.max_retries` 上，而不是 `None` |
| `test_build_chat_model_passes_custom_timeout_and_zero_retries` | 超时 12.5 和重试 0 进入两个客户端，没有被默认值 2 覆盖 |
| `test_build_chat_model_prefers_settings_over_openai_environment` | `OPENAI_API_KEY`、`OPENAI_API_BASE`、`OPENAI_BASE_URL` 不覆盖 `Settings`，显示文本也不含那把环境变量密钥 |
| `test_usage_from_ai_message_copies_token_counts` | 复制 11 和 7；模型名用参数 `demo-chat`，不用 `response_metadata` 里的 `other-model`；不保留 `total_tokens` |
| `test_usage_from_ai_message_without_metadata_is_none` | 未提供用量时返回 `None` |
| `test_usage_from_ai_message_explicit_none_is_none` | 显式 `usage_metadata=None` 同样返回 `None` |
| `test_zero_token_counts_stay_zero` | 0 保持为 0，不当成缺失 |
| `test_negative_token_count_is_rejected` | 负数抛 `ValidationError`，不变成 `None` |
| `test_render_chat_prompt_is_system_then_human` | 两条消息，类型和系统文本固定，用户消息是“你好” |
| `test_render_chat_prompt_keeps_question_verbatim` | 首尾空格和 `{name}`、`{question}` 原样留在用户消息 |
| `test_render_chat_prompt_keeps_empty_question` | 空字符串仍渲染，用户消息为空 |
| `test_system_message_does_not_change_with_question` | 换问题只改变用户消息 |
| `test_chat_prompt_invoke_matches_render` | `invoke({"question": ...}).to_messages()` 与 `render_chat_prompt` 一致 |

构造测试用 `monkeypatch` 清掉 `MINIRAG_*` 和 `OPENAI_*`，并用 `Settings(_env_file=None)`，避免读到本机 `.env`。网络断言替换了三个 socket 函数，任一被调用都会失败。

## 10. 实际运行的命令与结果

解释器：`C:\Users\11091\.conda\envs\medical-agent\python.exe`。日期：2026-10-20。

红灯：只有测试、尚无 `src/minirag/llm/` 时，`pytest tests/unit/test_chat_model.py tests/unit/test_prompts.py -q` 在收集阶段报 `ModuleNotFoundError: No module named 'minirag.llm'`（外层为 `ImportError`）。两个文件各 1 个 error，共 2 errors in 3.87s，退出码 2。断言没有执行。

实现后第一次绿灯：同一命令 14 passed in 5.69s，退出码 0。

`ruff format` 只调整了 `tests/unit/test_chat_model.py` 里一行过长的 `monkeypatch.setattr`。调整后该命令 14 passed in 5.92s，退出码 0。

随后的回归，当时 `config.py` 的注释已经带有 Ruff 要求的空格：

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest -q` | 48 passed in 5.11s | 0 |
| `python -m pytest -m live -q` | 48 deselected in 3.82s，无未知标记错误 | 5 |
| `python -m pytest -m integration -q` | 48 deselected in 3.61s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 17 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 6 source files | 0 |

`-m live` 与 `-m integration` 是在最终 `pytest -q` 之前单独跑的，取消选择的数量同为 48。退出码 5 表示全部被取消选择，不是标记未注册，也不能写成测试通过。

中间有一次 `ruff format --check .` 失败：`config.py` 第 64 行当时是 `)#AliasChoices...`，同时测试文件还有未换行的长调用。那次检查是 2 files would be reformatted，退出码 1。`ruff check .` 当时已经通过。我只格式化了本任务的测试文件。`config.py` 的注释不是本任务添加的，没有改它的措辞；稍后磁盘上的这一行已经是 `)  # AliasChoices...`，上面的 17 files 结果就是在那之后得到的。

更早一次 `mypy src` 在格式检查尚未通过时已经输出 `Success: no issues found in 6 source files`。上表是格式通过后的另一次 mypy，结果相同。未安装新包。未把 S0-01、S0-02、S0-03 标为 `done`。

## 11. 容易混淆的概念

- `model` 参数和 `model_name` 字段是同一个值的两个名字。测试要断言的是字段 `model_name`。
- `ChatOpenAI.max_retries is None` 时，库不会把重试次数写进客户端，客户端再用自己的默认值 2。所以“客户端是 2”并不能证明工厂传了 2。测试同时断言模型和客户端。
- `max_retries=2` 不是“一共请求 2 次”。当前 SDK 的循环是 `max_retries + 1` 次机会。
- `usage is None` 是没有用量。`input_tokens=0` 是报告了 0。负数既不是缺失，也不是 0，而是 `ValidationError`。
- `usage_metadata` 里的 `total_tokens` 不会进入 `Usage`。契约没有这个字段。
- 系统消息里的花括号是模板变量。用户问题里的花括号是普通文本。
- Prompt 的 `invoke` 只渲染消息。模型的 `invoke` 才会发 HTTP 请求。本任务测试了前者，没有调用后者。
- 工厂返回的对象离线构造成功，不等于模型服务可用。那是 S0-08 的 `live` 测试。

## 12. 局限与后续

- 没有 `respond_chat`，也没有 `ainvoke`。图在 S0-05。
- 没有把多条 `Usage` 加成一个响应字段。汇总在 S0-06。
- 没有把超时、连接失败映射成 `llm_unavailable`。那是 S0-07。
- 没有证据 Prompt、路由 Prompt、历史占位符。对应 S3-01、S5-01、S6-02。
- 系统指令的具体措辞由本任务确定，SPEC 没有逐字规定。改措辞必须同时改 `test_prompts.py` 里的期望文本。
- 模型名来自调用方参数。若服务返回的快照名和请求的模型名不同，这里不会自动改用快照名。
- `render_chat_prompt` 接受空字符串。拒绝空白问题仍是 `AskRequest` 的职责。
- 不完整的 `usage_metadata` 由 `AIMessage` 在构造时拒绝。本函数没有为这条路径单独写测试。
- S0-01、S0-02、S0-03 仍是 `review`。本任务没有把它们改成 `done`。

## 13. 面试问题

**问：为什么工厂返回 `BaseChatModel`，而测试又检查它是 `ChatOpenAI`？**  
答：节点以后只需要 `invoke` / `ainvoke`，所以类型标注用接口，测试才能替换成 Fake。生产实现必须是 `ChatOpenAI`，超时和重试才进得了 openai 客户端。只断言接口，就看不到 `max_retries` 有没有真的写进去。

**问：Token 用量从哪来，为什么会缺失？缺失时为什么不能填 0？**  
答：用量在模型回复的 `AIMessage.usage_metadata` 里，由提供商在响应中返回。有的兼容接口不返回这段数据，字段就是 `None`。0 表示模型明确数出了 0 个 Token。SPEC 要求缺失时 `usage` 为 `null`，用 0 会把“未知”说成“没有消耗”。

**问：模型重试为什么交给 SDK，而不是自己写循环或 `with_retry`？**  
答：SPEC 4.7 规定模型和 Embedding 使用 SDK 的超时与重试，并且不自建通用重试框架。当前 openai 客户端已经按状态码和连接错误决定是否重试，次数由 `max_retries` 控制。自己再包一层会把同一次失败重试两次，测试也要分清是哪一层在试。

## 14. 约 30 秒的口述

聊天模型由 `build_chat_model` 按配置构造，返回 `ChatOpenAI`，类型看成 `BaseChatModel`。模型名、地址、密钥、超时和重试都从 `Settings` 传入，构造客户端时不发请求。重试交给 openai SDK，默认 2 次，配置成 0 就真的不重试。聊天 Prompt 渲染成系统消息加用户消息，问题原文放在用户消息里，花括号不会被再次解析。用量来自 `AIMessage.usage_metadata`：有就抄两个 Token 数，没有就返回 `None`，不能把缺失写成 0。

## 15. 练习

不看 `chat_model.py` 和 `prompts.py`，先说出结果，再在解释器里核对。解释器要能导入 `minirag`。不要打印真实密钥，也不要调用 `invoke`。做完后不要把试验代码留在仓库里。

1. `Settings` 的 `max_retries` 是 0、`timeout` 是 12.5。`build_chat_model` 之后，`model.max_retries` 和 `model.root_client.max_retries` 各是多少？如果工厂忘了传 `max_retries`，这两个值会一样吗？
2. `render_chat_prompt("  {question}  ")` 的用户消息内容是什么？系统消息里会出现这段文字吗？
3. 一条 `AIMessage` 的 `usage_metadata` 是 `input_tokens=0`、`output_tokens=0`、`total_tokens=0`。`usage_from_ai_message` 应该返回 `None`，还是一个 Token 为 0 的 `Usage`？

## 16. 代码作者说明

S0-04 的测试、`src/minirag/llm/` 下的三个文件、`docs/TASKS.md` 中本任务的状态与结果，以及本文，都由 AI 在开发者明确要求实施 S0-04 后编写。开发者尚未手写这些代码。S0-01、S0-02、S0-03 的状态仍是 `review`。`config.py` 里的 `AliasChoices` 注释是开发过程中已有的笔记，本任务没有改它的措辞。

## 复跑

2026-10-20，第 1 至 16 节和 `docs/TASKS.md` 写入后，用同一解释器重跑。`-m live` 与 `-m integration` 的输出里没有未知标记错误。退出码 5 表示 48 个测试都被取消选择，不是标记未注册，也不能写成“测试通过”。

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/unit/test_chat_model.py tests/unit/test_prompts.py -q` | 14 passed in 5.10s | 0 |
| `python -m pytest -q` | 48 passed in 4.90s | 0 |
| `python -m pytest -m live -q` | 48 deselected in 3.28s，无未知标记错误 | 5 |
| `python -m pytest -m integration -q` | 48 deselected in 3.26s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 18 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 6 source files | 0 |

默认 pytest 的通过数量与实现刚完成时一致，仍是 48。格式检查从 17 个文件变为 18 个，因为多了本学习文档。本节是在上述命令之后追加的。追加本节之后又跑了一次 `ruff check .` 和 `ruff format --check .`，结果仍是 All checks passed、18 files already formatted，退出码都是 0。
