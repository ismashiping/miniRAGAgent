# S0-08 CLI `ask` 与依赖组装

## 1. 本次解决的问题

S0-07 之后，问答只能在 Python 里调用 `ask`。调用方要自己构造 `Settings`、`ChatOpenAI` 和 `AppContext`。命令行还不能问一句“你好”。

本任务补上两层：

- `bootstrap.build_app_context(settings)` 用已有配置创建 S0 的 `AppContext`：同一份 `settings`，加上 `build_chat_model` 造出的聊天模型。构造过程不调用模型，也不连接网络。
- `bootstrap.load_app_context()` 从环境变量和当前目录的 `.env` 读取 `Settings`，再调用上面的函数。这是 CLI 的默认组装函数。
- `cli.main(["ask", "你好"])` 解析参数，调用可替换的组装函数，再调用已经写好的 `ask`。文本模式把 `answer` 打到标准输出并返回 0。`--json` 打出完整 `AskResponse`。`status=error` 返回 1。
- `python -m minirag` 进入 `__main__.py`，把 `main()` 的返回值交给解释器。

没有实现 `ingest`、`eval`、`memory`，也没有 `open_app_context`。那些是后面的子命令和组装阶段。

## 2. 为什么需要它

SPEC 4.10 要求 S0 结束时能运行 `python -m minirag ask "<问题>"`。A-S0-7 要求真实模型下这条命令有回答，且日志里不出现 API Key。

ARCHITECTURE 把 CLI 放在传输层：只做参数、退出码和输出。生产依赖只在 `bootstrap` 创建。决策 30 写明 CLI、评估和 FastAPI 共用这一处，不使用模块级单例。如果 `cli.py` 直接 `ChatOpenAI(...)`，测试要么访问网络，要么在命令行里复制一套 Fake 组装；以后的 HTTP 入口还会再写一遍。

传输层保持薄，还有一个直接原因：非法问题已经由 `ask` 收成 `invalid_request`。CLI 再校验一次，就会把同一条规则写成两份，空白问题也会在进 `ask` 之前变成 argparse 或 `ValidationError` 的堆栈。

## 3. 修改前的执行流程

修改前没有 `bootstrap.py`、`cli.py` 和 `__main__.py`。`AppContext` 只在测试和图里手工构造。`build_chat_model` 已经能按 `Settings` 创建 `ChatOpenAI`，但没有任何进程入口调用它。

因此：

- `python -m minirag` 没有模块可运行。
- 测试要验证“命令行输出回答”，只能调用 `ask`，看不到退出码和标准输出。
- 配置缺失时没有一条给命令行用的固定说明。

`service.ask` 的行为没有改。成功仍是 `answered` / `chat`。失败仍是错误响应，不是抛给 CLI 的异常。

## 4. 涉及的文件、类和调用关系

| 文件 | 职责 |
|---|---|
| `src/minirag/bootstrap.py` | `build_app_context`、`load_app_context`。S0 只组装配置和聊天模型 |
| `src/minirag/cli.py` | `main`：解析 `ask`、调用工厂、写标准输出、映射退出码 |
| `src/minirag/__main__.py` | `python -m minirag` 时 `sys.exit(main())` |
| `tests/unit/test_bootstrap.py` | 组装结果和“构造时不连网” |
| `tests/unit/test_cli.py` | Fake 依赖下的输出、退出码、用法错误、日志 handler 会卸下 |
| `tests/live/test_live_ask.py` | 有真实配置时跑子进程；没有配置就跳过 |

调用关系：

```
python -m minirag
  -> __main__.main()
    -> cli.main()
      -> argparse
      -> context_factory()          # 默认是 load_app_context
        -> Settings()
        -> build_app_context(settings)
          -> build_chat_model(settings)
          -> AppContext
      -> ask({"question": question}, context)
      -> stdout 写 answer 或 JSON
      -> 返回 0 或 1
```

`cli.py` 不导入 `build_chat_model`，也不导入 `Settings`。测试把 `context_factory` 换成返回 Fake `AppContext` 的函数后，`build_chat_model` 不会被调用。

## 5. 相关原理

**传输层和业务层。** 参数来自进程，响应要变成退出码和字节流，这是传输层的事。问题长度、`top_k`、模型超时该变成哪个错误码，已经在 `ask` 里决定。CLI 只看 `AskResponse.status`。这样同一份业务规则以后可以原样接到 FastAPI：路由函数也是解析请求、取 `bootstrap` 准备好的上下文、调用 `aask`、把响应写回去。

**依赖注入用工厂，不用全局模型。** `main` 的 `context_factory` 是关键字参数，类型是 `Callable[[], AppContext]`，默认 `load_app_context`。工厂无参，是因为“读环境”也属于组装，不应该先在 CLI 里 `Settings()` 再塞给工厂。测试因此不必准备密钥。生产路径每次命令调用一次工厂，不把模型放进模块级变量，所以测试之间不会共用一个客户端。

**构造模型和调用模型不是一件事。** `ChatOpenAI` 在 `__init__` 里创建 httpx 客户端，但不会对 `base_url` 做 DNS 或 TCP。已有的 `test_chat_model` 用封住 `socket.create_connection`、`socket.socket.connect` 和 `socket.getaddrinfo` 证明了这一点。`build_app_context` 的测试复用同一做法。网络发生在以后的 `ainvoke`，那已经是 `ask` 的事。

**退出码是给进程看的，响应体是给人看的。** `0` 表示 `status` 不是 `error`。`1` 表示问答失败，或配置无法构造。argparse 对缺少子命令、未知命令、缺少问题直接 `SystemExit(2)`，此时还没读配置。`main` 不把 `SystemExit` 改成返回值，所以用法错误和业务失败的码不同。脚本可以用退出码分支，`--json` 时标准输出仍是一整份 JSON。

**标准输出和标准错误分开。** 文本模式只 `print(response.answer)`。JSON 模式 `model_dump_json(ensure_ascii=False)`，中文保持原文。错误响应的 `answer` 已经是固定短句，所以失败时也写在标准输出，不把 JSON 拆到标准错误。项目 INFO 日志走标准错误，避免和被管道接走的回答混在一起。

**日志 handler 是这次命令临时加上的。** `configure_logging` 只给现有 handler 加 `request_id` 过滤器，自己不创建 handler。不加工具的话，CLI 进程的 INFO 日志不会出现，A-S0-7 的“看日志里有没有密钥”就没有日志可看。`_cli_logging` 给名为 `minirag` 的 logger 加一个 `StreamHandler(sys.stderr)`，级别设为 INFO，离开 `with` 时卸下 handler 并恢复原级别。不调用 `StreamHandler.close()`，因为它会关掉所持有的流，而那个流是 `sys.stderr`。

**只捕获 `ValidationError`。** 缺配置是用户能处理的情况，打印固定句子，不打印 `str(exc)`。工厂抛出的 `RuntimeError` 继续向外抛。若这里 `except Exception`，编程错误会变成退出码 1，堆栈消失。`ask` 已经把模型故障收成响应，正常路径不会把 `APIConnectionError` 抛到 CLI。

## 6. 关键代码的执行顺序

`main(["ask", "你好"])`：

1. `_build_parser().parse_args`。子命令必须是 `ask`，后面是一个问题字符串。`--json` 可在问题前或问题后。
2. 进入 `_cli_logging`。之后 `minirag.*` 的 INFO 写到当前的 `sys.stderr`。
3. 调用 `context_factory()`。默认实现是 `load_app_context`：`Settings()` 再 `build_app_context`。`Settings()` 抛 `ValidationError` 时，标准错误打印“配置无效或缺少必填项。请设置 MINIRAG_CHAT_MODEL、MINIRAG_BASE_URL 和 MINIRAG_API_KEY。”，返回 1。标准输出为空。
4. `ask({"question": question}, context)`。问题原样传入，包括首尾空白。去掉空白、拒绝空问题，都在 `AskRequest` 里。
5. `_write_response`。然后 `status == "error"` 返回 1，否则返回 0。
6. 离开 `with`，handler 和 logger 级别恢复。

`python -m minirag` 不把 `sys.argv` 切好再传入。`main()` 的 `argv is None` 时，argparse 自己读 `sys.argv[1:]`。

`build_app_context` 只有两步：`build_chat_model(settings)`，再 `AppContext(settings=settings, chat_model=...)`。`settings` 是同一个对象，不是重新 `Settings()` 出来的第二份。

## 7. 输入、输出、状态变化和异常

| 调用 | 标准输出 | 标准错误 | 退出码 |
|---|---|---|---|
| `main(["ask", "你好"])`，工厂返回 Fake | 回答文本一行 | 含“开始问答”“问答完成”，不含回答正文，不含测试密钥 | 0 |
| `main(["ask", "  你好  "])` | 同样是模型回答。空白由 `ask` 去掉 | 同上 | 0 |
| `main(["ask", "你好", "--json"])` | 一行 JSON，字段覆盖整个 `AskResponse`，中文不转义 | 日志，不含密钥 | 0 |
| `main(["ask", "   "])` | `请求参数不合法。` | 无堆栈、无密钥。Fake 的 `i` 仍为 0 | 1 |
| `main(["ask", "--json", "   "])` | JSON：`status=error`，`intent=null`，`error.code=invalid_request` | 无堆栈 | 1 |
| Fake 抛出带密钥的 `APIConnectionError` | `模型暂时不可用，请稍后重试。` | 无密钥、无堆栈。模型调用 1 次 | 1 |
| 空环境且工作目录没有 `.env`，不注入工厂 | 空 | 只有那句固定配置说明，不含故意放进环境的密钥 | 1 |
| `main([])` 或 `main(["ingest", "docs"])` | argparse 的用法信息 | 用法信息在标准错误 | `SystemExit(2)`，不是返回值 |
| 工厂抛 `RuntimeError` | 不把异常收成退出码 | — | 异常继续抛出 |

JSON 成功时还能看到 `intent=chat`、`usage.model` 等于配置里的模型名、Token 为 Fake 消息上的 4 和 6、`latency_ms >= 0`、`error is null`。这些字段都来自 `ask`，CLI 没有重算。

`load_app_context` 在临时目录和显式环境变量下返回的 `ChatOpenAI.model_name`、`request_timeout`、`max_retries` 与环境一致。`repr(context)` 不含测试密钥。

进程没有新的全局模型。命令结束后，`logging.getLogger("minirag")` 的 handler 列表和级别与调用前相同。

## 8. 为什么采用当前方案

**默认工厂放在 `bootstrap`，不放在 `cli.py`。** ARCHITECTURE 的组装入口负责读配置和创建模型。CLI 若自己 `Settings()` 再 `build_chat_model`，传输层就含了组装。`build_app_context(settings)` 仍是可单测的纯函数；`load_app_context()` 只是“无参的生产工厂”，给 `main` 的默认参数用。测试替换的是这个无参工厂，不是去猴子补丁 `Settings`。

**错误响应保持在标准输出。** 若文本模式的失败改打到标准错误，`--json` 就得特殊处理，否则管道无法同时拿到成功和失败的 JSON。退出码已经表达成败。配置错误没有 `AskResponse` 可打印，所以那一句固定说明在标准错误，标准输出留空。

**不增加 `--session-id` 和 `--top-k`。** 本任务的验收只要求问题和 `--json`。这两个字段在 `AskRequest` 里已有默认行为。现在加上参数，CLI 测试和帮助文本都会扩到下一阶段还没要求的接口。

**用法错误用 argparse 的 2，不自己造解析器。** `add_subparsers(..., required=True)` 在 Python 3.10 可用。未知命令 `ingest` 在解析阶段失败，避免写一个“尚未实现”的空子命令让人以为入库已经存在。

**`Settings()` 旁的 `type: ignore[call-arg]`。** mypy 没启用 Pydantic 插件，把 `chat_model`、`base_url`、`api_key` 看成必填构造参数，不理解它们来自环境变量。运行时这行就是 `Settings()`。忽略的是这一处调用，不是整个文件。

**真实服务测试用子进程，而不是再调一次 `main`。** A-S0-7 的对象是 `python -m minirag ask "你好"`。子进程才会走到 `__main__`。项目默认不安装进环境，所以测试把仓库的 `src` 放进 `PYTHONPATH`，工作目录仍是仓库根，`.env` 还在 `Settings` 的默认位置。另设 `PYTHONIOENCODING=utf-8`，避免 Windows 控制台代码页把捕获到的中文弄乱。没有这三个配置时 `pytest.skip`，跳过不是通过。

## 9. 测试以及各自验证的行为

`tests/unit/test_bootstrap.py` 2 个测试。套接字的连接和 DNS 被换成会失败的函数。

| 测试 | 验证 |
|---|---|
| `test_build_app_context_binds_settings_and_chat_model_without_network` | 返回的 `settings` 是传入的同一个对象；模型是 `ChatOpenAI`，名字、地址、超时 12.5、重试 0 与配置一致；`repr` 不含测试密钥；构造期间没有连网 |
| `test_load_app_context_reads_environment_without_network` | 在空目录里只靠环境变量组装。模型名、超时 9、重试 1 来自环境。不读取开发者自己的 `.env` |

`tests/unit/test_cli.py` 12 个测试（含一个两组参数）。成功路径把 `build_chat_model` 换成会抛 `AssertionError` 的函数，证明注入工厂后 CLI 不创建模型。Fake 列表模型放两条相同回复：只有一条时，调用一次后 `i` 回到 0，看不出有没有调用过。

| 测试 | 验证 |
|---|---|
| `test_main_ask_prints_answer_and_returns_zero` | 标准输出只有回答。标准错误有两条阶段日志，没有回答正文，也没有密钥。`i == 1`。返回 0 |
| `test_main_strips_question_via_ask` | `"  你好  "` 仍成功。CLI 没有自己 `strip`，是 `ask` 在校验时去掉的 |
| `test_main_json_prints_complete_ask_response` | JSON 含全部 10 个响应字段，能通过 `AskResponse.model_validate`。用量是 4 和 6。中文回答出现在原文里 |
| `test_main_error_status_returns_one_without_calling_model` | 空白问题返回 1，输出固定短句，`i == 0`，没有堆栈和密钥 |
| `test_main_json_error_returns_one_and_full_response` | `--json` 放在问题前面也同样解析。错误 JSON 的 `intent` 为 `null`，`code` 为 `invalid_request` |
| `test_main_provider_failure_returns_safe_text` | 异常消息里故意放了测试密钥。标准输出是 `llm_unavailable` 的固定句子。两边都没有密钥和堆栈。调用次数为 1 |
| `test_main_missing_config_returns_one_without_network` | 不注入工厂。临时目录、清空相关环境变量，只留下一把测试密钥。返回 1，标准错误恰好是固定说明，不连网 |
| `test_main_does_not_swallow_unexpected_factory_errors` | 工厂的 `RuntimeError` 原样抛出 |
| `test_main_removes_cli_log_handler` | 调用前后 `minirag` logger 的 handler 和级别相同 |
| `test_main_usage_error_exits_two` | `[]` 和 `["ingest", "docs"]` 都是 `SystemExit(2)` |
| `test_module_entry_exits_with_cli_status` | `runpy.run_module("minirag", run_name="__main__")` 使用当时的 `cli.main`。替身返回 3，进程入口以 3 退出，且不会去组装真实依赖 |

`tests/live/test_live_ask.py` 只有 `test_live_ask_returns_answer_without_api_key_in_output`。它先 `Settings(_env_file=仓库/.env)`。校验失败就跳过。成功时用当前解释器跑 `python -m minirag ask 你好`，断言退出码 0、标准输出非空、标准错误含两条阶段日志，且密钥不在这两条流里。比较失败时抛出的句子是“命令输出中出现了 API Key”，断言消息本身不含密钥。

## 10. 实际运行的命令和结果

解释器：`C:\Users\11091\.conda\envs\medical-agent\python.exe`。日期：2026-10-22。

红灯：三个测试文件 `py_compile` 通过。`pytest tests/unit/test_bootstrap.py tests/unit/test_cli.py -q` 在收集阶段失败，退出码 2，2 errors in 4.26s。`test_bootstrap.py` 为 `ModuleNotFoundError: No module named 'minirag.bootstrap'`。`test_cli.py` 为 `ModuleNotFoundError: No module named 'minirag.cli'`。断言没有执行。这是模块还不存在，不是测试写错。

实现并格式化之后，目标测试 14 passed in 4.45s，退出码 0。当时默认 `pytest -q` 是 125 passed, 1 deselected, 1 warning in 5.33s。那条警告是 `RuntimeWarning: 'minirag.__main__' found in sys.modules ...`：live 测试在收集时导入了 `__main__`，随后单元测试用 `runpy` 再执行它。已经去掉 live 测试里的那次导入。去掉之后默认 pytest 为 125 passed, 1 deselected in 4.91s，退出码 0，没有警告。

`pytest -m live tests/live/test_live_ask.py -rs -q` 为 1 skipped in 0.11s，退出码 0。跳过原因是未配置 `MINIRAG_CHAT_MODEL`、`MINIRAG_BASE_URL`、`MINIRAG_API_KEY`。当时 `Test-Path .env` 为 false，这三个环境变量在进程里也都未设置。A-S0-7 未验证。没有调用真实模型。退出码 0 只表示 pytest 把跳过当成非失败，不能写成真实调用通过。

`pytest -m integration -q` 为 126 deselected in 3.52s，退出码 5。被取消选择的是 125 个默认测试加 1 个 live 测试。输出里没有未知标记错误。

`ruff check .` 通过。`mypy src` 为 Success: no issues found in 18 source files，退出码 0。18 比 S0-07 的 15 多了 `bootstrap.py`、`cli.py` 和 `__main__.py`。

`ruff format --check .` 退出码 1，1 file would be reformatted。该文件是 `docs/ARCHITECTURE.md`，属于开始本任务前已经存在的 D-04 工作区改动。本任务没有修改它，也没有运行会改写它的 `ruff format`。因此不能把全仓库格式检查写成通过。本任务自己的 Python 文件在单独的 `ruff format --check` 里是已格式化。

未安装新包。未把 S0-01 至 S0-07 标为 `done`。学习文档写入后的复跑见第 17 节。

## 11. 容易混淆的概念

- `main` 返回 0 或 1。用法错误是 `SystemExit(2)`，调用方看到的是异常，不是整数 2。`__main__` 里的 `sys.exit(main())` 只有 `main` 正常返回时才会用到那个整数。
- 注入的 `context_factory` 不会收到 `Settings`。它自己准备整个 `AppContext`。默认工厂才读环境。
- `build_app_context` 不读 `.env`。`load_app_context` 才读。单测前者时传入 `_env_file=None` 的 `Settings`，避免机器上的文件混进来。
- 文本模式的失败也在标准输出。看退出码，不能只看“有没有打印文字”。
- Fake 模型的 `i == 0` 单独不能证明没调用过。本任务的 CLI 测试因此准备了两条回复。
- 关闭日志 handler 不等于 `handler.close()`。后者会关掉 `sys.stderr`。
- pytest 把 live 测试跳过显示为退出码 0。SPEC 要求这种阻塞如实写成未验证。
- 全仓库 `pytest -m live` 现在会选中 1 个测试。以前没有任何 live 测试时，这条命令是全部取消选择、退出码 5。有了这个文件之后，没配置时是 1 skipped、退出码 0。

## 12. 局限与后续

- A-S0-7 没有用真实模型跑过。配置齐了以后应再跑 `pytest -m live tests/live/test_live_ask.py`，并检查标准错误里的项目日志。
- CLI 的日志级别是 `minirag` 的 INFO。httpx 和 openai 的 DEBUG 请求日志没有打开。那些日志若在 DEBUG 下打印 `Authorization`，当前测试看不到。生产命令本身也不打开 DEBUG。
- 工厂抛出的任何 `ValidationError` 都显示同一句配置说明。S0 的默认工厂只会在 `Settings` 上抛出它。以后若组装阶段还有别的校验错误，不应继续共用这句文案。
- `IndexIncompatibleError` 和 Qdrant 启动失败还没有。SPEC 里 CLI 对它们也要非零退出，那是 S2-08 和 S1-08 的事。
- 没有 `--session-id`、`--top-k`，也没有 `ingest`。
- 项目没有安装进环境。从仓库根运行需要 `PYTHONPATH=src`，或者先把 `src` 放到解释器能导入的位置。这是 SPEC 第 15 条“默认不安装”的结果，不是 `__main__.py` 少写了一行。
- 全仓库 `ruff format --check .` 仍被既有的 `docs/ARCHITECTURE.md` 挡住。
- 没有把 S0-07 标成 `done`。开始本任务时它仍是 `review`；这次是开发者明确要求实施 S0-08。

## 13. 面试问题

**问：为什么 CLI 不直接创建 `ChatOpenAI`？**  
答：创建模型要读配置、放入 `AppContext`，评估和以后的 FastAPI 也需要同一份结果。放在 `bootstrap` 后，CLI 只解析参数并调用 `ask`。测试用 `context_factory` 注入 Fake 模型，默认测试不访问网络，也不需要 API Key。`build_app_context` 本身还可以单独断言：传入的 `Settings` 原样返回，并且构造时没有连接套接字。

**问：`status=error` 为什么还把文字打到标准输出，退出码却是 1？**  
答：输出是响应体，退出码是给 shell 的。`--json` 时成功和失败都应该是一份完整 `AskResponse`，调用方只解析标准输出，再用退出码判断要不要当成失败。配置缺失没有响应体，固定说明才写到标准错误，避免和 JSON 混在一起。用法错误仍然是 argparse 的 2，因为它发生在业务调用之前。

**问：怎样确认日志里没有 API Key，又没有把密钥写进测试失败信息？**  
答：业务日志不记录 `get_secret_value()`，供应商异常的 `str(exc)` 也不进入 `ask` 的日志和响应。CLI 对配置错误打印固定句子，不打印 `ValidationError`。测试把密钥放进异常消息或环境变量，然后检查标准输出和标准错误。live 测试若发现密钥，只抛出“命令输出中出现了 API Key”，不把密钥拼进断言文本。另外，`StreamHandler.close()` 不能用来收尾，否则会关掉标准错误。

## 14. 约 30 秒的口述

命令行是传输层。`main` 用 argparse 解析 `ask` 和问题，通过可替换的工厂拿到 `AppContext`。默认工厂在 `bootstrap` 里读配置并构造 `ChatOpenAI`，这一步不访问网络。然后调用已经写好的 `ask`。标准输出是回答或完整 JSON，项目日志在标准错误。`status=error` 返回 1，参数用法错误是 2。非法问题和模型故障都不在 CLI 里再捕获一遍，所以测试注入 Fake 模型就能离线验证退出码，也不会把 API Key 打出来。

## 15. 练习

不看 `cli.py` 和 `bootstrap.py`，先说出结果，再在解释器里核对。使用项目解释器，让它能导入 `minirag`。只用 Fake 或空配置，不要调用真实接口，也不要打印密钥。做完后不要把试验代码留在仓库里。

1. `main(["ask", "  你好  "], context_factory=返回 Fake 的函数)` 的退出码是多少？问题两侧的空格是谁去掉的？若工厂没有被调用，而是 CLI 自己 `build_chat_model`，哪个测试会先失败？
2. `main(["ask", "   "], context_factory=...)` 的退出码、标准输出，以及 Fake 模型的 `i` 分别是什么？把参数改成 `["ingest", "docs"]` 后，还能用返回值 `== 1` 判断吗？
3. 在一个没有 `.env` 的空目录里清空 `MINIRAG_*` 后调用 `main(["ask", "你好"])`。标准输出和标准错误各有什么？若改成 `except Exception` 再返回 1，第 2 题里的工厂 `RuntimeError` 还会不会冒出来？

## 16. 代码作者说明

S0-08 的测试、`bootstrap.py`、`cli.py`、`__main__.py`、`docs/TASKS.md` 里本任务的状态与结果，以及本文，都由 AI 在开发者明确要求实施 S0-08 后编写。开发者尚未手写这些代码。开始时 S0-07 仍是 `review`；这次实施请求被当作可以开始本任务的确认。S0-01 至 S0-07 没有改成 `done`。S0-07 已有的源码、测试和学习文档没有被本任务改写。`docs/ARCHITECTURE.md` 和 `docs/SPEC.md` 里已有的 D-04 改动也没有被格式化或回退。

## 17. 复跑

2026-10-22，第 1 至 16 节和 `docs/TASKS.md` 写入后，用同一解释器重跑。代码与第 10 节去掉 `RuntimeWarning` 之后相同，新增的是本文和任务状态。`-m integration` 的输出里没有未知标记错误。退出码 5 表示 126 个测试都被取消选择。`ruff format --check .` 的 41 个已格式化文件包含本文；失败的仍只有开始本任务前已修改的 `docs/ARCHITECTURE.md`。

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/unit/test_bootstrap.py tests/unit/test_cli.py -q` | 14 passed in 6.04s | 0 |
| `python -m pytest -q` | 125 passed, 1 deselected in 5.61s，无警告 | 0 |
| `python -m pytest -m live tests/live/test_live_ask.py -rs -q` | 1 skipped in 0.12s。未配置三个 `MINIRAG_*` 变量，A-S0-7 未验证 | 0 |
| `python -m pytest -m integration -q` | 126 deselected in 3.62s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 1 file would be reformatted（`docs/ARCHITECTURE.md`），41 files already formatted | 1 |
| `python -m mypy src` | Success: no issues found in 18 source files | 0 |

本节表格补上之后又执行了一次检查。`ruff check .` 仍是 All checks passed，退出码 0。`ruff format --check docs/learning/S0-08-cli.md` 为 1 file already formatted，退出码 0。`ruff format --check .` 仍是 1 file would be reformatted（`docs/ARCHITECTURE.md`），41 files already formatted，退出码 1。这次只改了 Markdown，没有再跑 pytest 和 mypy。
