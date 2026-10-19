"""构造聊天模型，并把单次回复的用量转成契约中的 ``Usage``。

本模块属于领域层。它只依赖配置和问答契约，不导入图或服务入口，也不发起网络请求。
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from minirag.config import Settings
from minirag.contracts import Usage


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
