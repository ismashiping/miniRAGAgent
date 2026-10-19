# S0-01 项目骨架与工具链

## 1. 本次解决的问题

仓库里只有文档，没有可以导入的 Python 包，也没有 pytest、Ruff、mypy 的统一配置。后续任务无法按 TDD 先写测试再写实现。

## 2. 为什么需要它

测试、格式检查和类型检查都要有一个稳定入口，否则每个任务都会临时决定“从哪里运行、用哪个解释器、哪些测试默认不跑”。S0-01 把这些约定放进 `pyproject.toml`，并让 `import minirag` 在测试中成立。业务功能（契约、配置、图、CLI）留在后续任务。

## 3. 修改前的执行流程

修改前不存在可执行流程。仓库根目录只有 `docs/`，Git 的 `master` 还没有任何提交。直接运行 pytest 时，没有 `minirag` 可导入。

## 4. 涉及的文件与调用关系

| 文件 | 职责 |
|---|---|
| `tests/unit/test_smoke.py` | 冒烟测试 `test_package_exposes_version`：导入包并检查版本 |
| `src/minirag/__init__.py` | 包的入口，提供 `__version__` |
| `pyproject.toml` | 项目元数据、依赖范围、pytest / Ruff / mypy 配置 |
| `.gitignore` | 忽略密钥、字节码和工具缓存，以及将来的索引目录 |

测试进程由 pytest 启动。pytest 读取 `tool.pytest.ini_options`，把 `src/` 加入模块搜索路径，然后执行测试函数。测试函数导入 `minirag`，读取 `__version__`。Ruff 与 mypy 不参与这次导入，它们分别检查风格和类型。

本任务没有类，也没有业务函数。包版本是模块级常量 `__version__`。

## 5. 相关原理

**src 布局。** 源码放在 `src/minirag/`，测试放在 `tests/`。仓库根目录不在包里面。这样测试不会因为“当前目录碰巧能导入”而通过，必须靠显式的 `pythonpath` 找到包。另一种平铺布局是把 `minirag/` 直接放在仓库根目录；当前目录默认就在 `sys.path` 里，容易把“没安装也能导入”误当成配置已经正确。

**pythonpath。** pytest 的 `pythonpath = ["src"]` 只影响 pytest 启动的测试进程，不修改 Conda 环境，也不等于 `pip install`。命令行里单独执行 `python -c "import minirag"` 仍然找不到包。这是 SPEC 3.4 的要求：默认不把项目安装进共享环境。

**测试标记。** `live` 表示需要真实模型、Embedding 或重排服务；`integration` 表示需要本地 PostgreSQL 或 Redis。默认 `addopts` 是 `-m "not live and not integration"`，所以日常 `pytest` 只跑离线测试。在 pytest 9.1.1 上，命令行再写 `-m live` 会覆盖 `addopts` 里的标记表达式，因此 SPEC 6.4 的三条命令可以并存。

**依赖范围。** SPEC 3.4 规定下限用已安装版本，上限用下一个主版本，例如 `langgraph>=1.2.11,<2`。写进 `pyproject.toml` 只是声明，不会安装。未安装的 `langgraph-checkpoint-postgres` 与 psycopg 不在本次声明中。

**Ruff 与 mypy。** Ruff 做格式和基础静态检查（未使用的导入、明显的语法与风格问题）。mypy 检查类型是否一致。一个文件可以格式正确，但类型仍然是错的；也可以类型正确，但格式不符合 Ruff。

**版本常量。** `__version__` 写成 `"0.1.0"`，与 `[project].version` 相同。不使用 `importlib.metadata.version("minirag")`，因为发行版没有安装，那个调用会抛 `PackageNotFoundError`。

## 6. 关键代码的执行顺序

1. 开发者或 AI 执行 `python -m pytest`。
2. pytest 读取 `pyproject.toml`，设置 `pythonpath`、`asyncio_mode = "auto"` 和默认标记过滤。
3. pytest 收集 `tests/unit/test_smoke.py`。
4. 测试导入 `minirag`，解释器在 `src/minirag/__init__.py` 找到包。
5. 断言 `__version__ == "0.1.0"`。
6. 质量检查另行执行：`ruff check .`、`ruff format --check .`、`mypy src`。它们不运行测试。

## 7. 输入、输出与异常

冒烟测试没有业务输入。成功时没有返回值，pytest 记为 passed。

实现之前，收集阶段就失败：`ModuleNotFoundError: No module named 'minirag'`。这发生在测试函数执行前，退出码是 2。SPEC 6.1 允许新模块的第一个测试以导入失败作为红灯。

实现之后，默认 pytest 成功。`-m live` 与 `-m integration` 各收集到 1 个测试、选中 0 个，退出码 5。pytest 用 5 表示“没有选中的测试”。输出里没有未知标记错误。当前还没有带这两个标记的测试，所以退出码 5 是预期结果，不能写成“测试通过”。

`python -c` 查找 `minirag` 的结果仍是 `None`，说明包没有被安装进环境。

## 8. 为什么用当前方案

版本使用手写常量，因为安装发行版会污染共享 Conda 环境。两处版本字符串需要以后人工保持一致；S0-01 只有这一处读取点，测试会在它们不一致时失败。

依赖一次声明 SPEC 3.1 里已经安装的库，范围按 3.4 书写。声明不等于实现那些库的功能，S0-02 及之后的代码仍然不在本任务中。

`.gitignore` 除验收点名的 `.env`、`__pycache__`、`.pytest_cache`、`data/index/` 外，还忽略 `.mypy_cache/`、`.ruff_cache/` 和 `*.py[cod]`。这三项是本次工具链会生成的缓存或字节码，忽略它们才能避免把检查产物提交进去。

## 9. 测试验证了什么

`test_package_exposes_version` 验证两件事：pytest 能通过 `src/` 布局导入 `minirag`；对外暴露的版本是 `"0.1.0"`。它不验证依赖是否已安装，也不验证 Ruff 或 mypy。

## 10. 实际命令与结果

解释器：`C:\Users\11091\.conda\envs\medical-agent\python.exe`。日期：2026-10-20。未执行 pip 安装。

红灯（当时只有测试文件，没有 `src/minirag` 和 `pyproject.toml`）：

```text
python -m pytest tests/unit/test_smoke.py -q
ModuleNotFoundError: No module named 'minirag'
ERROR tests/unit/test_smoke.py
1 error in 0.58s
退出码 2
```

绿灯与质量检查（实现之后）：

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest` | 1 passed in 0.09s | 0 |
| `python -m pytest -m live` | 1 deselected，无未知标记错误 | 5 |
| `python -m pytest -m integration` | 1 deselected，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 5 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 1 source file | 0 |

`importlib.util.find_spec("minirag")` 在普通解释器进程中为 `None`。

学习文档和任务状态写入后又按 SPEC 6.4 重跑了全部命令，结果记在文末“复跑”。

## 11. 容易混淆的概念

- `pythonpath` 让测试进程找得到源码；`pip install -e .` 把项目安装进环境。本项目明确不做后者。
- 退出码 5 是“没有测试被选中”，不是标记未注册。未知标记会在输出里出现 `PytestUnknownMarkWarning` 或严格模式下的错误。
- 默认排除 `live`，是因为这类测试需要密钥和网络，不能作为每次本地开发的门槛。排除不等于禁止运行，显式 `-m live` 仍可选择它们。
- Ruff 不证明类型正确；mypy 不证明格式正确；pytest 不证明两者。三个命令都要跑。
- 依赖范围里的 `>=1.2.11,<2` 限制的是将来安装时的兼容窗口。当前环境里的包版本不会因为写了这行而改变。

## 12. 局限与后续

- `__version__` 与 `pyproject.toml` 的 `version` 是两份字符串，本任务用测试锁住它们相等，没有自动生成。
- 还没有 `live` 或 `integration` 测试，所以这两条命令的退出码是 5。
- 开发工具放在 `[project.optional-dependencies] dev` 中，只是声明；没有执行安装。
- Git 仍无提交。按 TASKS 的建议，文档基线由开发者自行决定是否提交。
- S0-02 才会定义问答契约。本包现在只有版本号。

## 13. 面试问题

**问：src 布局比把包放在仓库根目录多解决了什么？**  
答：根目录默认在 `sys.path` 中，平铺布局会让“在仓库里随便跑 python”就能导入包，从而掩盖安装和测试路径配置错误。src 布局要求测试通过 `pythonpath` 或正式安装才能导入，导入路径是显式的。

**问：`langgraph>=1.2.11,<2` 挡住了哪类风险，又留下了什么风险？**  
答：下限保证使用的是已经实测过的 API 起点，上限排除下一个主版本里允许出现的不兼容变更。同一主版本内的次版本仍可能引入行为变化，所以范围不能代替锁文件和回归测试。

**问：Ruff 通过为什么还要跑 mypy？**  
答：Ruff 看的是格式、导入和一批可确定的代码问题。mypy 看注解和推断类型是否矛盾，例如函数声明返回 `str` 却返回了 `int`。两边的通过不能互相代替。

## 14. 约 30 秒的口述

这个项目用 src 布局，包在 `src/minirag`，测试不把项目安装进共享环境，而是让 pytest 的 pythonpath 指向 src。默认测试排除 live 和 integration，避免没有密钥或数据库时失败。版本号是包里的常量，因为没安装就读不到发行版元数据。Ruff 负责格式和基础检查，mypy 负责类型，pytest 负责行为。

## 15. 练习

不看本文第 5 节，自己完成这两步，并口头说明预期结果：

1. 在 `pyproject.toml` 的 pytest `markers` 里新增一个名为 `slow` 的标记，说明文字自定。
2. 给 `test_package_exposes_version` 加上这个标记后，分别判断默认 `pytest` 和 `pytest -m slow` 会选中还是排除这个测试。改完后把标记和装饰器删掉，恢复本任务的代码。

## 16. 代码作者说明

D-01 至 D-03 的文档由先前的协作写成，开发者在 2026-10-20 确认它们可以作为基线。S0-01 的测试、`pyproject.toml`、`.gitignore`、`src/minirag/__init__.py` 和本文由 AI 在开发者确认计划后编写。开发者尚未手写本任务代码。

## 复跑

2026-10-20，学习文档与 `docs/TASKS.md` 写入后，用同一解释器重跑 SPEC 6.4：

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest` | 1 passed in 0.03s | 0 |
| `python -m pytest -m live` | 1 deselected，无未知标记错误 | 5 |
| `python -m pytest -m integration` | 1 deselected，无未知标记错误 | 5 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m ruff format --check .` | 6 files already formatted | 0 |
| `python -m mypy src` | Success: no issues found in 1 source file | 0 |

与实现刚完成时相比，默认 pytest 仍是 1 passed；格式检查从 5 个文件变为 6 个，因为多了本学习文档。标记命令的退出码仍是 5。

问题
为什么没有 pip install，pytest 仍能 import minirag，而单独开一个 Python 进程却不能？
默认测试为什么要排除 live？排除之后，SPEC 里的 pytest -m live 为什么还能单独选中这类测试？
一次 ruff check 通过，能说明类型标注没有问题吗？请用本任务里的两个工具各举一个它们能抓住、另一个抓不住的例子。