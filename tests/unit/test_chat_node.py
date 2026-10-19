import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.runtime import Runtime
from pydantic import Field

from minirag.config import Settings
from minirag.graph.context import AppContext
from minirag.graph.nodes.chat import respond_chat
from minirag.graph.state import AgentState
from minirag.llm.prompts import CHAT_SYSTEM_PROMPT

_API_KEY = "sk-test-secret-value"
_ENV_NAMES = (
    "MINIRAG_CHAT_MODEL",
    "MINIRAG_BASE_URL",
    "MINIRAG_API_KEY",
    "MINIRAG_TIMEOUT",
    "MINIRAG_MAX_RETRIES",
)
_UPDATE_KEYS = {"answer", "usage_records"}
_RECORD_KEYS = {"model", "input_tokens", "output_tokens"}


class RecordingChatModel(FakeMessagesListChatModel):
    """记下每次调用收到的消息，并继续返回预先写好的回复。"""

    seen: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object | None = None,
        **kwargs: object,
    ) -> object:
        self.seen.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


class RaisingChatModel(BaseChatModel):
    """调用时抛出超时，用来确认节点不吞掉模型异常。"""

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


def _runtime(
    settings: Settings,
    model: BaseChatModel,
) -> Runtime[AppContext]:
    return Runtime(context=AppContext(settings=settings, chat_model=model))


def _reply(content: str | list[object], **usage: int) -> AIMessage:
    if usage:
        return AIMessage(
            content=content,
            usage_metadata={
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "total_tokens": usage["input_tokens"] + usage["output_tokens"],
            },
        )
    return AIMessage(content=content)


async def test_respond_chat_returns_answer_and_one_usage_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    model = RecordingChatModel(
        responses=[_reply("  你好  ", input_tokens=3, output_tokens=5)]
    )

    update = await respond_chat(
        {"question": "  天气 {how} 呢  "},
        _runtime(settings, model),
    )

    assert set(update) == _UPDATE_KEYS
    assert update["answer"] == "  你好  "
    records = update["usage_records"]
    assert len(records) == 1
    assert set(records[0]) == _RECORD_KEYS
    assert records[0]["model"] == "demo-chat"
    assert records[0]["input_tokens"] == 3
    assert records[0]["output_tokens"] == 5
    assert "total_tokens" not in records[0]


async def test_respond_chat_keeps_zero_token_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    model = FakeMessagesListChatModel(
        responses=[_reply("ok", input_tokens=0, output_tokens=0)]
    )

    update = await respond_chat({"question": "你好"}, _runtime(settings, model))

    record = update["usage_records"][0]
    assert record["input_tokens"] == 0
    assert record["output_tokens"] == 0


async def test_respond_chat_records_null_usage_when_metadata_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    model = FakeMessagesListChatModel(responses=[_reply("没有用量")])

    update = await respond_chat({"question": "你好"}, _runtime(settings, model))

    assert update["answer"] == "没有用量"
    record = update["usage_records"][0]
    assert record["model"] == "demo-chat"
    assert record["input_tokens"] is None
    assert record["output_tokens"] is None


async def test_respond_chat_sends_rendered_chat_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    question = "天气 {how} 呢"
    model = RecordingChatModel(responses=[_reply("好的")])

    await respond_chat({"question": question}, _runtime(settings, model))

    assert len(model.seen) == 1
    messages = model.seen[0]
    assert len(messages) == 2
    assert all(isinstance(message, BaseMessage) for message in messages)
    assert messages[0].type == "system"
    assert messages[0].content == CHAT_SYSTEM_PROMPT
    assert messages[1].type == "human"
    assert messages[1].content == question


async def test_respond_chat_keeps_empty_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    model = FakeMessagesListChatModel(responses=[_reply("")])

    update = await respond_chat({"question": "你好"}, _runtime(settings, model))

    assert update["answer"] == ""
    assert len(update["usage_records"]) == 1


async def test_respond_chat_rejects_non_string_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    model = FakeMessagesListChatModel(
        responses=[_reply([{"type": "text", "text": "你好"}]), _reply("unused")]
    )

    with pytest.raises(TypeError):
        await respond_chat({"question": "你好"}, _runtime(settings, model))


async def test_respond_chat_requires_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    model = FakeMessagesListChatModel(
        responses=[_reply("不应被调用"), _reply("第二条")]
    )
    state: AgentState = {"request_id": "req-1"}

    with pytest.raises(KeyError):
        await respond_chat(state, _runtime(settings, model))

    assert model.i == 0


async def test_respond_chat_propagates_model_errors_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)

    with pytest.raises(TimeoutError, match="timeout") as exc_info:
        await respond_chat(
            {"question": "你好"},
            _runtime(settings, RaisingChatModel()),
        )

    assert _API_KEY not in str(exc_info.value)


async def test_respond_chat_uses_the_injected_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    selected = FakeMessagesListChatModel(
        responses=[_reply("来自注入模型"), _reply("第二条")]
    )
    other = FakeMessagesListChatModel(responses=[_reply("不应出现"), _reply("第二条")])

    def _reject_settings(self: Settings, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("节点不应构造 Settings")

    monkeypatch.setattr(Settings, "__init__", _reject_settings)
    update = await respond_chat({"question": "你好"}, _runtime(settings, selected))

    assert update["answer"] == "来自注入模型"
    assert selected.i == 1
    assert other.i == 0
