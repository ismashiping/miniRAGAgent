# S0-02 问答契约

## 1. 本次解决的问题

CLI、LangGraph 入口和以后的 HTTP 接口需要同一组请求与响应结构。本任务用 Pydantic v2 把 SPEC 4.10 的问答契约写成可校验的模型。

定义了 `AskRequest`、`AskResponse`、`Citation`、`ErrorInfo`、`Usage`。没有定义 `IngestReport`，那是 S1-05 的范围。也没有写 `aask`、错误映射或模型调用。

## 2. 为什么需要它

如果每个入口自己用字典拼字段，长度、`top_k` 和“出错时必须带 error”这些规则会散落在各处，测试也要重复写。契约放在基础层 `contracts.py`，上层只依赖它，不反向依赖 CLI 或图。

S0-01 只让 `import minirag` 成功。没有这些模型时，后续任务无法先为非法问题写测试。

## 3. 修改前的执行流程

修改前，包里只有 `src/minirag/__init__.py` 的 `__version__`。测试导入 `minirag.contracts` 会在收集阶段失败。不存在“构造请求再校验”的执行流程。

## 4. 涉及的文件、类和调用关系

| 文件 | 职责 |
|---|---|
| `tests/unit/test_contracts.py` | 先写的行为测试 |
| `src/minirag/contracts.py` | 五个模型及其校验 |

测试直接构造模型，不经过服务或图：

`AskRequest` ← 测试传入 `question`、`top_k`  
`AskResponse` 包含 `ErrorInfo | None`、`Usage | None`、`list[Citation]`

类与校验方法：

- `AskRequest.strip_question`：字段校验，去掉首尾空白。
- `AskResponse.sort_degraded`：字段校验，按名称排序。
- `AskResponse.check_status_consistency`：模型校验，检查 `status` 与 `error`，以及非 `knowledge` 时不能带引用。

`ErrorInfo.code` 的类型是 `ErrorCode`，只含 SPEC 4.10 的五个错误码。`Intent` 是 `chat`、`knowledge`、`calculate`。`AnswerStatus` 是 `answered`、`insufficient_evidence`、`error`。

## 5. 相关原理

**Pydantic v2 校验一个字段的顺序。** 先跑 `mode="before"` 的 `field_validator`，再做类型转换和 `Field` 约束，最后跑默认的 `mode="after"` 字段校验。`question` 必须先 `strip()`，再检查长度 1 到 2000。如果先检查长度，两侧带空格的 2000 字问题会被误拒，纯空白串又可能在去空白之前被当成合法。

**字段校验和模型校验。** `field_validator` 只能看到当前字段。`top_k` 的 1 到 20、`degraded` 排序都属于这一层。`model_validator(mode="after")` 能看到已经通过字段校验的整个对象，所以才能写“`status=error` 时必须有 `error`，其他状态必须是 `None`”。

**默认值不能用可变对象。** `citations` 和 `degraded` 使用 `Field(default_factory=list)`。如果写成 `= []`，多个响应会共享同一个列表。

**`None` 和 `0`。** `usage is None` 表示这次请求没有可用的用量汇总，SPEC 禁止用 0 冒充“未知”。`Usage.input_tokens == 0` 表示模型确实报告了 0 个输入 Token。`Citation` 的四个分数默认 `None`，表示这一路没有参与计算，同样不能填 0。

**一套 Schema。** SPEC 4.10 规定 HTTP 只是传输层。现在还没有 HTTP，但字段已经按这份契约固定，避免以后再发明一套 JSON 字段。

Python 3.10 没有 `typing.Self`，模型校验的返回类型写成字符串 `"AskResponse"`。

## 6. 关键代码的执行顺序

以 `AskRequest(question="  hello  ", top_k=5)` 为例：

1. Pydantic 收到原始输入。
2. `strip_question` 把问题变成 `"hello"`。
3. `Field(min_length=1, max_length=2000)` 检查去掉空白后的字符串。
4. `top_k` 按整数检查 `ge=1, le=20`；省略时使用默认值 5。
5. 得到 `AskRequest` 实例。任一步失败都抛 `ValidationError`，不会返回半成品。

以 `AskResponse` 为例：

1. 各字段先单独校验。`degraded` 在字段校验末尾被 `sorted()` 成新列表。
2. 全部字段成功后，`check_status_consistency` 检查 `status` 与 `error` 是否匹配。
3. 同一方法再检查：`intent` 不是 `"knowledge"` 时，`citations` 必须为空。`intent` 默认是 `None`，因此默认也不能带引用。
4. 通过后返回实例。

## 7. 输入、输出、状态变化和异常

这些模型没有内部服务状态。输入是构造参数，输出是模型实例或 `ValidationError`。

已测行为：

- `"  hello  "` 变成 `"hello"`。`""`、`"   "`、`"\n\t"` 被拒绝。
- 恰好 2000 个字符通过；两侧再加空白后仍是 2000 个字符，也通过。2001 个字符被拒绝。
- 不传 `top_k` 时为 5；1 和 20 通过；0 和 21 被拒绝。
- 不传 `session_id`、`user_id` 时为 `None`。
- `status="error"` 且带 `ErrorInfo` 通过；不带 `error` 被拒绝。
- `answered` 和 `insufficient_evidence` 在 `error=None` 时通过；带了 `error` 被拒绝。
- `code="timeout"` 被拒绝。允许的错误码只有五个字面量。
- 不传 `citations`、`degraded` 时得到空列表，且两个响应不共享列表。
- `["rerank", "cache"]` 保存为 `["cache", "rerank"]`。
- 不传 `usage` 时为 `None`。`input_tokens=0` 可以保存。负数 Token 或负数 `latency_ms` 被拒绝。
- `Citation` 不传 `heading` 和四个分数时，它们都是 `None`。
- `intent="knowledge"` 可以带引用；`None`、`chat`、`calculate` 带引用会被拒绝。

校验失败不返回业务错误码 `invalid_request`。把 `ValidationError` 映射成响应是 S0-07 的工作。本任务只让非法数据构造失败。

## 8. 为什么用当前方案

长度和范围用 `Field`，因为它们是单字段约束，不需要手写 `if`。去空白用 `mode="before"`，因为它必须发生在长度检查之前。`status` 与 `error` 的关系用 `model_validator`，因为规则跨字段。

`degraded` 在模型里排序，是为了让 SPEC 4.10 的“按名称排序”在任何入口构造响应时都成立。`sorted()` 返回新列表，不修改调用方传入的原列表。去重仍留给以后的 Reducer，Schema 不悄悄删掉重复名称。

`Usage` 的 Token 字段使用 `input_tokens`、`output_tokens`，与当前环境里 `langchain_core` 的 `UsageMetadata` 同名，方便 S0-04 做转换。模型名用 `model`，因为 `UsageMetadata` 本身不带模型名。没有加入 `total_tokens`，SPEC 只要求模型名、输入 Token 和输出 Token。

`Citation.marker` 使用 `str`。SPEC 只说“引用编号”，没有规定是整数还是 `"[1]"` 这种文本。字符串可以原样保存标记，避免现在就猜格式。

非 `knowledge` 不能带 `citations`，来自 SPEC 4.10 的原句。它和 `error` 一样是跨字段规则，所以放进同一个 `model_validator`。这比只靠以后的服务层记得“清空列表”更早暴露非法组合。

没有把“`knowledge` 必须有引用”写成规则。证据不足时 `intent` 可以是 `knowledge`，同时 `citations` 为空，这是 SPEC 的拒答结果。

## 9. 测试验证了什么

| 测试 | 验证 |
|---|---|
| `test_question_strips_surrounding_whitespace` | 首尾空白被去掉，中间内容保留 |
| `test_blank_question_is_rejected` | 空串和只含空白的串不能通过 |
| `test_question_length_limits_apply_after_strip` | 2000 通过，带外侧空白的 2000 通过，2001 拒绝 |
| `test_top_k_defaults_to_5_and_rejects_out_of_range` | 默认 5；边界 1 和 20 通过；0 和 21 拒绝 |
| `test_optional_ids_default_to_none` | 请求里的会话和用户标识默认为空 |
| `test_error_is_required_only_when_status_is_error` | 三种 `status` 与 `error` 的搭配 |
| `test_unknown_error_code_is_rejected` | 错误码不能随手新增 |
| `test_citations_and_degraded_default_to_empty_lists` | 默认空列表，且实例之间不共享 |
| `test_degraded_names_are_sorted` | 降级组件名按字典序保存 |
| `test_usage_may_be_none_and_zero_is_a_real_count` | 缺失用量是 `None`；0 是合法计数 |
| `test_citations_are_empty_unless_intent_is_knowledge` | 只有 `knowledge` 可以带引用 |
| `test_latency_and_token_counts_reject_negative_values` | 耗时和 Token 不能为负 |
| `test_citation_scores_default_to_none` | 四个分数和 `heading` 默认是 `None` |

这些测试不调用模型，不读取 `.env`，也不检查 `IngestReport`。

## 10. 实际命令与结果

解释器：`C:\Users\11091\.conda\envs\medical-agent\python.exe`。日期：2026-10-20。未安装新包。

红灯发生在实现 `src/minirag/contracts.py` 之前。测试文件顶层就导入该模块，所以 pytest 在收集阶段停止，后面的断言还没运行。因此没有观察到“`ValidationError` 未抛出”那种逐条失败。这是新模块缺失时的导入失败，符合 SPEC 6.1，不是测试写错，也不是环境缺 Pydantic。

```text
python -m pytest tests/unit/test_contracts.py -q
ImportError while importing test module '...tests\unit\test_contracts.py'
ModuleNotFoundError: No module named 'minirag.contracts'
ERROR tests/unit/test_contracts.py
1 error in 0.46s
退出码 2
```

实现之后、写入本学习文档之前：

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/unit/test_contracts.py -q` | 13 passed in 0.14s | 0 |
| `python -m pytest -q` | 14 passed in 0.08s | 0 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 8 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 2 source files | 0 |

此时还没有重跑 `-m live` 和 `-m integration`。这两条的结果只记在下面的复跑里，不以本节表格冒充。

## 11. 容易混淆的概念

- `field_validator` 改的是一个字段的值。`model_validator` 检查字段之间的关系。把“去空白”写进模型校验也能工作，但长度约束就会和它抢顺序。
- `ValidationError` 是构造模型失败。`AskResponse.status="error"` 是一份已经构造成功的失败响应。非法 `question` 现在还到不了后者。
- `usage=None` 是“没有用量”。`input_tokens=0` 是“用量已知，且为 0”。检索分数同理：没算过是 `None`，算出来的 0 分才是 0.0。
- `intent=None` 不是第四种意图。SPEC 规定请求校验失败时响应里的意图为空。意图枚举本身只有三个值。
- 默认空列表和“禁止非知识问答携带引用”是两件事。前者是省略参数时的值，后者是传入非空列表时的跨字段规则。
- 排序发生在保存时。调用方传入的原列表不会被原地排序。

## 12. 局限与后续

- 没有把 `ValidationError` 变成 `code=invalid_request` 的响应。A-S0-2 的这一半在 S0-07。
- 没有检查 `request_id`、`message`、`marker` 是否为空字符串。SPEC 没有写最小长度，本任务未加这条约束。
- `degraded` 会排序，但不会去重。重复名称要等 S2 的 Reducer。
- `marker` 的具体文本格式要到 S3 引用解析时再定。
- 多个模型调用如何汇总成一个 `Usage`，以及拿不到 `usage_metadata` 时谁负责填 `None`，属于 S0-04 和 S0-06。
- S0-01 仍是 `review`，本任务没有把它改成 `done`。

## 13. 面试问题

**问：为什么 `question` 用 before 字段校验，而 `error` 用模型校验？**  
答：去空白只改变 `question` 自己，而且必须发生在 `min_length` / `max_length` 之前，所以用 `mode="before"`。`error` 是否合法取决于 `status`，单个字段看不到另一个字段，所以用 `mode="after"` 的模型校验，此时两个值都已经就绪。

**问：为什么 CLI 和 HTTP 不各写一套模型？**  
答：SPEC 把 HTTP 定义为传输层。字段含义、默认值和非法组合如果分叉，测试就要覆盖两套规则，客户端看到的错误也会不一致。一套 `AskRequest` / `AskResponse` 让入口只负责解析和序列化。

**问：用量字段为什么允许 0，却又允许整个 `usage` 为 `None`？**  
答：0 是模型报告的真实计数。`None` 表示这次没有拿到用量，SPEC 禁止用 0 冒充缺失。引用分数也是这个约定：未参与的分数保持 `None`。

## 14. 约 30 秒的口述

问答契约是一组 Pydantic 模型，CLI 和图以后都用它。问题会先去掉首尾空白，再限制在 1 到 2000 字；`top_k` 默认 5，只允许 1 到 20。响应里 `status=error` 必须带 `error`，其他状态必须是 `None`。用量缺失用 `None`，不能写成 0。字段校验处理单字段，模型校验处理字段之间的关系。非法输入在构造时抛 `ValidationError`，映射成 `invalid_request` 是后面的入口任务。

## 15. 练习

不看 `contracts.py` 里的校验方法，自己先说出结果，再在解释器里构造一次核对。做完后不要把试验代码留在仓库里。

1. `AskRequest(question="  " + "a" * 2000)` 应该成功还是失败？成功的话，`question` 的长度是多少？
2. `AskResponse` 的 `status` 为 `answered`，同时传入一个 `ErrorInfo`，应该发生什么？
3. 给 `AskResponse` 增加一个可选字段 `trace_id: str | None = None`，并写一个测试证明省略时它是 `None`。核对后把字段和测试删掉，恢复本任务的代码。

## 16. 代码作者说明

S0-02 的测试、`src/minirag/contracts.py`、`docs/TASKS.md` 中本任务的状态与结果，以及本文，都由 AI 在开发者明确要求实施 S0-02 后编写。开发者尚未手写这些代码。S0-01 的文件没有被改写，其状态仍是 `review`。

## 复跑

2026-10-20，学习文档与 `docs/TASKS.md` 写入后，用同一解释器重跑。`-m live` 与 `-m integration` 的输出里没有未知标记错误。退出码 5 表示 14 个测试都被取消选择，不是标记未注册，也不能写成“测试通过”。

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests/unit/test_contracts.py -q` | 13 passed in 0.06s | 0 |
| `python -m pytest -q` | 14 passed in 0.06s | 0 |
| `python -m pytest -m live -q` | 14 deselected in 0.04s，无未知标记错误 | 5 |
| `python -m pytest -m integration -q` | 14 deselected in 0.04s，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 9 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 2 source files | 0 |

默认 pytest 的通过数量与实现刚完成时一致，仍是 14。格式检查从 8 个文件变为 9 个，因为多了本学习文档。
