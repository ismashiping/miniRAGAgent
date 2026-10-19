"""一次图运行的依赖。

依赖放在这里，而不是放进 ``AgentState``，这样测试可以替换模型，以后的检查点
也不会把模型和密钥一起保存。
"""

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from minirag.config import Settings


@dataclass(frozen=True)
class AppContext:
    """节点通过 LangGraph ``Runtime`` 拿到的依赖。

    冻结的是这一组引用：调用开始后不能把 ``chat_model`` 换成另一个对象。
    模型自己的内部计数仍然可以变化。本类不读取环境变量，也不创建模型。

    参数:
        settings: 本次运行的配置。聊天节点只用它的 ``chat_model`` 作为用量里的模型名。
        chat_model: 本次运行的聊天模型。生产代码传入 ``BaseChatModel``，测试传入 Fake。

    返回:
        供 ``graph.ainvoke(..., context=...)`` 使用的上下文。
    """

    settings: Settings
    chat_model: BaseChatModel
