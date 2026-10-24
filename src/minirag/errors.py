"""领域异常，以及写进响应的固定错误说明。

供应商异常算不算模型不可用，由 ``llm.chat_model`` 判断。本模块不导入模型 SDK，
因此基础层不依赖具体客户端。``retrieval_failed`` 和 ``service_unavailable``
仍是契约里的错误码，但对应的领域异常要等召回和数据库功能出现后再加。
"""

from minirag.contracts import ErrorInfo

INVALID_REQUEST_MESSAGE = "请求参数不合法。"
LLM_UNAVAILABLE_MESSAGE = "模型暂时不可用，请稍后重试。"
INTERNAL_ERROR_MESSAGE = "服务内部出错，请稍后重试。"


class LLMUnavailableError(Exception):
    """模型超时、连不上、被限流，或在重试后仍返回 5xx。

    入口把这个异常映射为 ``llm_unavailable``。``message`` 只能是面向用户的说明。
    SDK 原文、密钥和堆栈放在 ``raise ... from`` 留下的 ``__cause__`` 上，不放进
    本异常的字符串。

    参数:
        message: 面向用户的说明。省略时用模块里的固定句子。调用方不应把捕获到的
            异常文本填进来。

    返回:
        异常实例。构造本身不会中断流程，由调用方抛出。
    """

    def __init__(self, message: str = LLM_UNAVAILABLE_MESSAGE) -> None:
        """保存面向用户的说明。

        参数:
            message: 写入异常字符串的文本。默认是固定短句。

        返回:
            无。初始化完成后 ``str(实例)`` 等于 ``message``。
        """
        super().__init__(message)


def invalid_request_info() -> ErrorInfo:
    """构造非法请求的错误信息。

    不接收 ``ValidationError``。那个异常的文本会带上用户输入，不能交给调用方。

    返回:
        ``code`` 为 ``invalid_request`` 的 ``ErrorInfo``。``message`` 是固定短句，
        不包含字段名、输入值或堆栈。
    """
    return ErrorInfo(code="invalid_request", message=INVALID_REQUEST_MESSAGE)


def error_info_for_exception(exc: BaseException) -> ErrorInfo:
    """把图或适配层抛出的异常收成响应里的 ``ErrorInfo``。

    ``LLMUnavailableError`` 对应 ``llm_unavailable``。其他类型，包括图内部的
    ``ValidationError``，都对应 ``internal_error``。请求是否合法在进入图之前
    单独判断；这里再出现的校验失败是内部数据不合契约，不是客户端的非法请求。

    参数:
        exc: 要分类的异常。只看类型，不读取 ``str(exc)``，因此异常文本里的密钥
            不会进到返回值。

    返回:
        固定说明的 ``ErrorInfo``。文本里没有异常原文、异常类型名或堆栈。
    """
    if isinstance(exc, LLMUnavailableError):
        return ErrorInfo(code="llm_unavailable", message=LLM_UNAVAILABLE_MESSAGE)
    return ErrorInfo(code="internal_error", message=INTERNAL_ERROR_MESSAGE)
