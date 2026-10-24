"""命令行传输层。

这里只解析参数、取得依赖、调用 ``ask``、把响应写到标准输出，并用退出码表示成败。
不创建模型，不校验问题文本，也不访问向量库。问题是否合法由 ``ask`` 决定。
"""

import argparse
import logging
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

from pydantic import ValidationError

from minirag.bootstrap import load_app_context
from minirag.contracts import AskResponse
from minirag.graph.context import AppContext
from minirag.logging_setup import RequestIdFormatter, configure_logging
from minirag.service import ask

ContextFactory = Callable[[], AppContext]
_CONFIG_ERROR_MESSAGE = (
    "配置无效或缺少必填项。请设置 MINIRAG_CHAT_MODEL、"
    "MINIRAG_BASE_URL 和 MINIRAG_API_KEY。"
)
_EXIT_OK = 0
_EXIT_ERROR = 1


def _build_parser() -> argparse.ArgumentParser:
    """构造本阶段唯一的 ``ask`` 子命令解析器。

    ``question`` 原样保留，包括首尾空白。去掉空白和长度限制是 ``AskRequest`` 的
    规则，不在解析器里再写一遍。``--json`` 只改变输出格式。

    参数:
        无。

    返回:
        ``prog`` 为 ``minirag`` 的解析器。子命令是必填的。未实现的命令会在解析
        阶段被拒绝。
    """
    parser = argparse.ArgumentParser(prog="minirag", description="MiniRAG 命令行。")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ask_parser = subparsers.add_parser("ask", help="向聊天模型提一个问题")
    ask_parser.add_argument("question", help="问题文本")
    ask_parser.add_argument(
        "--json",
        action="store_true",
        help="向标准输出打印完整的 AskResponse JSON",
    )
    return parser


@contextmanager
def _cli_logging() -> Iterator[None]:
    """在本次命令执行期间把 ``minirag`` 的 INFO 日志写到标准错误。

    回答和 JSON 占用标准输出，日志不能跟它们混在同一条流里。只给名为
    ``minirag`` 的 logger 临时加一个 handler，并把它的级别设为 INFO。离开
    ``with`` 时卸下 handler，级别恢复成进入前的值，避免影响同进程里的其他测试。

    不调用 ``StreamHandler.close()``。那个方法会关闭它持有的流，而这里的流是
    ``sys.stderr``，关掉后进程就无法再输出错误。

    参数:
        无。

    返回:
        无返回值。``with`` 块内项目日志写到当时的 ``sys.stderr``，块结束后
        handler 和级别都回到进入前。
    """
    project_logger = logging.getLogger("minirag")
    previous_level = project_logger.level
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RequestIdFormatter())
    project_logger.addHandler(handler)
    project_logger.setLevel(logging.INFO)
    configure_logging()
    try:
        yield
    finally:
        handler.flush()
        project_logger.removeHandler(handler)
        project_logger.setLevel(previous_level)


def _write_response(response: AskResponse, *, as_json: bool) -> None:
    """把一次问答的结果写到标准输出。

    文本模式只写 ``answer``。错误响应的 ``answer`` 已经是面向用户的短句，
    所以失败时也不改写到标准错误。JSON 模式写完整响应，中文不转成 ``\\u`` 转义。

    参数:
        response: ``ask`` 返回的响应。本函数不修改它，也不根据 ``status`` 决定
            写不写。
        as_json: 为真时输出 JSON。为假时只输出回答文本。

    返回:
        无。两种模式都通过 ``print`` 在末尾加一个换行。
    """
    if as_json:
        print(response.model_dump_json(ensure_ascii=False))
        return
    print(response.answer)


def main(
    argv: Sequence[str] | None = None,
    *,
    context_factory: ContextFactory = load_app_context,
) -> int:
    """执行一次命令行问答。

    解析在组装依赖之前完成。用法错误由 argparse 直接以状态码 2 退出，此时还没有
    读取配置。解析成功后调用 ``context_factory``。默认工厂读取环境并创建聊天模型；
    测试传入返回 Fake 上下文的工厂，本函数就不会创建模型。配置无法构造时向标准
    错误打印固定说明并返回 1，不打印异常原文。

    拿到上下文后把问题原样交给 ``ask``。``ask`` 负责校验、调用图和错误映射。
    本函数只按 ``status`` 决定退出码：``error`` 为 1，其余为 0。标准输出是回答
    或完整 JSON。

    参数:
        argv: 不含解释器和谐程序名的参数，例如 ``["ask", "你好"]``。``None``
            时交给 argparse 读取 ``sys.argv[1:]``。``context_factory`` 只能用
            关键字传入。
        context_factory: 无参可调用对象，返回本次命令使用的 ``AppContext``。
            省略时使用 ``load_app_context``。

    返回:
        ``0`` 表示响应状态不是 ``error``。``1`` 表示 ``status`` 为 ``error``，
        或组装依赖时配置无效。问答失败时标准输出仍是 ``answer`` 或完整 JSON。
        配置无效时标准输出为空，固定说明写在标准错误。

    异常:
        SystemExit: 缺少子命令、命令未知或 ``ask`` 缺少问题时，argparse 以状态码
            2 退出。本函数不把它改写成返回值。
        ValidationError: 不向外抛出。组装函数抛出的该异常视为配置失败。
        其他异常: 组装函数或 ``ask`` 意外失败时原样向外抛，不收成退出码 1。
            ``ask`` 自己会把模型和校验失败收成响应，正常路径不会把那些失败抛出来。
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command
    question = args.question
    if (
        not isinstance(command, str)
        or command != "ask"
        or not isinstance(question, str)
    ):
        parser.error("无法解析 ask 命令")
    as_json = bool(args.json)
    with _cli_logging():
        try:
            context = context_factory()
        except ValidationError:
            print(_CONFIG_ERROR_MESSAGE, file=sys.stderr)
            return _EXIT_ERROR
        response = ask({"question": question}, context)
        _write_response(response, as_json=as_json)
        if response.status == "error":
            return _EXIT_ERROR
        return _EXIT_OK
