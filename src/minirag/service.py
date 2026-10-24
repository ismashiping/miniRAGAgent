"""问答入口。

``aask`` 先校验请求，再生成请求标识和会话标识，调用 S0 的 LangGraph 图，把
最终 State 组装成 ``AskResponse``。校验失败、模型不可用和未知异常都在这里收成
错误响应。``ask`` 只是同步包装。
"""

import asyncio
import logging
import time
import traceback
import uuid
from collections.abc import Mapping
from typing import Any, cast

from pydantic import ValidationError

from minirag.contracts import AskRequest, AskResponse, ErrorInfo, Usage
from minirag.errors import (
    LLMUnavailableError,
    error_info_for_exception,
    invalid_request_info,
)
from minirag.graph.builder import build_graph
from minirag.graph.context import AppContext
from minirag.graph.state import AgentState, UsageRecord
from minirag.llm.chat_model import raise_provider_failure
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


def _coerce_request(request: AskRequest | Mapping[str, Any]) -> AskRequest:
    """把入口收到的数据再校验成 ``AskRequest``。

    已经是 ``AskRequest`` 时仍 ``model_dump`` 后再校验。``model_construct`` 可以
    绕过构造时的校验，入口不能信任那一次。字典按字段规则校验，空白问题会在这里
    被去掉首尾空白后拒绝。

    参数:
        request: 调用方传入的请求。可以是已经构造的 ``AskRequest``，也可以是
            字段名到值的映射。

    返回:
        校验通过的 ``AskRequest``。问题的首尾空白已被去掉。

    异常:
        ValidationError: 问题为空、超过 2000 字符，或 ``top_k`` 不在 1 到 20。
            异常文本可能含有用户输入，调用方不要把它写进响应或日志。
    """
    if isinstance(request, AskRequest):
        raw: Mapping[str, Any] = request.model_dump()
    else:
        raw = request
    return AskRequest.model_validate(raw)


def _session_id_from_raw(request: AskRequest | Mapping[str, Any]) -> str | None:
    """在校验失败时取出还能用的会话标识。

    校验失败的请求不能整份信任，但字符串形式的 ``session_id`` 只是回显给调用方，
    不参与图。不是字符串时当作没提供，避免把非法值写进响应。

    参数:
        request: 校验失败前的原始请求，类型与 ``_coerce_request`` 的参数相同。

    返回:
        调用方给出的字符串，包括空字符串。没提供或类型不是字符串时返回 ``None``。
    """
    if isinstance(request, AskRequest):
        value: object = request.session_id
    elif isinstance(request, Mapping):
        value = request.get("session_id")
    else:
        return None
    if isinstance(value, str):
        return value
    return None


def _error_response(
    *,
    request_id: str,
    session_id: str,
    info: ErrorInfo,
    started: float,
) -> AskResponse:
    """组装一条错误响应。

    ``answer`` 与 ``error.message`` 使用同一句固定说明。``intent`` 为 ``None``：
    校验没通过，或图没有正常走完，S0 也还没有路由节点可以给出意图。

    参数:
        request_id: 本次请求标识。校验失败时也会新生成一个。
        session_id: 会话标识。调用方没提供可用字符串时由入口生成。
        info: 已经去掉内部细节的错误码和说明。
        started: ``time.perf_counter()`` 的起点，与 ``_elapsed_ms`` 使用同一时钟。

    返回:
        ``status`` 为 ``error`` 的 ``AskResponse``。``usage`` 为 ``None``，
        ``citations`` 和 ``degraded`` 为空。``latency_ms`` 从 ``started`` 算到
        这次组装。
    """
    return AskResponse(
        request_id=request_id,
        session_id=session_id,
        status="error",
        intent=None,
        answer=info.message,
        error=info,
        usage=None,
        latency_ms=_elapsed_ms(started),
    )


def _log_unhandled(exc: BaseException) -> None:
    """把未知异常的堆栈写入日志，不写异常自己的文本。

    ``logger.exception`` 会把 ``str(exc)`` 打出来。供应商和内部异常的文本可能
    含有密钥或用户输入，所以这里只用 ``traceback.format_tb``。帧里是源代码行，
    不是异常消息。

    参数:
        exc: 未能归类的异常。使用它的类型名和 ``__traceback__``。

    返回:
        无。
    """
    stack = "".join(traceback.format_tb(exc.__traceback__))
    logger.error(
        "未处理的异常 %s，错误码 internal_error\nTraceback (most recent call last):\n%s",
        type(exc).__name__,
        stack,
    )


def _elapsed_ms(started: float) -> int:
    """把从 ``started`` 到现在的时间收成非负的整数毫秒。

    参数:
        started: ``time.perf_counter()`` 返回的起点。必须和现在同一次单调时钟。

    返回:
        向下取整后的毫秒数。很快的调用可以是 0，不会是负数。
    """
    return int((time.perf_counter() - started) * 1000)


async def aask(
    request: AskRequest | Mapping[str, Any],
    context: AppContext,
) -> AskResponse:
    """执行一次问答并返回组装好的响应。

    顺序是：开始计时，安装日志过滤器，生成 ``request_id``，再校验请求。校验失败
    直接返回 ``invalid_request``，不调用图，也不调用模型。通过之后，缺省时生成
    ``session_id``，把标识放进日志上下文，再调用图。初始 State 只有 ``request_id``
    和 ``question``。``user_id`` 与 ``top_k`` 留在请求对象上，S0 的 State 没有
    这两个字段。图返回后，``answer`` 原样写入响应，``usage_records`` 交给
    ``summarize_usage``。成功时 ``status`` 为 ``answered``，``intent`` 为
    ``chat``，因为 S0 还没有路由节点，聊天节点也不写这两个字段。

    图里抛出的供应商超时、连接失败、429 和 5xx，先交给 ``raise_provider_failure``
    转成 ``LLMUnavailableError``，再映射为 ``llm_unavailable``。其他异常映射为
    ``internal_error``，堆栈写入日志，异常原文不写入日志和响应。两种错误的
    ``intent`` 都是 ``None``。

    本函数不读取环境变量，也不调用 ``build_chat_model``。模型和配置都来自
    ``context``。每次调用都 ``build_graph()``。这张图没有检查点，依赖在
    ``ainvoke`` 时传入，所以编译结果不需要留到下一次请求。

    参数:
        request: 问答请求。可以是 ``AskRequest``，也可以是字段映射。两种都会在
            本函数里再校验一次。``session_id`` 为 ``None`` 或映射里没有该键时由
            本函数生成；传入空字符串或空白时原样返回，不把它们当成缺省。
        context: 本次图运行的依赖，至少包含 ``settings`` 和 ``chat_model``。
            测试传入 Fake 模型。本函数不在缺省时自己构造模型。校验失败时不会
            用到它。

    返回:
        ``AskResponse``。``request_id`` 是新生成的 UUID 字符串。成功时
        ``error`` 为 ``None``。失败时 ``status`` 为 ``error``，``answer`` 与
        ``error.message`` 是同一句固定说明。``latency_ms`` 从进入本函数算到
        响应字段组装完成，不含最后一条“问答完成”日志。非知识问答的
        ``citations`` 和 ``degraded`` 为空。

    异常:
        不把校验失败和模型故障继续向外抛。``asyncio.CancelledError`` 不是
        ``Exception`` 的子类，取消请求时仍会向外抛。离开 ``request_id`` 上下文
        时标识会恢复。
    """
    started = time.perf_counter()
    configure_logging()
    request_id = str(uuid.uuid4())
    try:
        parsed = _coerce_request(request)
    except ValidationError:
        session_id = _session_id_from_raw(request)
        if session_id is None:
            session_id = str(uuid.uuid4())
        with request_id_context(request_id):
            logger.info("请求校验失败")
            return _error_response(
                request_id=request_id,
                session_id=session_id,
                info=invalid_request_info(),
                started=started,
            )
    if parsed.session_id is None:
        session_id = str(uuid.uuid4())
    else:
        session_id = parsed.session_id
    with request_id_context(request_id):
        logger.info("开始问答")
        try:
            graph = build_graph()
            # langgraph 1.2.11 把 ainvoke 的返回类型标成普通 dict。运行时它就是
            # 本次图的 State，这里只告诉类型检查器按 AgentState 使用。
            state = cast(
                AgentState,
                await graph.ainvoke(
                    {"request_id": request_id, "question": parsed.question},
                    context=context,
                ),
            )
        # 入口边界：未知异常要变成 internal_error 并留下堆栈，不能变成 None。
        # Python 3.10 的 CancelledError 不是 Exception，取消仍会向外抛。
        except Exception as exc:  # noqa: BLE001
            try:
                raise_provider_failure(exc)
            except LLMUnavailableError as domain:
                logger.warning(
                    "模型不可用，错误码 llm_unavailable，异常类型 %s",
                    type(exc).__name__,
                )
                info = error_info_for_exception(domain)
            else:
                _log_unhandled(exc)
                info = error_info_for_exception(exc)
            return _error_response(
                request_id=request_id,
                session_id=session_id,
                info=info,
                started=started,
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


def ask(
    request: AskRequest | Mapping[str, Any],
    context: AppContext,
) -> AskResponse:
    """同步调用 ``aask``。

    没有运行中的事件循环	进入 except	使用 asyncio.run() 执行问答
    已有运行中的事件循环	跳过 except	主动抛出 RuntimeError 告诉调用方不要用 asyncio.run()

    参数:
        request: 传给 ``aask`` 的问答请求。字段含义与 ``aask`` 相同。
        context: 传给 ``aask`` 的图依赖。字段含义与 ``aask`` 相同。

    返回:
        与同一次 ``aask`` 相同的响应字段。两次调用各自生成 ``request_id``，
        耗时也可能不同。校验失败和模型故障也是返回值，不是抛出的异常。

    异常:
        RuntimeError: 当前线程已有运行中的事件循环。本函数先检查循环，再创建
            协程；若先调用 ``aask`` 再把结果交给失败的 ``asyncio.run``，协程不会
            被等待，解释器会给出 ``RuntimeWarning``。
    """
    try:
        asyncio.get_running_loop()  # 获取当前线程中正在运行的事件循环
    except RuntimeError:
        return asyncio.run(aask(request, context))
    raise RuntimeError("asyncio.run() cannot be called from a running event loop")
