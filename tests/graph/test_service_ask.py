import asyncio
import logging
import uuid

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage

from minirag.config import Settings
from minirag.contracts import AskRequest, Usage
from minirag.graph.context import AppContext
from minirag.graph.state import UsageRecord
from minirag.logging_setup import (
    REQUEST_ID_LOG_FORMAT,
    RequestIdFilter,
    RequestIdFormatter,
    configure_logging,
    request_id_context,
    request_id_var,
)
from minirag.service import aask, ask, summarize_usage

_API_KEY = "sk-test-secret-value"
_ENV_NAMES = (
    "MINIRAG_CHAT_MODEL",
    "MINIRAG_BASE_URL",
    "MINIRAG_API_KEY",
    "MINIRAG_TIMEOUT",
    "MINIRAG_MAX_RETRIES",
)


class RaisingChatModel(BaseChatModel):
    """调用时抛出超时，用来确认入口不把模型异常收成响应。"""

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object | None = None,
        **kwargs: object,
    ) -> object:
        raise TimeoutError("timeout")

    @property
    def _llm_type(self) -> str:
        return "raising-chat-model"


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return Settings(
        _env_file=None,
        chat_model="demo-chat",
        base_url="https://example.com/v1",
        api_key=_API_KEY,
    )


def _model(
    text: str,
    *,
    input_tokens: int | None = 4,
    output_tokens: int | None = 6,
) -> FakeMessagesListChatModel:
    if input_tokens is None or output_tokens is None:
        message = AIMessage(content=text)
    else:
        message = AIMessage(
            content=text,
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )
    return FakeMessagesListChatModel(
        responses=[
            message,
            AIMessage(content="第二条不会被本次调用使用"),
        ]
    )


def _context(settings: Settings, model: BaseChatModel) -> AppContext:
    return AppContext(settings=settings, chat_model=model)


def _service_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name.startswith("minirag.")]


def test_ask_returns_answered_chat_and_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    response = ask(
        AskRequest(
            question="  今天{天气}  ",
            session_id="sess-1",
            user_id="user-1",
            top_k=3,
        ),
        _context(settings, _model("  保持空白  ")),
    )

    assert response.status == "answered"
    assert response.intent == "chat"
    assert response.answer == "  保持空白  "
    assert response.session_id == "sess-1"
    assert response.citations == []
    assert response.degraded == []
    assert response.error is None
    assert response.usage == Usage(model="demo-chat", input_tokens=4, output_tokens=6)
    uuid.UUID(response.request_id)
    assert type(response.latency_ms) is int
    assert response.latency_ms >= 0
    assert _API_KEY not in response.model_dump_json()


def test_ask_keeps_given_session_id_including_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    kept = ask(
        AskRequest(question="你好", session_id="sess-1"),
        _context(settings, _model("回答")),
    )
    empty = ask(
        AskRequest(question="你好", session_id=""),
        _context(settings, _model("回答")),
    )
    spaces = ask(
        AskRequest(question="你好", session_id="  "),
        _context(settings, _model("回答")),
    )

    assert kept.session_id == "sess-1"
    assert empty.session_id == ""
    assert spaces.session_id == "  "


def test_ask_generates_session_id_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    first = ask(
        AskRequest(question="你好"),
        _context(settings, _model("回答")),
    )
    second = ask(
        AskRequest(question="你好"),
        _context(settings, _model("回答")),
    )

    uuid.UUID(first.session_id)
    uuid.UUID(first.request_id)
    uuid.UUID(second.session_id)
    uuid.UUID(second.request_id)
    assert first.session_id != first.request_id
    assert first.session_id != second.session_id
    assert first.request_id != second.request_id


async def test_aask_usage_follows_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    present = await aask(
        AskRequest(question="你好"),
        _context(settings, _model("有用量", input_tokens=4, output_tokens=6)),
    )
    zeros = await aask(
        AskRequest(question="你好"),
        _context(settings, _model("零用量", input_tokens=0, output_tokens=0)),
    )
    missing = await aask(
        AskRequest(question="你好"),
        _context(settings, _model("无用量", input_tokens=None, output_tokens=None)),
    )
    blank = await aask(
        AskRequest(question="你好"),
        _context(settings, _model("", input_tokens=1, output_tokens=1)),
    )

    assert present.usage == Usage(model="demo-chat", input_tokens=4, output_tokens=6)
    assert present.status == "answered"
    assert zeros.usage == Usage(model="demo-chat", input_tokens=0, output_tokens=0)
    assert missing.usage is None
    assert missing.answer == "无用量"
    assert missing.status == "answered"
    assert missing.intent == "chat"
    assert blank.answer == ""
    assert blank.usage == Usage(model="demo-chat", input_tokens=1, output_tokens=1)


def test_summarize_usage_sums_only_complete_records_of_one_model() -> None:
    complete: list[UsageRecord] = [
        {"model": "demo-chat", "input_tokens": 1, "output_tokens": 2},
        {"model": "demo-chat", "input_tokens": 4, "output_tokens": 6},
    ]
    zeros: list[UsageRecord] = [
        {"model": "demo-chat", "input_tokens": 0, "output_tokens": 0},
    ]
    missing: list[UsageRecord] = [
        {"model": "demo-chat", "input_tokens": None, "output_tokens": None},
    ]
    partial: list[UsageRecord] = [
        {"model": "demo-chat", "input_tokens": 3, "output_tokens": None},
    ]
    mixed_models: list[UsageRecord] = [
        {"model": "demo-chat", "input_tokens": 1, "output_tokens": 2},
        {"model": "other-model", "input_tokens": 4, "output_tokens": 6},
    ]
    one_missing: list[UsageRecord] = [
        {"model": "demo-chat", "input_tokens": 1, "output_tokens": 2},
        {"model": "demo-chat", "input_tokens": None, "output_tokens": None},
    ]

    assert summarize_usage([]) is None
    assert summarize_usage(missing) is None
    assert summarize_usage(partial) is None
    assert summarize_usage(mixed_models) is None
    assert summarize_usage(one_missing) is None
    assert summarize_usage(zeros) == Usage(
        model="demo-chat",
        input_tokens=0,
        output_tokens=0,
    )
    assert summarize_usage(complete) == Usage(
        model="demo-chat",
        input_tokens=5,
        output_tokens=8,
    )


def test_ask_fields_match_aask(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    request = AskRequest(question="今天天气如何", session_id="sess-1")
    via_ask = ask(
        request,
        _context(settings, _model("同一个回答", input_tokens=4, output_tokens=6)),
    )
    via_aask = asyncio.run(
        aask(
            request,
            _context(settings, _model("同一个回答", input_tokens=4, output_tokens=6)),
        )
    )
    ask_data = via_ask.model_dump()
    aask_data = via_aask.model_dump()

    uuid.UUID(ask_data.pop("request_id"))
    uuid.UUID(aask_data.pop("request_id"))
    assert type(ask_data.pop("latency_ms")) is int
    assert type(aask_data.pop("latency_ms")) is int
    assert via_ask.latency_ms >= 0
    assert via_aask.latency_ms >= 0
    assert ask_data == aask_data
    assert via_ask.request_id != via_aask.request_id


def test_request_logs_share_one_request_id(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="minirag")
    settings = _settings(monkeypatch)
    first = ask(
        AskRequest(question="第一题", session_id="s1"),
        _context(settings, _model("回答一")),
    )
    second = ask(
        AskRequest(question="第二题", session_id="s2"),
        _context(settings, _model("回答二")),
    )
    records = _service_records(caplog)

    assert records
    assert {record.request_id for record in records} == {
        first.request_id,
        second.request_id,
    }
    assert _API_KEY not in caplog.text
    assert request_id_var.get() is None


async def test_concurrent_aask_keeps_separate_request_ids(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="minirag")
    settings = _settings(monkeypatch)
    left, right = await asyncio.gather(
        aask(
            AskRequest(question="第一题", session_id="s1"),
            _context(settings, _model("回答一")),
        ),
        aask(
            AskRequest(question="第二题", session_id="s2"),
            _context(settings, _model("回答二")),
        ),
    )
    records = _service_records(caplog)

    assert left.answer == "回答一"
    assert right.answer == "回答二"
    assert left.request_id != right.request_id
    assert {record.request_id for record in records} == {
        left.request_id,
        right.request_id,
    }
    assert request_id_var.get() is None


async def test_ask_cannot_run_inside_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    model = _model("不会被调用")

    with pytest.raises(RuntimeError, match="running event loop"):
        ask(AskRequest(question="你好"), _context(settings, model))

    assert model.i == 0


def test_model_timeout_propagates_and_clears_request_id(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="minirag")
    settings = _settings(monkeypatch)

    with pytest.raises(TimeoutError, match="^timeout$"):
        ask(
            AskRequest(question="你好"),
            _context(settings, RaisingChatModel()),
        )

    records = _service_records(caplog)
    assert records
    assert len({record.request_id for record in records}) == 1
    assert records[0].request_id != "-"
    assert request_id_var.get() is None
    assert _API_KEY not in caplog.text


def test_filter_stamps_child_logger_and_formatter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="minirag")
    configure_logging()
    child = logging.getLogger("minirag.graph.nodes.chat")
    with request_id_context("req-child"):
        assert request_id_var.get() == "req-child"
        child.info("节点日志")
    child.info("请求之外")
    assert request_id_var.get() is None

    stamped = [record for record in caplog.records if record.getMessage() == "节点日志"]
    outside = [record for record in caplog.records if record.getMessage() == "请求之外"]
    assert len(stamped) == 1
    assert stamped[0].request_id == "req-child"
    assert len(outside) == 1
    assert outside[0].request_id == "-"

    bare = logging.LogRecord(
        name="minirag.service",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    assert RequestIdFilter().filter(bare) is True
    assert bare.request_id == "-"
    rendered = RequestIdFormatter(REQUEST_ID_LOG_FORMAT).format(stamped[0])
    assert "[req-child]" in rendered
    assert "minirag.graph.nodes.chat" in rendered
    assert "节点日志" in rendered
    unstamped = logging.LogRecord(
        name="minirag.service",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="plain",
        args=(),
        exc_info=None,
    )
    assert "[-]" in RequestIdFormatter(REQUEST_ID_LOG_FORMAT).format(unstamped)


def test_request_id_context_restores_outer_value() -> None:
    assert request_id_var.get() is None
    with request_id_context("outer"):
        assert request_id_var.get() == "outer"
        with request_id_context("inner"):
            assert request_id_var.get() == "inner"
        assert request_id_var.get() == "outer"
    assert request_id_var.get() is None
