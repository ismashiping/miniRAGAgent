"""S0 聊天节点。

根据注入的模型生成一段文本回答，并记下这一次调用的用量。
"""

from typing import TypedDict

from langgraph.runtime import Runtime

from minirag.graph.context import AppContext
from minirag.graph.state import AgentState, UsageRecord
from minirag.llm.chat_model import usage_from_ai_message
from minirag.llm.prompts import render_chat_prompt


class RespondChatUpdate(TypedDict):
    """``respond_chat`` 写回图的那一部分状态。

    参数:
        answer: 模型回复的文本。空字符串和首尾空白都原样保留。
        usage_records: 只包含本次调用的一条用量。图会把它追加到已有列表。

    返回:
        恰好包含这两个键的字典。
    """

    answer: str
    usage_records: list[UsageRecord]


async def respond_chat(
    state: AgentState,
    runtime: Runtime[AppContext],
) -> RespondChatUpdate:
    """用上下文里的模型回答 ``state["question"]``。

    模型和模型名都来自 ``runtime.context``。本函数不调用 ``build_chat_model``，
    也不构造 ``Settings``，因此不会读取环境变量或 ``.env``。

    执行顺序是：取出问题，渲染系统消息和用户消息，再 ``ainvoke``。回复的
    ``content`` 必须是字符串。用量交给 ``usage_from_ai_message``：有元数据时
    保留 Token 数，包括 0；没有时两个 Token 字段为 ``None``。两种情况都返回
    一条记录，这样入口才能区分“没有调用模型”和“调用了但没有用量”。

    参数:
        state: 当前图状态。必须包含 ``question``。本函数不读取其他字段。
        runtime: LangGraph 在运行节点时注入的对象。``runtime.context`` 必须是
            带有 ``settings`` 和 ``chat_model`` 的 ``AppContext``。单测可以直接
            构造 ``Runtime(context=...)``，不必先编译整张图。

    返回:
        ``answer`` 与 ``usage_records``。不返回 ``question``、``request_id``、
        ``status`` 或 ``error``，这些字段因此保持调用前的值或继续空着。

    异常:
        KeyError: ``state`` 没有 ``question``。此时还没有调用模型。
        TypeError: 回复的 ``content`` 不是字符串。此时模型已经被调用。
        Exception: 模型调用失败时，原异常继续向外抛，不包装，也不写日志。
    """
    question = state["question"]
    messages = render_chat_prompt(question)
    context = runtime.context
    message = await context.chat_model.ainvoke(messages)
    content = message.content
    if not isinstance(content, str):
        raise TypeError("respond_chat 只接受字符串回复")
    model_name = context.settings.chat_model
    usage = usage_from_ai_message(message, model=model_name)
    if usage is None:
        record: UsageRecord = {
            "model": model_name,
            "input_tokens": None,
            "output_tokens": None,
        }
    else:
        record = {
            "model": usage.model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
    return {"answer": content, "usage_records": [record]}
