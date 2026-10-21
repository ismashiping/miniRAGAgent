"""问答入口。

``aask`` 生成请求标识和会话标识，调用 S0 的 LangGraph 图，再把最终 State
组装成 ``AskResponse``。``ask`` 只是同步包装。模型异常继续向外抛，不在这里
映射成错误响应。
"""

import asyncio
import logging
import time
import uuid
from typing import cast

from minirag.contracts import AskRequest, AskResponse, Usage
from minirag.graph.builder import build_graph
from minirag.graph.context import AppContext
from minirag.graph.state import AgentState, UsageRecord
from minirag.logging_setup import configure_logging, request_id_context

logger = logging.getLogger(__name__)


def summarize_usage(records: list[UsageRecord]) -> Usage | None:
    """把图里的用量记录汇总成响应中的一个 ``Usage``。

    没有记录时返回 ``None``。这时没有模型名可以填写，把 Token 写成 0 会把
    “没有调用模型”说成“调用过且用量为 0”。任一记录缺少输入或输出 Token 时，
    整次请求的 ``usage`` 也是 ``None``，不能只用其中有数字的那几条。记录上的
    模型名不一致时同样返回 ``None``：``Usage`` 只有一个 ``model`` 字段，不能把
    别的模型的 Token 记到其中一个名字下面。

    参数:
        records: 图状态里的 ``usage_records``。每条包含模型名、输入 Token 和
            输出 Token。Token 缺失时是 ``None``，不是 0。

    返回:
        全部记录都有 Token 且模型名相同的 ``Usage``。0 会原样加进去。无法按
        上面的规则汇总时返回 ``None``。
    """
    if not records:
        return None
    model_name = records[0]["model"]
    input_tokens = 0
    output_tokens = 0
    for record in records:
        record_input = record["input_tokens"]
        record_output = record["output_tokens"]
        if (
            record["model"] != model_name
            or record_input is None
            or record_output is None
        ):
            return None
        input_tokens += record_input
        output_tokens += record_output
    return Usage(
        model=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _elapsed_ms(started: float) -> int:
    """把从 ``started`` 到现在的时间收成非负的整数毫秒。

    参数:
        started: ``time.perf_counter()`` 返回的起点。必须和现在同一次单调时钟。

    返回:
        向下取整后的毫秒数。很快的调用可以是 0，不会是负数。
    """
    return int((time.perf_counter() - started) * 1000)


async def aask(request: AskRequest, context: AppContext) -> AskResponse:
    """执行一次问答并返回组装好的响应。

    顺序是：开始计时，安装日志过滤器，生成 ``request_id``，缺省时生成
    ``session_id``，把标识放进日志上下文，再调用图。初始 State 只有 ``request_id``
    和 ``question``。``user_id`` 与 ``top_k`` 留在请求对象上，S0 的 State 没有
    这两个字段。图返回后，``answer`` 原样写入响应，``usage_records`` 交给
    ``summarize_usage``。``status`` 固定为 ``answered``，``intent`` 固定为
    ``chat``，因为 S0 还没有路由节点，聊天节点也不写这两个字段。

    本函数不读取环境变量，也不调用 ``build_chat_model``。模型和配置都来自
    ``context``。每次调用都 ``build_graph()``。这张图没有检查点，依赖在
    ``ainvoke`` 时传入，所以编译结果不需要留到下一次请求。

    参数:
        request: 已经通过校验的问答请求。问题里的首尾空白在构造这个对象时已经
            去掉。``session_id`` 为 ``None`` 时由本函数生成；传入空字符串或
            空白时原样返回，不把它们当成缺省。
        context: 本次图运行的依赖，至少包含 ``settings`` 和 ``chat_model``。
            测试传入 Fake 模型。本函数不在缺省时自己构造模型。

    返回:
        ``AskResponse``。``request_id`` 是新生成的 UUID 字符串。``latency_ms``
        从进入本函数算到响应字段组装完成，不含最后一条“问答完成”日志。非知识
        问答的 ``citations`` 和 ``degraded`` 为空，``error`` 为 ``None``。

    异常:
        Exception: 图或模型抛出的异常原样继续抛出，不记录堆栈，也不改成错误
            响应。离开函数前日志上下文会恢复。错误码映射不在本任务。
    """
    started = time.perf_counter()
    configure_logging()
    request_id = str(uuid.uuid4())
    if request.session_id is None:
        session_id = str(uuid.uuid4())
    else:
        session_id = request.session_id
    with request_id_context(request_id):
        logger.info("开始问答")
        graph = build_graph()
        # langgraph 1.2.11 把 ainvoke 的返回类型标成普通 dict。运行时它就是
        # 本次图的 State，这里只告诉类型检查器按 AgentState 使用。
        state = cast(
            AgentState,
            await graph.ainvoke(
                {"request_id": request_id, "question": request.question},
                context=context,
            ),
        )
        usage_records = state.get("usage_records", [])
        response = AskResponse(
            request_id=request_id,
            session_id=session_id,
            status="answered",
            intent="chat",
            answer=state["answer"],
            usage=summarize_usage(usage_records),
            latency_ms=_elapsed_ms(started),
        )
        logger.info("问答完成")
        return response


def ask(request: AskRequest, context: AppContext) -> AskResponse:
    """同步调用 ``aask``。

    没有运行中的事件循环	进入 except	使用 asyncio.run() 执行问答
    已有运行中的事件循环	跳过 except	主动抛出 RuntimeError 告诉调用方不要用 asyncio.run()

    参数:
        request: 传给 ``aask`` 的问答请求。字段含义与 ``aask`` 相同。
        context: 传给 ``aask`` 的图依赖。字段含义与 ``aask`` 相同。

    返回:
        与同一次 ``aask`` 相同的响应字段。两次调用各自生成 ``request_id``，
        耗时也可能不同。

    异常:
        RuntimeError: 当前线程已有运行中的事件循环。本函数先检查循环，再创建
            协程；若先调用 ``aask`` 再把结果交给失败的 ``asyncio.run``，协程不会
            被等待，解释器会给出 ``RuntimeWarning``。
        Exception: ``aask`` 抛出的异常继续向外抛，不在这里捕获。
    """
    try:
        asyncio.get_running_loop()#获取当前线程中正在运行的事件循环
    except RuntimeError:
        return asyncio.run(aask(request, context))
    raise RuntimeError("asyncio.run() cannot be called from a running event loop")
