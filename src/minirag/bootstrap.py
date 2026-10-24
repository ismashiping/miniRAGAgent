"""组装进程要用的依赖。

S0 只把配置和聊天模型放进 ``AppContext``。向量库、检索和重排以后仍加在本模块，
CLI 和 FastAPI 都调用这里，避免各写一套创建代码。本模块不发起网络请求。
"""

from minirag.config import Settings
from minirag.graph.context import AppContext
from minirag.llm.chat_model import build_chat_model


def build_app_context(settings: Settings) -> AppContext:
    """用已经校验过的配置组装 S0 的运行上下文。

    本函数调用 ``build_chat_model``。那个函数只构造客户端，不调用模型，也不连接
    ``base_url``。本函数同样不调用 ``invoke`` 或 ``ainvoke``，也不读取环境变量
    或 ``.env``。配置从哪来由调用方决定，因此测试可以传入一份不碰本机文件的
    ``Settings``。

    参数:
        settings: 聊天模型配置。原样放进返回的上下文，不复制，也不重新加载。
            读取 ``chat_model``、``base_url``、``api_key``、``timeout`` 和
            ``max_retries`` 的是 ``build_chat_model``。

    返回:
        ``settings`` 与对应 ``ChatOpenAI`` 组成的 ``AppContext``。``chat_model``
        的静态类型是 ``BaseChatModel``。返回前不会产生回答。
    """
    return AppContext(settings=settings, chat_model=build_chat_model(settings))


def load_app_context() -> AppContext:
    """从环境变量和当前工作目录的 ``.env`` 读取配置，再组装上下文。

    这是 CLI 的默认组装函数。测试传入自己的工厂时不会调用本函数，因此不必准备
    真实密钥。本函数不捕获配置错误，也不创建向量库客户端。

    参数:
        无。

    返回:
        ``build_app_context(Settings())`` 的结果。``Settings`` 使用它自己的来源
        顺序：构造参数、环境变量，然后是 ``.env``。

    异常:
        ValidationError: 必填配置缺失、只有空白，或超时与重试越界。``Settings``
        已隐藏错误文本中的输入值，本函数不再包装这个异常。
    """
    # mypy 没有启用 Pydantic 插件，看不到环境变量会填上必填字段。
    settings = Settings()  # type: ignore[call-arg]
    return build_app_context(settings)
