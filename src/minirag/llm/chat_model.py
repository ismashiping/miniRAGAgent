"""构造聊天模型，并把单次回复的用量转成契约中的 ``Usage``。

本模块也负责识别供应商的不可用异常。它不导入图或服务入口，也不发起网络请求。
"""

import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from minirag.config import Settings
from minirag.contracts import Usage
from minirag.errors import LLM_UNAVAILABLE_MESSAGE, LLMUnavailableError

# openai 3.13.0 在重试耗尽后抛出这些类型。APITimeoutError 是 APIConnectionError
# 的子类。langchain-openai 1.6.2 的 OpenAITimeoutError、OpenAIConnectionError、
# OpenAIRateLimitError、OpenAIAPIError 分别继承它们，因此不用再写一层包装类。
# 400、401、403、404、408、409、422 以及内置 TimeoutError 不在这里。
_PROVIDER_UNAVAILABLE = (
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)


def build_chat_model(settings: Settings) -> BaseChatModel:
    """按配置构造 ``ChatOpenAI``，构造过程不调用模型。

    已安装的 langchain-openai 1.6.2 把构造参数映射为这些字段：``model`` 存到
    ``model_name``，``base_url`` 存到 ``openai_api_base``，``timeout`` 存到
    ``request_timeout``，``max_retries`` 原样保存。同步和异步客户端在构造时创建，
    但不会连接 ``base_url``。

    API Key 以 ``SecretStr`` 传入，不调用 ``get_secret_value()``，因此本函数没有
    明文密钥可以写进日志。调用方也不应打印 ``get_secret_value()`` 的返回值。

    参数:
        settings: 聊天模型配置。读取 ``chat_model``、``base_url``、``api_key``、
            ``timeout`` 和 ``max_retries``。超时和重试使用配置中的值，不在这里
            另写一套默认值。

    返回:
        配置好的 ``ChatOpenAI``，类型标注为 ``BaseChatModel``，便于调用方按统一
        接口使用。本函数不调用 ``invoke`` 或 ``ainvoke``。
    """
    return ChatOpenAI(
        model=settings.chat_model,
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout=settings.timeout,
        max_retries=settings.max_retries,
    )


def usage_from_ai_message(message: AIMessage, *, model: str) -> Usage | None:
    """把一条 ``AIMessage`` 的用量转成 ``Usage``。

    ``usage_metadata`` 只有 Token 计数，没有模型名，所以模型名由调用方传入。
    不读取 ``response_metadata``，因为不同服务放模型名的键不一致。本函数只处理
    一条消息，不把多次调用汇总成一个 ``Usage``。

    参数:
        message: 模型返回的一条回复。只读取 ``usage_metadata``。
        model: 写入 ``Usage.model`` 的模型名。通常是这次调用使用的配置模型名。

    返回:
        ``usage_metadata`` 缺失或为 ``None`` 时返回 ``None``。存在时返回
        ``Usage``，其中 ``input_tokens`` 和 ``output_tokens`` 原样复制，包括 0。
        不读取 ``total_tokens``。Token 为负数时，``Usage`` 抛出 ``ValidationError``，
        本函数不把该异常换成 ``None`` 或 0。
    """
    metadata = message.usage_metadata
    if metadata is None:
        return None
    return Usage(
        model=model,
        input_tokens=metadata["input_tokens"],
        output_tokens=metadata["output_tokens"],
    )


def raise_provider_failure(exc: BaseException) -> None:
    """供应商不可用时改抛领域异常，其余异常保持原样。

    超时和连接失败是 ``APIConnectionError``，429 是 ``RateLimitError``，5xx 是
    ``InternalServerError``。这三类都是 openai SDK 会重试的故障；重试次数用尽后
    仍然抛出它们。本函数不读取异常字符串，避免把密钥写进新异常。

    已经是 ``LLMUnavailableError`` 时原样再抛，不再包一层，这样原来的
    ``__cause__`` 还在。

    参数:
        exc: 模型调用或图执行抛出的异常。

    返回:
        无。不能归为模型不可用时直接返回，调用方继续处理原来的 ``exc``。

    异常:
        LLMUnavailableError: ``exc`` 本身就是该类型，或属于上面的供应商故障。
            新异常用 ``raise LLMUnavailableError(...) from exc`` 抛出，说明文字
            是固定短句。
    """
    if isinstance(exc, LLMUnavailableError):
        raise exc
    if isinstance(exc, _PROVIDER_UNAVAILABLE):
        raise LLMUnavailableError(LLM_UNAVAILABLE_MESSAGE) from exc
