"""组装 S0 的最小图。

图里只有一条路径：开始，聊天节点，结束。模型不在组装时绑定，而在每次
``ainvoke`` 时通过 ``context`` 传入。
"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from minirag.graph.context import AppContext
from minirag.graph.nodes.chat import respond_chat
from minirag.graph.state import AgentState


def build_graph() -> CompiledStateGraph[AgentState, AppContext, AgentState, AgentState]:
    """编译 ``START → respond_chat → END``。

    不传入 Checkpointer 或 Store。同一次进程里的两次 ``ainvoke`` 不会共享状态。

    返回:
        已编译的图。调用 ``ainvoke(state, context=AppContext(...))`` 执行。
        没有参数。模型、配置和问题都不在这里决定。
    """
    graph: StateGraph[AgentState, AppContext, AgentState, AgentState] = StateGraph(
        AgentState,
        context_schema=AppContext,
    )
    graph.add_node("respond_chat", respond_chat)
    graph.add_edge(START, "respond_chat")
    graph.add_edge("respond_chat", END)
    return graph.compile()
