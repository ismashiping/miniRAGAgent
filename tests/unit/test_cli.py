"""CLI 只解析参数、调用组装函数和 ask，并用退出码表示成败。"""

import json
import logging
import runpy
import socket
from pathlib import Path

import httpx
import openai
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage

from minirag.cli import main
from minirag.config import Settings
from minirag.contracts import AskResponse
from minirag.graph.context import AppContext

_API_KEY = "sk-test-secret-value"
_ANSWER = "离线回答正文"
_INVALID_REQUEST_MESSAGE = "请求参数不合法。"
_LLM_UNAVAILABLE_MESSAGE = "模型暂时不可用，请稍后重试。"
_CONFIG_ERROR_MESSAGE = (
    "配置无效或缺少必填项。请设置 MINIRAG_CHAT_MODEL、"
    "MINIRAG_BASE_URL 和 MINIRAG_API_KEY。"
)
_ENV_NAMES = (
    "MINIRAG_CHAT_MODEL",
    "MINIRAG_BASE_URL",
    "MINIRAG_API_KEY",
    "MINIRAG_TIMEOUT",
    "MINIRAG_MAX_RETRIES",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "OPENAI_BASE_URL",
)
_RESPONSE_FIELDS = {
    "request_id",
    "session_id",
    "status",
    "intent",
    "answer",
    "citations",
    "degraded",
    "error",
    "usage",
    "latency_ms",
}


class ExplodingChatModel(BaseChatModel):
    """调用时抛出给定异常，并记下调用次数。"""

    calls: int = 0
    boom: Exception

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object | None = None,
        **kwargs: object,
    ) -> object:
        self.calls += 1
        raise self.boom

    @property
    def _llm_type(self) -> str:
        return "exploding-chat-model"


@pytest.fixture
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """若 CLI 在缺少配置时仍去连接模型，则本测试失败。"""

    def _reject(operation: str):
        def _fail(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(f"CLI 不应访问网络，但调用了 {operation}")

        return _fail

    monkeypatch.setattr(
        socket, "create_connection", _reject("socket.create_connection")
    )
    monkeypatch.setattr(socket.socket, "connect", _reject("socket.socket.connect"))
    monkeypatch.setattr(socket, "getaddrinfo", _reject("socket.getaddrinfo"))


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return Settings(
        _env_file=None,
        chat_model="demo-chat",
        base_url="https://example.com/v1",
        api_key=_API_KEY,
    )


def _model(text: str) -> FakeMessagesListChatModel:
    """两条回复。只有一条时，调用一次后计数会回到 0。"""
    message = AIMessage(
        content=text,
        usage_metadata={
            "input_tokens": 4,
            "output_tokens": 6,
            "total_tokens": 10,
        },
    )
    return FakeMessagesListChatModel(responses=[message, message])


def _context(
    monkeypatch: pytest.MonkeyPatch,
    model: BaseChatModel | None = None,
) -> tuple[AppContext, BaseChatModel]:
    chat_model = _model(_ANSWER) if model is None else model
    return AppContext(
        settings=_settings(monkeypatch), chat_model=chat_model
    ), chat_model


def _forbid_model_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("CLI 不应创建聊天模型")

    monkeypatch.setattr("minirag.llm.chat_model.build_chat_model", _forbidden)
    monkeypatch.setattr("minirag.bootstrap.build_chat_model", _forbidden)
    monkeypatch.setattr("minirag.cli.build_chat_model", _forbidden, raising=False)


def test_main_ask_prints_answer_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context, model = _context(monkeypatch)
    _forbid_model_construction(monkeypatch)

    code = main(["ask", "你好"], context_factory=lambda: context)

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.splitlines() == [_ANSWER]
    assert "request_id" not in captured.out
    assert _API_KEY not in captured.out
    assert _API_KEY not in captured.err
    assert "开始问答" in captured.err
    assert "问答完成" in captured.err
    assert _ANSWER not in captured.err
    assert isinstance(model, FakeMessagesListChatModel)
    assert model.i == 1


def test_main_strips_question_via_ask(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context, model = _context(monkeypatch)

    code = main(["ask", "  你好  "], context_factory=lambda: context)

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [_ANSWER]
    assert isinstance(model, FakeMessagesListChatModel)
    assert model.i == 1


def test_main_json_prints_complete_ask_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context, _model_instance = _context(monkeypatch)

    code = main(["ask", "你好", "--json"], context_factory=lambda: context)

    captured = capsys.readouterr()
    assert code == 0
    assert _ANSWER in captured.out
    payload = json.loads(captured.out)
    assert set(payload) == _RESPONSE_FIELDS
    response = AskResponse.model_validate(payload)
    assert response.status == "answered"
    assert response.intent == "chat"
    assert response.answer == _ANSWER
    assert response.error is None
    assert response.citations == []
    assert response.degraded == []
    assert response.usage is not None
    assert response.usage.model == "demo-chat"
    assert response.usage.input_tokens == 4
    assert response.usage.output_tokens == 6
    assert response.latency_ms >= 0
    assert response.request_id
    assert response.session_id
    assert _API_KEY not in captured.out
    assert _API_KEY not in captured.err


def test_main_error_status_returns_one_without_calling_model(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context, model = _context(monkeypatch)

    code = main(["ask", "   "], context_factory=lambda: context)

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out.splitlines() == [_INVALID_REQUEST_MESSAGE]
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err
    assert _API_KEY not in captured.out
    assert _API_KEY not in captured.err
    assert _ANSWER not in captured.out
    assert isinstance(model, FakeMessagesListChatModel)
    assert model.i == 0


def test_main_json_error_returns_one_and_full_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context, model = _context(monkeypatch)

    code = main(["ask", "--json", "   "], context_factory=lambda: context)

    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    response = AskResponse.model_validate(payload)
    assert set(payload) == _RESPONSE_FIELDS
    assert response.status == "error"
    assert response.intent is None
    assert response.answer == _INVALID_REQUEST_MESSAGE
    assert response.error is not None
    assert response.error.code == "invalid_request"
    assert response.error.message == _INVALID_REQUEST_MESSAGE
    assert _API_KEY not in captured.out
    assert "Traceback" not in captured.err
    assert isinstance(model, FakeMessagesListChatModel)
    assert model.i == 0


def test_main_provider_failure_returns_safe_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    model = ExplodingChatModel(
        boom=openai.APIConnectionError(
            message=f"connect {_API_KEY}",
            request=request,
        )
    )
    context, _ = _context(monkeypatch, model)

    code = main(["ask", "你好"], context_factory=lambda: context)

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out.splitlines() == [_LLM_UNAVAILABLE_MESSAGE]
    assert model.calls == 1
    assert _API_KEY not in captured.out
    assert _API_KEY not in captured.err
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_main_missing_config_returns_one_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    block_network: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MINIRAG_API_KEY", _API_KEY)

    code = main(["ask", "你好"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.splitlines() == [_CONFIG_ERROR_MESSAGE]
    assert _API_KEY not in captured.err
    assert "Traceback" not in captured.err


def test_main_does_not_swallow_unexpected_factory_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> AppContext:
        raise RuntimeError("factory-boom")

    with pytest.raises(RuntimeError, match="factory-boom"):
        main(["ask", "你好"], context_factory=_boom)


def test_main_removes_cli_log_handler(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context, _model_instance = _context(monkeypatch)
    project_logger = logging.getLogger("minirag")
    before_handlers = list(project_logger.handlers)
    before_level = project_logger.level

    code = main(["ask", "你好"], context_factory=lambda: context)

    assert code == 0
    assert project_logger.handlers == before_handlers
    assert project_logger.level == before_level
    capsys.readouterr()


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["ingest", "docs"],
    ],
)
def test_main_usage_error_exits_two(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(argv)

    assert exc_info.value.code == 2


def test_module_entry_exits_with_cli_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_main(
        argv: list[str] | None = None, *, context_factory: object = None
    ) -> int:
        del argv, context_factory
        return 3

    monkeypatch.setattr("minirag.cli.main", _fake_main)
    monkeypatch.setattr(
        "minirag.bootstrap.load_app_context",
        lambda: (_ for _ in ()).throw(AssertionError("入口测试不应组装真实依赖")),
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("minirag", run_name="__main__")

    assert exc_info.value.code == 3
