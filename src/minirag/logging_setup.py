"""把当前请求的 ``request_id`` 放进日志记录。

标识存在 ``contextvars.ContextVar`` 里。日志过滤器在记录真正发出时读取它。
异步任务各自有上下文，所以两个并发请求的日志不会写成同一个标识。
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar(
    "minirag_request_id",
    default=None,
)
_UNSET_REQUEST_ID = "-"
REQUEST_ID_LOG_FORMAT = (
    "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
)


class RequestIdFilter(logging.Filter):
    """在日志发出时把当前 ``request_id`` 写到 ``LogRecord`` 上。

    父 logger 上的过滤器不会作用到子 logger 发出的记录。要把每条请求日志都
    带上标识，这个过滤器需要加到实际处理记录的 handler 上。它不丢弃任何记录。

    参数:
        无。构造时不接收项目自己的参数，沿用 ``logging.Filter`` 的默认构造。

    返回:
        过滤器实例。把它加到 logger 或 handler 上之后才会在写日志时被调用。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """把上下文中的请求标识写到这条记录上。

        参数:
            record: 即将交给 handler 的日志记录。本方法会给它增加 ``request_id``
                属性，不修改消息文本。

        返回:
            始终为 ``True``。当前没有请求时属性值是 ``-``，记录仍然输出。
        """
        current = request_id_var.get()
        record.request_id = _UNSET_REQUEST_ID if current is None else current
        return True


class RequestIdFormatter(logging.Formatter):
    """按带 ``request_id`` 的格式渲染日志。

    标准 ``Formatter`` 在格式串包含 ``%(request_id)s``、但记录上没有该属性时会
    失败。这里先补上 ``-``，因此单独使用本类也不会因为缺少过滤器而抛错。

    参数:
        fmt: 格式串。省略时使用 ``REQUEST_ID_LOG_FORMAT``。
        datefmt: 传给 ``logging.Formatter`` 的时间格式。省略时为 ``None``，
            使用日志模块的默认时间格式。

    返回:
        格式器实例。调用 ``format`` 得到一行日志文本。
    """

    def __init__(self, fmt: str | None = None, datefmt: str | None = None) -> None:
        """保存格式串。省略 ``fmt`` 时使用模块级的请求标识格式。

        参数:
            fmt: 日志格式串。``None`` 表示用 ``REQUEST_ID_LOG_FORMAT``。
            datefmt: 时间格式。``None`` 表示用 ``logging.Formatter`` 的默认格式。

        返回:
            无。初始化完成后本实例可以渲染带 ``request_id`` 的记录。
        """
        super().__init__(fmt if fmt is not None else REQUEST_ID_LOG_FORMAT, datefmt)

    def format(self, record: logging.LogRecord) -> str:
        """渲染一条日志。记录上还没有 ``request_id`` 时先写成 ``-``。

        参数:
            record: 要渲染的日志记录。已有非空 ``request_id`` 时保留原值。

        返回:
            按本格式器的格式串生成的一行文本。
        """
        if getattr(record, "request_id", None) is None:
            record.request_id = _UNSET_REQUEST_ID
        return super().format(record)


def _attach_request_id_filter(target: logging.Logger | logging.Handler) -> None:
    """给一个 logger 或 handler 加上 ``RequestIdFilter``，已有则跳过。

    参数:
        target: 接收过滤器的 logger 或 handler。重复调用不会叠多个同类过滤器。

    返回:
        无。
    """
    if any(isinstance(existing, RequestIdFilter) for existing in target.filters):
        return
    target.addFilter(RequestIdFilter())


def configure_logging() -> None:
    """让现有的 ``minirag`` logger 和根 handler 带上请求标识过滤器。

    子 logger 的记录会传播到根 handler。只把过滤器加在父 logger 上，覆盖不到
    这些记录，所以根 handler 也要加。本函数不新增 handler，也不改已有格式串，
    避免和进程里已经配置好的输出重复或互相覆盖。可以重复调用。

    参数:
        无。

    返回:
        无。
    """
    project_logger = logging.getLogger("minirag")
    _attach_request_id_filter(project_logger)
    for handler in project_logger.handlers:
        _attach_request_id_filter(handler)
    for handler in logging.getLogger().handlers:
        _attach_request_id_filter(handler)


@contextmanager
def request_id_context(request_id: str) -> Iterator[None]:
    """在当前上下文里绑定请求标识，离开 ``with`` 时恢复进入前的值。

    恢复使用 ``ContextVar.reset``，所以内层请求结束后外层标识还在。异常离开
    这个块时也会恢复。不要用设置新值来“清空”，否则外层标识会被盖掉。

    参数:
        request_id: 写到后续日志上的请求标识。调用方应传入非空字符串。

    返回:
        无返回值。``with`` 块内 ``request_id_var.get()`` 等于 ``request_id``，
        块结束后回到进入前的值；最外层之前没有绑定时回到 ``None``。
    """
    token = request_id_var.set(request_id)
    try:
        yield
    finally:
        request_id_var.reset(token)
