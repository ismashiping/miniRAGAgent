"""入口把失败收成错误响应。

非法请求不进入图。供应商的超时、连接、限流和 5xx 变成 ``llm_unavailable``。
其余异常变成 ``internal_error``。响应里只有固定说明，堆栈留在日志中。
"""

import logging
import uuid

import httpx
import openai
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage

from minirag.config import Settings
from minirag.contracts import AskRequest
from minirag.graph.context import AppContext
from minirag.logging_setup import request_id_var
from minirag.service import aask, ask

_API_KEY = "sk-test-secret-value"
_INVALID_REQUEST_MESSAGE = "请求参数不合法。"
_LLM_UNAVAILABLE_MESSAGE = "模型暂时不可用，请稍后重试。"
_INTERNAL_ERROR_MESSAGE = "服务内部出错，请稍后重试。"
_ENV_NAMES = (
    "MINIRAG_CHAT_MODEL",
    "MINIRAG_BASE_URL",
    "MINIRAG_API_KEY",
    "MINIRAG_TIMEOUT",
    "MINIRAG_MAX_RETRIES",
)


class ExplodingChatModel(BaseChatModel):
    """调用时抛出构造时给定的异常，并记下调用次数。"""

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


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return Settings(
        _env_file=None,
        chat_model="demo-chat",
        base_url="https://example.com/v1",
        api_key=_API_KEY,
    )


def _context(settings: Settings, model: BaseChatModel) -> AppContext:
    return AppContext(settings=settings, chat_model=model)


def _fake_model(text: str) -> FakeMessagesListChatModel:
    """两条回复。只准备一条时，调用一次后 ``i`` 会回到 0，看不出有没有调用。"""
    return FakeMessagesListChatModel(
        responses=[
            AIMessage(content=text),
            AIMessage(content="第二条不会被本次调用使用"),
        ]
    )


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.com/v1/chat/completions")


def _status_error(status_code: int, exc_type: type[openai.APIStatusError]) -> Exception:
    response = httpx.Response(status_code, request=_request())
    return exc_type(f"status {status_code} {_API_KEY}", response=response, body=None)


def _service_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name.startswith("minirag.")]


def _assert_error_shape(response: object, code: str, message: str) -> None:
    assert response.status == "error"
    assert response.intent is None
    assert response.answer == message
    assert response.error is not None
    assert response.error.code == code
    assert response.error.message == message
    assert response.citations == []
    assert response.degraded == []
    assert response.usage is None
    assert type(response.latency_ms) is int
    assert response.latency_ms >= 0
    uuid.UUID(response.request_id)
    dumped = response.model_dump_json()
    assert "Traceback" not in dumped
    assert _API_KEY not in dumped
    assert "File " not in dumped


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "   "},
        {"question": ""},
        {"question": "x" * 2001},
        {"question": "合法问题", "top_k": 0},
        {"question": "合法问题", "top_k": 21},
        {"question": "   ", "session_id": ""},
    ],
)
def test_invalid_payload_returns_invalid_request_without_calling_model(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    payload: dict[str, object],
) -> None:
    caplog.set_level(logging.INFO, logger="minirag")
    settings = _settings(monkeypatch)
    model = _fake_model("不应被调用")

    response = ask(payload, _context(settings, model))

    _assert_error_shape(response, "invalid_request", _INVALID_REQUEST_MESSAGE)
    assert model.i == 0
    if "session_id" in payload:
        assert response.session_id == payload["session_id"]
    else:
        uuid.UUID(response.session_id)
        assert response.session_id != response.request_id
    question = payload["question"]
    assert isinstance(question, str)
    # 空字符串是任何文本的子串，不能用来检查“没有回显”。
    if question.strip():
        assert question not in response.model_dump_json()
        assert question not in caplog.text
    assert _API_KEY not in caplog.text
    assert request_id_var.get() is None
    records = _service_records(caplog)
    assert records
    assert {record.request_id for record in records} == {response.request_id}


def test_model_construct_is_validated_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    model = _fake_model("不应被调用")
    request = AskRequest.model_construct(
        question="   ",
        session_id="sess-keep",
        user_id=None,
        top_k=0,
    )

    response = ask(request, _context(settings, model))

    _assert_error_shape(response, "invalid_request", _INVALID_REQUEST_MESSAGE)
    assert response.session_id == "sess-keep"
    assert model.i == 0


async def test_aask_invalid_question_matches_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    model = _fake_model("不应被调用")
    context = _context(settings, model)

    response = await aask({"question": "  ", "session_id": "sess-a"}, context)

    _assert_error_shape(response, "invalid_request", _INVALID_REQUEST_MESSAGE)
    assert response.session_id == "sess-a"
    assert model.i == 0


def test_valid_dict_still_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    model = _fake_model("  回复  ")

    response = ask(
        {"question": "  你好  ", "top_k": 1, "session_id": "sess-1"},
        _context(settings, model),
    )

    assert response.status == "answered"
    assert response.intent == "chat"
    assert response.answer == "  回复  "
    assert response.session_id == "sess-1"
    assert response.error is None
    assert model.i == 1


@pytest.mark.parametrize(
    "boom",
    [
        openai.APITimeoutError(_request()),
        openai.APIConnectionError(message=f"connect {_API_KEY}", request=_request()),
        _status_error(429, openai.RateLimitError),
        _status_error(500, openai.InternalServerError),
    ],
)
def test_provider_failure_returns_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    boom: Exception,
) -> None:
    caplog.set_level(logging.WARNING, logger="minirag")
    settings = _settings(monkeypatch)
    model = ExplodingChatModel(boom=boom)

    response = ask(
        AskRequest(question="你好", session_id="sess-1"), _context(settings, model)
    )

    _assert_error_shape(response, "llm_unavailable", _LLM_UNAVAILABLE_MESSAGE)
    assert response.session_id == "sess-1"
    assert model.calls == 1
    assert str(boom) not in response.model_dump_json()
    assert _API_KEY not in caplog.text
    assert "Traceback" not in caplog.text
    assert request_id_var.get() is None
    records = _service_records(caplog)
    assert records
    assert {record.request_id for record in records} == {response.request_id}


async def test_aask_timeout_returns_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    model = ExplodingChatModel(boom=openai.APITimeoutError(_request()))

    response = await aask(AskRequest(question="你好"), _context(settings, model))

    _assert_error_shape(response, "llm_unavailable", _LLM_UNAVAILABLE_MESSAGE)
    assert model.calls == 1
    uuid.UUID(response.session_id)


def test_unknown_exception_returns_internal_error_and_logs_stack(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="minirag")
    settings = _settings(monkeypatch)
    model = ExplodingChatModel(boom=RuntimeError(f"boom {_API_KEY}"))

    response = ask(AskRequest(question="你好"), _context(settings, model))

    _assert_error_shape(response, "internal_error", _INTERNAL_ERROR_MESSAGE)
    assert model.calls == 1
    assert f"boom {_API_KEY}" not in response.model_dump_json()
    assert "RuntimeError" not in response.model_dump_json()
    assert "Traceback (most recent call last):" in caplog.text
    assert _API_KEY not in caplog.text
    assert request_id_var.get() is None
    records = _service_records(caplog)
    assert records
    assert {record.request_id for record in records} == {response.request_id}


def test_builtin_timeout_is_internal_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="minirag")
    settings = _settings(monkeypatch)
    model = ExplodingChatModel(boom=TimeoutError("timeout"))

    response = ask(AskRequest(question="你好"), _context(settings, model))

    _assert_error_shape(response, "internal_error", _INTERNAL_ERROR_MESSAGE)
    assert "timeout" not in response.model_dump_json()
    assert "Traceback (most recent call last):" in caplog.text
    assert _API_KEY not in caplog.text


def test_authentication_error_is_internal_and_hides_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="minirag")
    settings = _settings(monkeypatch)
    model = ExplodingChatModel(boom=_status_error(401, openai.AuthenticationError))

    response = ask(AskRequest(question="你好"), _context(settings, model))

    _assert_error_shape(response, "internal_error", _INTERNAL_ERROR_MESSAGE)
    assert response.error is not None
    assert response.error.code != "llm_unavailable"
    assert _API_KEY not in caplog.text
    assert "Traceback (most recent call last):" in caplog.text


def test_negative_usage_inside_graph_is_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    message = AIMessage(
        content="回答",
        usage_metadata={"input_tokens": -1, "output_tokens": 2, "total_tokens": 1},
    )
    model = FakeMessagesListChatModel(
        responses=[message, AIMessage(content="第二条不会被本次调用使用")]
    )

    response = ask(AskRequest(question="你好"), _context(settings, model))

    _assert_error_shape(response, "internal_error", _INTERNAL_ERROR_MESSAGE)
    assert model.i == 1
