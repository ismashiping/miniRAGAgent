# S0-03 配置管理

## 1. 本次解决的问题

聊天模型的模型名、`base_url`、API Key、超时和重试次数需要从进程外面读入，而且密钥不能出现在 `str`、`repr` 或校验错误里。

本任务新增 `Settings`。它用 pydantic-settings 2.15 读取环境变量和 `.env`。API Key 的类型是 `SecretStr`。没有创建模型客户端，也没有读取 Embedding、重排、切分或索引目录。那些字段留给后续任务。

## 2. 为什么需要它

S0-04 要按配置构造 `ChatOpenAI`。如果模型名和密钥写在源码里，换服务就要改代码，测试也会碰到真实密钥。SPEC 5.6 要求用环境变量和 pydantic-settings，并提供只含占位值的 `.env.example`。

S0-02 只定义了问答数据结构。没有配置对象时，后面的工厂函数无法先写出“超时是多少、缺密钥时报什么”的测试。

## 3. 修改前的执行流程

修改前，仓库里没有 `config.py`。测试导入 `minirag.config` 会在收集阶段失败。不存在“读环境变量再得到 `Settings`”的执行流程。`.gitignore` 已经忽略 `.env`，但还没有 `.env.example`。

## 4. 涉及的文件、类和调用关系

| 文件 | 职责 |
|---|---|
| `tests/unit/test_config.py` | 先写的行为测试。除 `.env` 优先级测试外，都传入 `_env_file=None` |
| `src/minirag/config.py` | `Settings` 与空白必填项校验 |
| `.env.example` | 变量名和占位值，不含真实密钥 |

测试直接构造 `Settings`，不经过服务或图：

`monkeypatch.setenv` 或临时 `.env` → `Settings` → 字段值或 `ValidationError`

类与方法：

- `Settings`：五个字段。`api_key` 是 `SecretStr`，其余为普通类型。
- `Settings.reject_blank_required_value`：拒绝只含空白的 `chat_model`、`base_url`、`api_key`。

环境变量名：

| 字段 | 环境变量 | 缺省 |
|---|---|---|
| `chat_model` | `MINIRAG_CHAT_MODEL` | 无，必填 |
| `base_url` | `MINIRAG_BASE_URL` | 无，必填 |
| `api_key` | `MINIRAG_API_KEY` | 无，必填 |
| `timeout` | `MINIRAG_TIMEOUT` | `600.0` |
| `max_retries` | `MINIRAG_MAX_RETRIES` | `2`，允许 0 到 2 |

本模块不导入 `contracts.py` 或其他项目模块。

## 5. 相关原理

**配置和代码分离。** 模型名、地址和密钥随部署变化，代码只声明字段、默认值和校验。`.env.example` 告诉使用者要准备哪些名字；真正的 `.env` 被 `.gitignore` 排除。

**来源优先级。** 已安装的 pydantic-settings 2.15 按“构造参数 → 环境变量 → `.env` → 字段默认值”取值。测试确认：构造参数覆盖环境变量，环境变量覆盖 `.env` 中的同名项，`.env` 可以补上环境变量里没有的项。未配置 secrets 目录，所以没有第四套密钥文件来源。

**`_env_file=None`。** `model_config` 里的 `env_file=".env"` 会读取当前工作目录的 `.env`。这个参数只对这一次构造生效，用来让测试不碰开发者自己的文件。它不是模型字段。

**`SecretStr`。** 非空密钥的 `str` 和 `repr` 是 `**********`，`model_dump_json()` 同样是掩码。明文只在 `get_secret_value()` 返回。空字符串的显示是 `''` 而不是星号，所以空白密钥要先拒绝，不能靠掩码来补救。

**`hide_input_in_errors`。** Pydantic 默认会在 `ValidationError` 里打印输入。缺模型名时，已经传入的 API Key 会出现在 `input_value={...}` 中。打开这个选项后，错误不再回显输入值。变量名仍然留在错误位置上。

**别名和前缀。** `env_prefix="MINIRAG_"` 的默认作用目标是字段名，不会再加到已经写好的别名前面。因此 `validation_alias` 使用完整变量名 `MINIRAG_API_KEY`，同时保留字段名 `api_key`，这样环境变量和 `Settings(api_key=...)` 都能通过。别名的第一项会成为缺失错误里的位置，于是错误文本包含变量名。

**空字符串和空白。** `env_ignore_empty=True` 把 `MINIRAG_API_KEY=` 当成没设置，于是走“字段缺失”。只含空格的值不是空字符串，会进入 `reject_blank_required_value`，再以“缺少环境变量 MINIRAG_API_KEY”拒绝。

## 6. 关键代码的执行顺序

以环境变量已设置、调用 `Settings(_env_file=None)` 为例：

1. `_env_file=None` 关闭这一次的 `.env` 读取。
2. pydantic-settings 读取进程环境。`MINIRAG_CHAT_MODEL` 等名字来自字段别名。
3. 字符串按字段类型转换。`api_key` 变成 `SecretStr`，`timeout` 变成 `float`。
4. `reject_blank_required_value` 检查三个必填字段去掉空白后是否还有内容。
5. `timeout > 0`、`0 <= max_retries <= 2` 由 `Field` 检查。未设置这两项时使用 600 和 2。
6. 得到 `Settings`。任一步失败都抛 `ValidationError`，不会返回半成品。

未传 `_env_file` 时，第 2 步之前还会读取当前目录的 `.env`。同名环境变量覆盖文件中的值。

## 7. 输入、输出、状态变化和异常

`Settings` 不保存全局状态，每次构造都重新读取来源。输入是环境变量、可选的 `.env` 和构造参数。输出是实例或 `ValidationError`。

已测行为：

- 五个环境变量都能加载。`timeout` 的字符串 `"30.5"` 变成 `30.5`，`max_retries` 的 `"1"` 变成 `1`。
- 不设置超时和重试时，值为 `600.0` 和 `2`。
- 缺少 `MINIRAG_API_KEY`、`MINIRAG_CHAT_MODEL` 或 `MINIRAG_BASE_URL` 时，错误文本包含对应变量名。
- 环境变量或构造参数中的空字符串、只含空格的 API Key 被拒绝，错误文本包含 `MINIRAG_API_KEY`。
- 只含空格的模型名和空的 `base_url` 被拒绝。
- `str(settings)`、`repr(settings)`、`str(settings.api_key)`、`repr(settings.api_key)` 和 `model_dump_json()` 都不含密钥原文。`get_secret_value()` 返回原文。
- 超时 `0`、`-1`、非数字，以及重试 `-1`、`3` 被拒绝，错误文本不含 API Key。
- 未知构造参数被拒绝。
- 构造参数覆盖同名环境变量。
- `_env_file=None` 时，当前目录里的 `.env` 不被读取，文件中的密钥也不会出现在错误里。
- 不禁用文件时，`.env` 能加载；环境变量覆盖文件中的密钥和超时，文件里的模型名和地址仍保留。
- `.env.example` 含有五个变量名和 `MINIRAG_API_KEY=your-api-key`，文本中没有 `sk-`。

校验失败不会变成 `AskResponse`。那是 S0-07 的错误映射。

## 8. 为什么用当前方案

超时默认用 600 秒，是因为 SPEC 4.7 只说超时可配置，决策 11 的数值表里没有秒数。当前环境的 `openai._constants.DEFAULT_TIMEOUT` 是 `Timeout(timeout=600, connect=5.0)`。`Settings.timeout` 保存总超时 `600.0` 这一个浮点数，没有把连接超时 5 秒单独做成字段。S0-04 可以把这个数传给 `ChatOpenAI` 的 `timeout`。

重试默认 2，并且 `le=2`。SPEC 4.7 写的是 `max_retries=2`，决策 11 写的是“最多重试 2 次”。因此可以配置成 0 或 1，不能配置成 3。0 表示客户端不再重试。

模型名和 `base_url` 没有默认值。SPEC 没有指定默认模型，也不该在用户没写地址时悄悄访问官方接口。

只放聊天相关的五个字段。索引目录、切分长度、Embedding 和重排要到后面的任务才用，现在加进去没有测试能约束它们。

没有做 `get_settings()` 缓存。ARCHITECTURE 要求节点不要读取全局单例。谁需要配置，谁构造或接收 `Settings`。

错误里出现变量名，靠的是 `AliasChoices` 的第一项，而不是手写一套异常类型。`hide_input_in_errors=True` 是安装好的 Pydantic 2.13 已有选项。第一次实现没开它时，缺少模型名的错误把 `sk-test-secret-value` 打印了出来，对应测试失败后才补上。

## 9. 测试验证了什么

| 测试 | 验证 |
|---|---|
| `test_settings_load_from_environment` | 五个环境变量被正确转换 |
| `test_timeout_and_retries_default_when_unset` | 未设置时超时 600、重试 2 |
| `test_missing_api_key_error_includes_variable_name` | 缺密钥的错误包含 `MINIRAG_API_KEY` |
| `test_blank_api_key_is_reported_as_missing` | 环境变量中的空串和空格都算缺失 |
| `test_blank_constructor_api_key_is_rejected` | 构造参数里的空密钥同样被拒绝 |
| `test_blank_model_and_base_url_are_rejected` | 空白模型名和空地址被拒绝 |
| `test_missing_model_and_base_url_name_their_variables` | 缺字段时错误含变量名，且不含已传入的密钥 |
| `test_repr_and_str_do_not_reveal_api_key` | `str`、`repr` 和 JSON 只有掩码 |
| `test_invalid_timeout_and_retries_are_rejected` | 超时必须大于 0；重试只允许 0 到 2；错误不含密钥 |
| `test_unknown_setting_is_rejected` | 未知构造参数被拒绝 |
| `test_constructor_arguments_override_environment` | 构造参数优先于环境变量 |
| `test_disabled_env_file_is_not_read` | `_env_file=None` 不读当前目录的 `.env` |
| `test_dotenv_loads_and_environment_overrides_it` | `.env` 生效，同名环境变量覆盖它 |
| `test_env_example_contains_placeholders_only` | 示例文件只有占位值 |

带参数的用例展开后共 20 个。这些测试不访问网络。读取 `.env` 的用例把工作目录改到 `tmp_path`，不使用仓库里可能存在的真实 `.env`。

## 10. 实际命令与结果

解释器：`C:\Users\11091\.conda\envs\medical-agent\python.exe`。日期：2026-10-20。未安装新包。

红灯发生在实现 `src/minirag/config.py` 之前。测试文件顶层就导入 `Settings`，所以 pytest 在收集阶段停止。最终测试文件上的红灯是：

```text
python -m pytest tests/unit/test_config.py -q
ImportError while importing test module '...tests\unit\test_config.py'
ModuleNotFoundError: No module named 'minirag.config'
ERROR tests/unit/test_config.py
1 error in 0.44s
退出码 2
```

这是新模块缺失，符合 SPEC 6.1。同一文件更早一版的收集失败是 `1 error in 0.43s`，原因相同。两次都没有执行到断言。

实现并打开 `hide_input_in_errors` 之后、写入本学习文档之前：

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/unit/test_config.py -q` | 20 passed in 0.17s | 0 |
| `python -m pytest -q` | 34 passed in 0.38s | 0 |
| `python -m pytest -m live -q` | 34 deselected in 0.16s，无未知标记错误 | 5 |
| `python -m pytest -m integration -q` | 34 deselected in 0.16s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 11 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 3 source files | 0 |

打开 `hide_input_in_errors` 之前，`test_missing_model_and_base_url_name_their_variables` 失败：错误文本含 `sk-test-secret-value`。当时是 1 failed、19 passed，退出码 1。这不是红灯阶段的收集错误。

## 11. 容易混淆的概念

- `SecretStr` 挡住的是显示和默认 JSON。它挡不住 `get_secret_value()`，也挡不住进程环境里本来就有的变量。
- 字段缺失和字段空白不是同一条路径。空字符串被 `env_ignore_empty` 丢掉；空格要靠校验方法拒绝。
- `_env_file=None` 只影响这一次构造。类上的 `env_file=".env"` 仍然是平时的默认行为。
- `ValidationError` 是配置加载失败。它还不是 `AskResponse.status="error"`。
- `timeout=600` 是总超时的秒数，不是 OpenAI SDK 那个同时带 `connect=5.0` 的 `Timeout` 对象。
- `max_retries=0` 是合法配置，表示不重试。默认值 2 不是“必须正好重试两次”。

## 12. 局限与后续

- 没有 Embedding、重排、切分长度、索引目录、历史窗口或缓存 TTL。后面的任务再往 `Settings` 增加字段。
- 没有检查 `base_url` 是不是合法 URL。
- 没有构造 `ChatOpenAI`。S0-04 才会把这些字段交出去。
- `SecretStr` 不防止调用方取出明文后再打印。日志测试要到会写日志的任务里做。
- pydantic-settings 的调试开关 `PYDANTIC_SETTINGS_DEBUG` 可能打印来源中的原始值。本模块没有打开它。
- 超时 600 秒是对照已安装 SDK 作出的选择，SPEC 正文没有写这个秒数。如果要改，应同时改测试和 `.env.example`。
- S0-01 与 S0-02 仍是 `review`。本任务没有把它们改成 `done`。

## 13. 面试问题

**问：环境变量、`.env` 和默认值谁优先？测试怎样避免读到本机 `.env`？**  
答：构造参数优先，然后是环境变量，再是当前目录的 `.env`，最后是字段默认值。测试把 `_env_file=None` 传给这一次构造，并用 `monkeypatch` 清掉 `MINIRAG_` 变量。需要验证文件时，把工作目录改到临时目录再写一份 `.env`。

**问：`SecretStr` 能防住什么，防不住什么？**  
答：它让 `str`、`repr` 和默认 JSON 显示掩码，避免日志直接打印配置对象时露出密钥。它不加密内存，不改变环境变量，调用 `get_secret_value()` 仍能拿到明文。另外，Pydantic 默认会把输入写进 `ValidationError`，所以还要 `hide_input_in_errors`，否则缺别的字段时密钥仍会被打出来。

**问：为什么缺密钥的错误要带变量名，而不是只写 `api_key`？**  
答：使用者对着 `.env.example` 排错，看到的是 `MINIRAG_API_KEY`。只写字段名时，他还得猜前缀和大小写。别名的第一项就是这个变量名，所以 `ValidationError` 的位置直接是它。

## 14. 约 30 秒的口述

配置放在 `Settings` 里，用 pydantic-settings 读取，不写进源码。构造参数优先于环境变量，环境变量优先于 `.env`，最后才是默认值。聊天模型名、地址和 API Key 必填，缺了就报对应的 `MINIRAG_` 变量名。API Key 用 `SecretStr`，打印对象只看到掩码，但 `get_secret_value()` 仍能取出明文，所以不能把返回值写进日志。超时默认 600 秒，对齐当前 OpenAI SDK 的总超时；重试默认 2 次，并且不允许超过 2 次。测试用 `_env_file=None` 避开本机 `.env`。

## 15. 练习

不看 `config.py` 的实现，先说出结果，再在解释器里构造一次核对。做完后不要把试验代码留在仓库里。解释器需要能导入 `minirag`，可以用 pytest 的方式，或临时把 `src` 放进 `PYTHONPATH`。不要打印真实密钥。

1. 只设置 `MINIRAG_CHAT_MODEL`、`MINIRAG_BASE_URL` 和 `MINIRAG_API_KEY`，然后 `Settings(_env_file=None)`。`timeout` 和 `max_retries` 应该是多少？
2. 环境变量里的 API Key 是 `from-env`，构造时又传入 `api_key="from-init"`。最终 `get_secret_value()` 是哪一个？`repr(settings)` 里能看到它吗？
3. 给 `Settings` 增加可选字段 `index_dir: str = "data/index"`，环境变量名沿用 `MINIRAG_` 前缀，并写一个测试证明省略时它是 `data/index`。核对后把字段和测试删掉，恢复本任务的代码。

## 16. 代码作者说明

S0-03 的测试、`src/minirag/config.py`、`.env.example`、`docs/TASKS.md` 中本任务的状态与结果，以及本文，都由 AI 在开发者明确要求实施 S0-03 后编写。开发者尚未手写这些代码。S0-01 与 S0-02 的源码和测试没有被改写，它们的状态仍是 `review`。

## 复跑

2026-10-20，学习文档与 `docs/TASKS.md` 写入后，用同一解释器重跑。`-m live` 与 `-m integration` 的输出里没有未知标记错误。退出码 5 表示 34 个测试都被取消选择，不是标记未注册，也不能写成“测试通过”。

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/unit/test_config.py -q` | 20 passed in 0.16s | 0 |
| `python -m pytest -q` | 34 passed in 0.20s | 0 |
| `python -m pytest -m live -q` | 34 deselected in 0.09s，无未知标记错误 | 5 |
| `python -m pytest -m integration -q` | 34 deselected in 0.09s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 12 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 3 source files | 0 |

默认 pytest 的通过数量与实现刚完成时一致，仍是 34。格式检查从 11 个文件变为 12 个，因为多了本学习文档。live 与 integration 的退出码在文档写入后单独再取了一次，均为 5。
