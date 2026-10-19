# MiniRAG Agent — Tasks

**依据：** `docs/SPEC.md`（Draft v2）、`docs/ARCHITECTURE.md`（初版）  
**规则：** 任务字段、优先级、状态、学习文档要求见 SPEC 第 8 章；TDD 流程见 SPEC 第 6 章；协作顺序见 SPEC 第 9 章。

---

## 1. 规划原则

- 一次只执行一个任务；完成后进入 `review`，开发者复盘确认后才标记 `done` 并开始下一项。
- 每个开发任务：先写测试并看到红灯，再写最小实现；生成 `docs/learning/<任务编号>-<短名>.md`。
- 滚动细化：当前阶段任务填全字段；后续阶段只列大纲，进入该阶段前补全。
- 不为覆盖技术名词而新增任务；新增或拆分任务需同步更新 SPEC 第 7 章。

## 2. 当前状态（2026-10-20）

- S0-01、S0-02、S0-03、S0-04 仍为 `review`，尚未标记 `done`。S0-05 最小图已写入，状态 `review`；其余开发任务仍为 `todo`。仓库已有覆盖到 S0-04 的基线提交；本任务未创建新提交。
- D-01 至 D-03 已由开发者确认，状态 `done`。
- 环境实测：Python 3.10.21；langchain-core 1.6.12、langgraph 1.2.11、langchain-openai 1.6.2、pytest 9.1.1、pytest-asyncio 1.4.0、ruff、mypy 已安装；`pip check` 无冲突。
- 已知缺口：S6-05 需要 `langgraph-checkpoint-postgres` 与 psycopg v3（未安装，届时申请）；S4-06 与所有 `live` 测试需要模型、Embedding、重排服务的配置（尚未提供）。

## 3. 优先级与状态

| 优先级 | 含义 |
|---|---|
| P0 | 阶段验收场景直接依赖 |
| P1 | 阶段内重要但可后置的质量项 |
| P2 | 可选实验或对比学习 |

状态：`todo` → `in_progress` → `review` → `done`；外部阻塞时为 `blocked`。

## 4. 文档任务

| 编号 | 内容 | 状态 | 说明 |
|---|---|---|---|
| D-01 | SPEC 重构为 Draft v2 | done | 2026-10-20 开发者确认可作为基线 |
| D-02 | ARCHITECTURE 初版 | done | 2026-10-20 开发者确认可作为基线 |
| D-03 | TASKS 初版（本文） | done | 2026-10-20 开发者确认可作为基线 |

文档任务不要求学习文档（SPEC 8.3）。

## 5. 依赖总览

```
D-01..D-03 → S0-01 → S0-02 → S0-03 → S0-04 → S0-05 → S0-06 → S0-07 → S0-08   （S0 完成）
S0 → S1-01 → S1-02 → S1-03 → S1-04 → S1-05                                   （S1 完成）
S1 → S2-01 → S2-02 → S2-03 → S2-04 → S2-05 → S2-06 → S2-07                   （S2 完成）
S2 → S3-01 → S3-02 → S3-03 → S3-04                                           （S3 完成）
S3 → S4-01 → S4-02 → S4-03 → S4-04 ；S4-05（人工，可与 S4-01 起并行准备）→ S4-06  （V0.1）
V0.1 → S5-01 → S5-02 → S5-03 → S5-04 ；S5-02 → S5-05 → S5-06 → S5-07 ；S5-08（V0.2）
V0.2 → S6-01 → S6-02 → S6-03 → S6-04 → S6-05 ；S6-01 → S7-01 → S7-02 → S7-03 ；S7-04 ；S7-05（V1.0）
```

---

## 6. S0 工程骨架与最小 LangChain + LangGraph 闭环（V0.1）

阶段完成条件：A-S0-1 至 A-S0-6 通过并记录证据；A-S0-7 在提供模型配置后验证，未提供时标记为未验证，不阻塞 S1。

### S0-01 项目骨架与工具链

- **优先级 / 状态：** P0 / review
- **学习目标：** 理解 `pyproject.toml`、`src/` 布局、pytest 配置与测试标记、Ruff 与 mypy 的分工。
- **要解决的问题：** 仓库没有可运行的 Python 包和测试配置，后续任务无法执行 TDD。
- **前置任务：** D-01、D-02、D-03 确认。
- **需要阅读：** 无源码（新建）。阅读 SPEC 3.1、3.4、6.4；ARCHITECTURE 2、9。
- **预期修改范围：** `pyproject.toml`、`.gitignore`、`src/minirag/__init__.py`、`tests/unit/test_smoke.py`。
- **测试先行：** 编写 `test_package_exposes_version`（导入 `minirag` 并断言 `__version__`）。预期红灯：`ModuleNotFoundError`（新模块首个测试，SPEC 6.1 允许）。
- **验收标准：**
  - 默认 `pytest` 通过；`pytest -m live` 与 `pytest -m integration` 不报未知标记错误。
  - `ruff check .`、`ruff format --check .`、`mypy src` 通过。
  - 依赖范围按 SPEC 3.4 声明，未安装任何新包，未把项目安装进环境。
  - `.gitignore` 覆盖 `.env`、`__pycache__`、`.pytest_cache`、`data/index/`。
- **覆盖场景：** A-S0-6（部分）。
- **测试命令：** SPEC 6.4 中的 pytest、ruff、mypy 命令。
- **实际结果：** 2026-10-20，解释器 `C:\Users\11091\.conda\envs\medical-agent\python.exe`。红灯：仅有测试时 `pytest tests/unit/test_smoke.py -q` 在收集阶段报 `ModuleNotFoundError`，1 error，退出码 2。实现后：`pytest` 1 passed，退出码 0；`pytest -m live` 与 `pytest -m integration` 均为 1 deselected、退出码 5，无未知标记错误；`ruff check .` 与 `ruff format --check .` 退出码 0；`mypy src` 为 1 source file、no issues，退出码 0。未安装新包；普通进程中 `find_spec("minirag")` 为 `None`。详见学习文档。
- **学习文档：** `docs/learning/S0-01-project-skeleton.md`
- **完成后应能：** 解释 `pythonpath` 配置为何能让测试找到 `src/` 中的包；解释为什么默认排除 `live` 测试；独立新增一个测试标记。
- **面试知识点：** src 布局与平铺布局的区别；依赖版本范围的写法与风险；Ruff 和 mypy 分别能发现什么问题。

### S0-02 问答契约

- **优先级 / 状态：** P0 / review
- **学习目标：** 用 Pydantic v2 定义契约：字段约束、默认值、`field_validator`、`model_validator`。
- **要解决的问题：** CLI、图、HTTP 需要共用一组请求与响应结构（SPEC 4.10）。
- **前置任务：** S0-01。
- **需要阅读：** `pyproject.toml`、`src/minirag/__init__.py`；SPEC 4.10。
- **预期修改范围：** `src/minirag/contracts.py`、`tests/unit/test_contracts.py`。
- **测试先行：**
  - `question` 去除首尾空白；空白串、2001 字符被拒绝；恰好 2000 字符通过。
  - `top_k` 默认 5；0 与 21 被拒绝。
  - `status=error` 时必须有 `error`；其他状态下 `error` 必须为 `None`。
  - `citations`、`degraded` 默认为空列表；`usage` 可为 `None`；`Citation` 的四个分数默认为 `None`。
  - 预期红灯：首个测试 `ImportError`，其余为断言或 `ValidationError` 未抛出。
- **验收标准：** 以上测试通过；`IngestReport` 不在本任务定义（S1-05）；回归检查通过。
- **覆盖场景：** A-S0-2（Schema 部分）。
- **测试命令：** `& $py -m pytest tests/unit/test_contracts.py`，再运行全部检查。
- **实际结果：** 2026-10-20，解释器 `C:\Users\11091\.conda\envs\medical-agent\python.exe`。红灯：只有测试、尚无 `contracts.py` 时，`pytest tests/unit/test_contracts.py -q` 在收集阶段报 `ModuleNotFoundError: No module named 'minirag.contracts'`（外层为 `ImportError`），1 error，退出码 2。其余用例未执行到断言。实现后：该文件 13 passed，退出码 0；默认 `pytest` 14 passed（含 S0-01 冒烟测试），退出码 0；`pytest -m live` 与 `pytest -m integration` 均为 14 deselected、退出码 5，无未知标记错误。`ruff check .` 与 `ruff format --check .` 退出码 0；`mypy src` 为 2 source files、no issues，退出码 0。未定义 `IngestReport`，未安装新包。
- **学习文档：** `docs/learning/S0-02-contracts.md`
- **完成后应能：** 说清字段级校验与模型级校验的区别；独立新增一个带约束的字段并写测试。
- **面试知识点：** Pydantic v2 校验顺序；为什么用一套 Schema 服务多个入口；`None` 与 `0` 在用量字段中的语义差异。

### S0-03 配置管理

- **优先级 / 状态：** P0 / review
- **学习目标：** 用 pydantic-settings 从环境变量加载配置；`SecretStr` 防止密钥泄露。
- **要解决的问题：** 模型名、`base_url`、API Key、超时需要可配置，且不能出现在日志中。
- **前置任务：** S0-02。
- **需要阅读：** `src/minirag/contracts.py`；SPEC 5.6。
- **预期修改范围：** `src/minirag/config.py`、`.env.example`、`tests/unit/test_config.py`。
- **测试先行：**
  - 通过 `monkeypatch.setenv` 设置变量后正确加载；默认超时与重试次数符合 SPEC。
  - 缺少 API Key 时报错信息包含变量名。
  - `repr` / `str` 中不出现密钥原文。
  - 测试中禁止读取本地 `.env`，避免环境干扰。
- **验收标准：** 测试通过；`.env.example` 只含占位值；回归检查通过。
- **覆盖场景：** A-S0-3（不泄露密钥的前提）。
- **测试命令：** `& $py -m pytest tests/unit/test_config.py`，再运行全部检查。
- **实际结果：** 2026-10-20，解释器 `C:\Users\11091\.conda\envs\medical-agent\python.exe`。红灯：测试已写、尚无 `config.py` 时，`pytest tests/unit/test_config.py -q` 在收集阶段报 `ModuleNotFoundError: No module named 'minirag.config'`（外层为 `ImportError`），1 error，退出码 2。断言未执行。实现后曾有 1 failed、19 passed：缺少模型名时 `ValidationError` 回显了 API Key；补上 `hide_input_in_errors=True` 后该文件 20 passed，退出码 0。默认 `pytest` 34 passed，退出码 0。`pytest -m live` 与 `pytest -m integration` 均为 34 deselected、退出码 5，无未知标记错误。`ruff check .` 与 `ruff format --check .` 退出码 0（当时 11 files already formatted）。`mypy src` 为 3 source files、no issues，退出码 0。学习文档写入后再跑：默认 pytest 仍为 34 passed；`ruff format --check .` 变为 12 files already formatted；`-m live` 与 `-m integration` 仍为 34 deselected、退出码 5。未安装新包。超时默认 600 秒来自当前环境 openai SDK 的总超时，SPEC 未写明这个秒数。未把 S0-01、S0-02 标为 `done`。详见学习文档。
- **学习文档：** `docs/learning/S0-03-settings.md`
- **完成后应能：** 解释环境变量、`.env` 与默认值的优先级；说明 `SecretStr` 能防住和防不住什么。
- **面试知识点：** 配置与代码分离；密钥管理；测试如何隔离环境变量。

### S0-04 ChatModel 工厂与聊天 Prompt

- **优先级 / 状态：** P0 / review
- **学习目标：** 理解 `BaseChatModel` 与 Runnable 接口（`invoke` / `ainvoke`）、`ChatPromptTemplate`、`AIMessage.usage_metadata`。
- **要解决的问题：** 需要一个可替换、可测试的模型入口，并把模型返回的用量转为契约中的 `Usage`。
- **前置任务：** S0-03。
- **需要阅读：** `src/minirag/config.py`、`src/minirag/contracts.py`；SPEC 3.2、4.1。
- **预期修改范围：** `src/minirag/llm/__init__.py`、`src/minirag/llm/chat_model.py`、`src/minirag/llm/prompts.py`、`tests/unit/test_chat_model.py`、`tests/unit/test_prompts.py`。
- **测试先行：**
  - `build_chat_model(settings)` 返回的对象配置了模型名、`base_url`、超时与 `max_retries=2`，构造过程不访问网络（具体属性名在任务中对照已安装的 langchain-openai 源码确认）。
  - 聊天 Prompt 渲染后为 System + Human 两条消息，Human 内容为问题原文。
  - 带 `usage_metadata` 的 `AIMessage` 转换为 `Usage`；不带时返回 `None`。
- **验收标准：** 测试通过且全部离线；回归检查通过。
- **覆盖场景：** A-S0-4（转换部分）。
- **测试命令：** `& $py -m pytest tests/unit/test_chat_model.py tests/unit/test_prompts.py`，再运行全部检查。
- **实际结果：** 2026-10-20，解释器 `C:\Users\11091\.conda\envs\medical-agent\python.exe`。红灯：测试已写、尚无 `src/minirag/llm/` 时，`pytest tests/unit/test_chat_model.py tests/unit/test_prompts.py -q` 在收集阶段报 `ModuleNotFoundError: No module named 'minirag.llm'`（外层为 `ImportError`），2 errors，退出码 2。断言未执行。实现后该命令 14 passed，退出码 0。默认 `pytest` 48 passed，退出码 0。`pytest -m live` 与 `pytest -m integration` 均为 48 deselected、退出码 5，无未知标记错误。`ruff check .` 退出码 0。`ruff format --check .` 曾因 `config.py` 一条非本任务注释缺少空格，以及测试里一行过长调用而失败；只格式化了本任务测试文件，没有改那条注释的措辞。注释随后已带上空格，再次检查为 17 files already formatted，退出码 0。`mypy src` 为 6 source files、no issues，退出码 0。学习文档写入后再跑：目标测试 14 passed in 5.10s；默认 pytest 48 passed in 4.90s；`-m live` 48 deselected in 3.28s、退出码 5；`-m integration` 48 deselected in 3.26s、退出码 5；`ruff check .` 通过；`ruff format --check .` 为 18 files already formatted；`mypy src` 仍为 6 source files、no issues。未安装新包。未调用模型，未实现图、用量汇总或错误映射。未把 S0-01、S0-02、S0-03 标为 `done`。详见学习文档。
- **学习文档：** `docs/learning/S0-04-chat-model-and-prompt.md`
- **完成后应能：** 按调用顺序讲清 Prompt → Messages → ChatModel → AIMessage；把模型换成另一家 OpenAI 兼容服务只改配置。
- **面试知识点：** LangChain Runnable 统一接口的价值；SDK 重试与自写重试的区别；Token 用量从哪里来、为什么可能缺失。

### S0-05 LangGraph 最小图

- **优先级 / 状态：** P0 / review
- **学习目标：** 理解 `StateGraph`、`TypedDict` State、节点返回部分更新、`START` / `END`、`context_schema` 与 `Runtime` 注入、`ainvoke`。
- **要解决的问题：** `ask` 必须从 S0 起由 LangGraph 执行（SPEC 决策 13）。
- **前置任务：** S0-04。
- **需要阅读：** `src/minirag/llm/chat_model.py`、`src/minirag/llm/prompts.py`；SPEC 4.4、4.5.1；ARCHITECTURE 3、4。
- **预期修改范围：** `src/minirag/graph/__init__.py`、`graph/state.py`、`graph/context.py`、`graph/nodes/__init__.py`、`graph/nodes/chat.py`、`graph/builder.py`、`tests/unit/test_chat_node.py`、`tests/graph/test_chat_graph.py`。
- **测试先行：**
  - 节点单测：给定 State 与 Fake 模型，返回包含 `answer`、`usage_records` 的部分更新，不返回无关字段（如何在单测中构造 `Runtime` 在任务中验证）。
  - 整图测试：`build_graph()` 编译后 `ainvoke`，最终 State 的 `answer` 等于 Fake 模型输出，`usage_records` 长度为 1。
  - 预期红灯：首个测试 `ImportError`。
- **验收标准：** 测试通过；节点内部不读取全局单例；回归检查通过。
- **覆盖场景：** A-S0-5。
- **测试命令：** `& $py -m pytest tests/unit/test_chat_node.py tests/graph/test_chat_graph.py`，再运行全部检查。
- **实际结果：** 2026-10-20，解释器 `C:\Users\11091\.conda\envs\medical-agent\python.exe`。红灯：测试已写、尚无 `src/minirag/graph/` 时，`pytest tests/unit/test_chat_node.py tests/graph/test_chat_graph.py -q` 在收集阶段报 `ModuleNotFoundError: No module named 'minirag.graph'`（外层为 `ImportError`），2 errors，退出码 2。断言未执行。实现后、格式化前：该命令 12 passed in 4.00s，退出码 0；默认 `pytest` 60 passed in 7.16s，退出码 0。`ruff check .` 通过。`mypy src` 为 12 source files、no issues，退出码 0。`ruff format --check .` 因 `tests/unit/test_chat_node.py` 一处调用可收成一行而失败，1 file would be reformatted，退出码 1。只格式化了该测试文件。格式化后：目标测试 12 passed in 4.37s，退出码 0；`pytest -m live` 60 deselected in 4.08s，退出码 5；`pytest -m integration` 60 deselected in 4.00s，退出码 5；均无未知标记错误。`ruff check .` 通过。`ruff format --check .` 为 26 files already formatted，退出码 0。`mypy src` 仍为 12 source files、no issues。未安装新包。未调用真实模型，未实现 `aask`、错误映射或 Checkpointer。未把 S0-01 至 S0-04 标为 `done`。学习文档写入后再跑：目标测试 12 passed in 4.02s；默认 pytest 60 passed in 5.87s；`-m live` 60 deselected in 4.27s、退出码 5；`-m integration` 60 deselected in 4.06s、退出码 5；`ruff check .` 通过；`ruff format --check .` 为 27 files already formatted（含 Markdown）；`mypy src` 仍为 12 source files、no issues。详见学习文档。
- **学习文档：** `docs/learning/S0-05-minimal-graph.md`
- **完成后应能：** 画出 S0 图并说明 State 每一步的变化；解释 State 与 Context 的区别；独立增加一个节点。
- **面试知识点：** LangGraph 与直接调用 LLM、LCEL 链的区别；Reducer 的作用；为什么依赖不放进 State。

### S0-06 `aask` / `ask` 入口与日志关联

- **优先级 / 状态：** P0 / todo
- **学习目标：** 异步入口与同步包装（`asyncio.run`）；`contextvars` 传递 `request_id`；从最终 State 组装响应。
- **要解决的问题：** 需要统一入口生成标识、计时、调用图并返回 `AskResponse`。
- **前置任务：** S0-05。
- **需要阅读：** `src/minirag/graph/builder.py`、`src/minirag/contracts.py`；SPEC 4.10、4.8（运行时观测）。
- **预期修改范围：** `src/minirag/service.py`、`src/minirag/logging_setup.py`、`tests/graph/test_service_ask.py`。
- **测试先行：**
  - A-S0-1：Fake 模型下返回 `answered`、`intent=chat`、非空 `request_id`。
  - 传入 `session_id` 时原样返回；未传时生成。
  - `usage` 由 `usage_records` 汇总；`latency_ms` 为非负整数。
  - `caplog` 中本次请求的日志都带有同一个 `request_id`。
  - 同步 `ask` 与 `aask` 结果字段一致。
- **验收标准：** 测试通过；回归检查通过。
- **覆盖场景：** A-S0-1、A-S0-4。
- **测试命令：** `& $py -m pytest tests/graph/test_service_ask.py`，再运行全部检查。
- **实际结果：** 未执行。
- **学习文档：** `docs/learning/S0-06-ask-entry.md`
- **完成后应能：** 解释 `asyncio.run` 为什么不能在已运行的事件循环中调用；解释 `contextvars` 为何适合异步日志关联。
- **面试知识点：** 协程与事件循环；同步/异步入口设计；请求 ID 在排查问题中的作用。

### S0-07 错误映射

- **优先级 / 状态：** P0 / todo
- **学习目标：** 领域异常、异常转换（`raise ... from`）、入口统一映射错误码、响应不泄露内部信息。
- **要解决的问题：** 模型故障、非法输入和未知错误需要稳定、安全的错误响应。
- **前置任务：** S0-06。
- **需要阅读：** `src/minirag/service.py`、`src/minirag/llm/chat_model.py`；SPEC 4.7、4.10 错误码。
- **预期修改范围：** `src/minirag/errors.py`、`src/minirag/service.py`、`src/minirag/llm/chat_model.py`、`tests/unit/test_errors.py`、`tests/graph/test_service_errors.py`。
- **测试先行：**
  - A-S0-2：非法 `question` / `top_k` 返回 `invalid_request`，`intent` 为 `None`，模型调用次数为 0。
  - A-S0-3：Fake 模型抛出超时或连接类异常 → `llm_unavailable`；响应文本不含堆栈与密钥。
  - 未知异常 → `internal_error`，日志中有堆栈。
  - 哪些 SDK 异常归为 `llm_unavailable` 在任务中对照已安装的 `openai` 包确认。
- **验收标准：** 测试通过；没有 `except Exception: return None` 式的吞异常；回归检查通过。
- **覆盖场景：** A-S0-2、A-S0-3。
- **测试命令：** `& $py -m pytest tests/unit/test_errors.py tests/graph/test_service_errors.py`，再运行全部检查。
- **实际结果：** 未执行。
- **学习文档：** `docs/learning/S0-07-error-mapping.md`
- **完成后应能：** 追踪一个模型超时异常从 SDK 到响应的完整传播路径；新增一个错误码并更新测试。
- **面试知识点：** 异常分层与转换；为什么不全部捕获；错误信息的安全边界。

### S0-08 CLI `ask`

- **优先级 / 状态：** P0 / todo
- **学习目标：** `argparse` 子命令、退出码、传输层保持很薄。
- **要解决的问题：** 需要从命令行调用 `ask`（SPEC 4.10）。
- **前置任务：** S0-07。
- **需要阅读：** `src/minirag/service.py`；SPEC 4.10 入口。
- **预期修改范围：** `src/minirag/__main__.py`、`src/minirag/cli.py`、`tests/unit/test_cli.py`、`tests/live/test_live_ask.py`。
- **测试先行：**
  - `main(["ask", "你好"])` 在 Fake 依赖下输出回答文本并返回 0；`--json` 输出完整 `AskResponse`。
  - `status=error` 时返回非零退出码。
  - `live` 测试：真实配置下调用成功，捕获的日志中不含 API Key。
- **验收标准：** 离线测试通过；`live` 测试在有配置时执行，否则如实记录未验证；回归检查通过。
- **覆盖场景：** A-S0-7。
- **测试命令：** `& $py -m pytest tests/unit/test_cli.py`；`& $py -m pytest -m live tests/live/test_live_ask.py`。
- **实际结果：** 未执行。
- **学习文档：** `docs/learning/S0-08-cli.md`
- **完成后应能：** 说明 CLI 为什么不包含业务逻辑；为 CLI 增加一个参数并测试。
- **面试知识点：** 传输层与业务层分离；退出码约定；如何在不依赖网络的情况下测试 CLI。

---

## 7. 后续阶段大纲（进入阶段前补全字段）

### S1 文档入库（V0.1）

| 编号 | 优先级 | 目标 | 前置 | 场景 |
|---|---|---|---|---|
| S1-01 | P0 | 读取与清洗、`doc_id` 规范化、跳过非 UTF-8 与不支持格式 | S0 | A-S1-4 |
| S1-02 | P0 | 标题分节、段落累积、硬切分，输出 `Document` | S1-01 | A-S1-1 |
| S1-03 | P0 | Embeddings 工厂与 Fake、批量与维度检查 | S1-02 | — |
| S1-04 | P0 | JSONL + `.npy` + 清单、`index_id`、原子替换 | S1-03 | A-S1-2、A-S1-3 |
| S1-05 | P0 | `ingest`、`IngestReport`、CLI | S1-04 | A-S1-2、A-S1-4 |

### S2 混合检索（V0.1）

| 编号 | 优先级 | 目标 | 前置 | 场景 |
|---|---|---|---|---|
| S2-01 | P0 | `VectorRetriever`：余弦、Top-K、空索引 | S1 | A-S2-1 |
| S2-02 | P0 | BM25 分词 | S1 | A-S2-2 |
| S2-03 | P0 | `BM25Retriever` 打分与排序 | S2-02 | A-S2-2 |
| S2-04 | P0 | `rrf_fuse` 去重与确定性排序 | S2-01、S2-03 | A-S2-3、A-S2-5 |
| S2-05 | P0 | Reranker 接口、超时与重试、失败降级 | S2-04 | A-S2-4 |
| S2-06 | P0 | 证据阈值筛选与降级跳过 | S2-05 | A-S2-4 |
| S2-07 | P0 | 检索节点与 `degraded` Reducer | S2-06 | A-S2-4、A-S2-5 |

### S3 有据回答与拒答（V0.1）

| 编号 | 优先级 | 目标 | 前置 | 场景 |
|---|---|---|---|---|
| S3-01 | P0 | 证据 Prompt 与编号 | S2 | — |
| S3-02 | P0 | 引用解析、越界丢弃、生成 `Citation` | S3-01 | A-S3-3 |
| S3-03 | P0 | 条件边：`generate_answer` / `refuse` 与拒答判定 | S3-02 | A-S3-2 |
| S3-04 | P0 | 接入 `ask`，knowledge 图端到端 | S3-03 | A-S3-1 至 A-S3-5 |

### S4 检索评估与消融实验（V0.1）

| 编号 | 优先级 | 目标 | 前置 | 场景 |
|---|---|---|---|---|
| S4-01 | P0 | 数据集格式、加载、相关切片判定 | S3 | A-S4-1 |
| S4-02 | P0 | Recall@K、MRR、Hit Rate@K | S4-01 | A-S4-1 |
| S4-03 | P0 | 拒答率、有效引用比例 | S4-01 | A-S4-1 |
| S4-04 | P0 | 消融运行器、报告、`eval` CLI | S4-02、S4-03 | A-S4-2 |
| S4-05 | P0 | 【人工】可公开语料与 ≥30 题数据集 | 无（可提前准备） | — |
| S4-06 | P0 | 【真实服务】评估、阈值标定、失败案例分析；`docs/REVIEW-V0.1.md` | S4-04、S4-05 | A-S4-3 |

### S5 Agent 编排（V0.2）

| 编号 | 优先级 | 目标 | 前置 | 场景 |
|---|---|---|---|---|
| S5-01 | P0 | 结构化输出路由、回退、支持 `bind_tools` 的测试替身 | V0.1 | A-S5-4 |
| S5-02 | P0 | 按意图条件分发，重新接入 `chat` | S5-01 | A-S5-9 |
| S5-03 | P0 | `calculate` AST 求值与 Tool Schema | S5-02 | A-S5-2 |
| S5-04 | P0 | 工具循环、白名单、`ToolMessage`、3 轮上限 | S5-03 | A-S5-1、A-S5-3 |
| S5-05 | P0 | 并行双路召回与 Reducer | S5-02 | A-S5-5 |
| S5-06 | P0 | 单路召回降级 | S5-05 | A-S5-6 |
| S5-07 | P0 | 检索重试循环（改写 1 次） | S5-06 | A-S5-7 |
| S5-08 | P0 | 节点耗时、Token、日志密钥检查 | S5-04、S5-07 | A-S5-8 |

### S6 会话与记忆（V1.0）

| 编号 | 优先级 | 目标 | 前置 | 场景 |
|---|---|---|---|---|
| S6-01 | P0 | `InMemorySaver`、历史写回、`Overwrite` 重置请求级字段 | V0.2 | A-S6-1 |
| S6-02 | P0 | 历史窗口与查询改写 | S6-01 | A-S6-2 |
| S6-03 | P0 | `save_memory` 工具与 `InMemoryStore` | S6-01 | A-S6-3 |
| S6-04 | P0 | 记忆 CLI list / clear | S6-03 | A-S6-3 |
| S6-05 | P0 | PostgreSQL Checkpointer 与 Store（需申请依赖） | S6-04 | A-S6-4 |

### S7 服务化与部署（V1.0）

| 编号 | 优先级 | 目标 | 前置 | 场景 |
|---|---|---|---|---|
| S7-01 | P0 | FastAPI `/health`、`/v1/ask` | S6-01 | A-S7-1 |
| S7-02 | P0 | SSE 与单一终止事件 | S7-01 | A-S7-2 |
| S7-03 | P0 | 断开取消与不写历史 | S7-02 | A-S7-2 |
| S7-04 | P0 | Redis 缓存与降级 | S7-01 | A-S7-3、A-S7-4 |
| S7-05 | P0 | Docker Compose、README；`docs/REVIEW-V1.0.md` | S6-05、S7-03、S7-04 | A-S7-5 |

## 8. 暂不实施

| 内容 | 原因 | 引入条件 |
|---|---|---|
| jieba 分词对比 | 可选实验 | S4 完成后，BM25 失败案例显示分词是主要问题 |
| FAISS / pgvector 对比 | 语料小，numpy 足够 | 语料规模使暴力检索延迟明显上升 |
| LLM-as-judge 回答质量评估 | 成本高，评分不稳定 | V0.1 后需要评估生成质量时 |
| 切片重叠 | 默认不重叠 | 消融实验显示边界截断是主要失败类型 |
| `create_agent` / ToolNode 对比 | 核心流程要求显式节点 | S5 完成后作为 P2 学习对比 |
| PDF 解析 | 未排期 | 先更新 SPEC |
| LangSmith 追踪 | 需要外网与账号 | 本地日志不足以定位问题时 |
| 多 Agent | SPEC 2.2 明确不做 | — |

## 9. 当前建议开始的任务

**S0-05 处于 `review`。** 开发者复盘确认前，不开始 S0-06，也不把 S0-05 标为 `done`。S0-01 至 S0-04 仍保持 `review`。Git 提交仍由开发者自行决定。

## 10. 完成记录

| 日期 | 任务 | 结果与证据 |
|---|---|---|
| 2026-10-20 | 环境检查 | 实测版本见第 2 节；`pip check` 无冲突；LangGraph `Runtime` context、`Overwrite`、`InMemoryStore` 可用；`FakeMessagesListChatModel.bind_tools()` 抛出 `NotImplementedError` |
| 2026-10-20 | D-01 至 D-03 | 文档已写入，当时状态 `review` |
| 2026-10-20 | D-01 至 D-03 | 开发者确认可作为基线，状态改为 `done` |
| 2026-10-20 | S0-01 | 进入 `review`。红灯为 `ModuleNotFoundError`（退出码 2）；随后默认 pytest 1 passed；`-m live` 与 `-m integration` 退出码 5 且无未知标记错误；Ruff 与 `mypy src` 通过。未安装新包 |
| 2026-10-20 | S0-02 | 进入 `review`。红灯为收集阶段 `ModuleNotFoundError: No module named 'minirag.contracts'`（退出码 2）。实现后 `tests/unit/test_contracts.py` 13 passed；默认 pytest 14 passed；Ruff 与 `mypy src` 通过。未定义 `IngestReport`。S0-01 未改成 `done` |
| 2026-10-20 | S0-03 | 进入 `review`。红灯为收集阶段 `ModuleNotFoundError: No module named 'minirag.config'`（退出码 2）。补上 `hide_input_in_errors` 后 `tests/unit/test_config.py` 20 passed；默认 pytest 34 passed；`-m live` 与 `-m integration` 各 34 deselected、退出码 5；Ruff 与 `mypy src` 通过。未安装新包。S0-01、S0-02 未改成 `done` |
| 2026-10-20 | S0-04 | 进入 `review`。红灯为收集阶段 `ModuleNotFoundError: No module named 'minirag.llm'`（退出码 2，2 errors）。实现后目标测试 14 passed；默认 pytest 48 passed；`-m live` 与 `-m integration` 各 48 deselected、退出码 5；Ruff 与 `mypy src` 通过。未安装新包，未调用模型。S0-01、S0-02、S0-03 未改成 `done` |
| 2026-10-20 | S0-05 | 进入 `review`。红灯为收集阶段 `ModuleNotFoundError: No module named 'minirag.graph'`（退出码 2，2 errors）。实现后目标测试 12 passed；格式化前默认 pytest 60 passed。格式化测试文件后：`-m live` 与 `-m integration` 各 60 deselected、退出码 5；Ruff 与 `mypy src`（12 source files）通过。未安装新包，未调用真实模型。S0-01 至 S0-04 未改成 `done` |
