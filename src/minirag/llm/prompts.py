"""S0 聊天 Prompt。

证据、路由和改写 Prompt 留到后续任务。本模块不调用模型。
"""

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate

# 系统文本不含花括号。ChatPromptTemplate 默认按 f-string 解析模板，花括号会被
# 当成变量。用户问题放在 {question} 的值里，值本身不会再次解析。
CHAT_SYSTEM_PROMPT = (
    "你是 MiniRAG 的对话助手。请直接回答用户的问题。"
    "不要声称查阅了知识库，不要编造引用。"
)


def build_chat_prompt() -> ChatPromptTemplate:
    """构造只含系统指令和用户问题的聊天 Prompt。

    返回:
        ``ChatPromptTemplate``。它是 Runnable，``invoke`` 的输入需要包含
        ``question``。每次调用都返回新模板。渲染结果是一条系统消息和一条用户消息。
    """
    return ChatPromptTemplate.from_messages(
        [
            ("system", CHAT_SYSTEM_PROMPT),
            ("human", "{question}"),
        ]
    )


def render_chat_prompt(question: str) -> list[BaseMessage]:
    """把问题渲染成系统消息和用户消息。

    参数:
        question: 放进用户消息的原文。本函数不去掉空白，也不检查长度；长度和
            空白由 ``AskRequest`` 负责。

    返回:
        长度为 2 的列表。第一条是 ``SystemMessage``，内容固定为聊天系统指令。
        第二条是 ``HumanMessage``，内容等于 ``question``。问题里的花括号按字面保留。
    """
    return build_chat_prompt().format_messages(question=question)
