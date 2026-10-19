"""图的状态。

这里只放一次执行需要在节点之间传递的数据。模型和配置不在这里，它们由
``AppContext`` 在每次调用时注入。
"""

import operator
from typing import Annotated, TypedDict

from minirag.contracts import AnswerStatus, ErrorInfo


class UsageRecord(TypedDict):
    """一次模型调用的用量。

    这是图内部的记录，不是返回给调用方的 ``Usage``。多次调用的汇总留在入口。
    用普通字典而不是 Pydantic 模型，是为了让追加后的列表保持可序列化的结构。

    参数:
        model: 本次调用使用的配置模型名，来自 ``Settings.chat_model``。
        input_tokens: 输入 Token 数。模型没有返回用量时为 ``None``，不是 0。
        output_tokens: 输出 Token 数。模型没有返回用量时为 ``None``，不是 0。

    返回:
        含上述三个键的字典。不包含 ``total_tokens``。
    """

    model: str
    input_tokens: int | None
    output_tokens: int | None


class AgentState(TypedDict, total=False):
    """S0 图在节点之间传递的状态。

    ``total=False`` 表示每个字段都可以暂时没有。节点只返回自己写出的字段，
    入口写入的 ``request_id`` 和 ``question`` 不会被聊天节点覆盖。

    参数:
        request_id: 本次请求标识。由入口写入，节点不修改。
        question: 交给聊天节点的问题原文。由入口写入，节点不修改。
        answer: 聊天节点写出的回复文本。后写的值覆盖先写的值。
        status: 结果状态。S0 的聊天节点不写这个字段。
        error: 错误信息。没有错误时可以不出现。S0 的聊天节点不写这个字段。
        usage_records: 各次模型调用的用量。新写入的列表追加到已有列表后面。

    返回:
        可以只包含部分字段的状态字典。
    """

    request_id: str
    question: str
    answer: str
    status: AnswerStatus
    error: ErrorInfo | None
    usage_records: Annotated[list[UsageRecord], operator.add]
