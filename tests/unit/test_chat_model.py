import socket

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, ValidationError

from minirag.config import Settings
from minirag.contracts import Usage
from minirag.llm.chat_model import build_chat_model, usage_from_ai_message

_API_KEY = "sk-test-secret-value"
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


@pytest.fixture
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """构造模型期间若发生 DNS 或 TCP 连接，则本测试失败。"""

    def _reject(operation: str):
        def _fail(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(f"构造模型时不应访问网络，但调用了 {operation}")

        return _fail

    monkeypatch.setattr(
        socket, "create_connection", _reject("socket.create_connection")
    )
    monkeypatch.setattr(socket.socket, "connect", _reject("socket.socket.connect"))
    monkeypatch.setattr(socket, "getaddrinfo", _reject("socket.getaddrinfo"))


def _settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> Settings:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return Settings(
        _env_file=None,
        chat_model="demo-chat",
        base_url="https://example.com/v1",
        api_key=_API_KEY,
        **overrides,
    )


def _visible_text(model: ChatOpenAI) -> str:
    api_key = model.openai_api_key
    assert isinstance(api_key, SecretStr)
    return "\n".join(
        [
            str(model),
            repr(model),
            str(api_key),
            repr(api_key),
            str(model.root_client),
            repr(model.root_client),
            str(model.root_async_client),
            repr(model.root_async_client),
        ]
    )


def test_build_chat_model_applies_settings_without_network(
    monkeypatch: pytest.MonkeyPatch,
    block_network: None,
) -> None:
    settings = _settings(monkeypatch, timeout=30.5, max_retries=2)

    model = build_chat_model(settings)

    assert isinstance(model, BaseChatModel)
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "demo-chat"
    assert model.openai_api_base == "https://example.com/v1"
    assert model.request_timeout == 30.5
    assert model.max_retries == 2
    assert isinstance(model.openai_api_key, SecretStr)
    assert model.openai_api_key.get_secret_value() == _API_KEY
    assert model.root_client.max_retries == 2
    assert model.root_client.timeout == 30.5
    assert str(model.root_client.base_url).rstrip("/") == "https://example.com/v1"
    assert model.root_async_client.max_retries == 2
    assert model.root_async_client.timeout == 30.5
    assert str(model.root_async_client.base_url).rstrip("/") == "https://example.com/v1"
    assert _API_KEY not in _visible_text(model)


def test_build_chat_model_uses_settings_defaults(
    monkeypatch: pytest.MonkeyPatch,
    block_network: None,
) -> None:
    settings = _settings(monkeypatch)

    model = build_chat_model(settings)

    assert isinstance(model, ChatOpenAI)
    assert settings.timeout == 600.0
    assert settings.max_retries == 2
    assert model.request_timeout == 600.0
    assert model.max_retries == 2
    assert model.root_client.max_retries == 2
    assert model.root_async_client.max_retries == 2


def test_build_chat_model_passes_custom_timeout_and_zero_retries(
    monkeypatch: pytest.MonkeyPatch,
    block_network: None,
) -> None:
    settings = _settings(monkeypatch, timeout=12.5, max_retries=0)

    model = build_chat_model(settings)

    assert isinstance(model, ChatOpenAI)
    assert model.request_timeout == 12.5
    assert model.max_retries == 0
    assert model.root_client.timeout == 12.5
    assert model.root_client.max_retries == 0
    assert model.root_async_client.timeout == 12.5
    assert model.root_async_client.max_retries == 0


def test_build_chat_model_prefers_settings_over_openai_environment(
    monkeypatch: pytest.MonkeyPatch,
    block_network: None,
) -> None:
    settings = _settings(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-openai-env")
    monkeypatch.setenv("OPENAI_API_BASE", "https://env.example/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://base-env.example/v1")

    model = build_chat_model(settings)

    assert isinstance(model, ChatOpenAI)
    assert isinstance(model.openai_api_key, SecretStr)
    assert model.openai_api_key.get_secret_value() == _API_KEY
    assert model.openai_api_base == "https://example.com/v1"
    visible = _visible_text(model)
    assert _API_KEY not in visible
    assert "sk-from-openai-env" not in visible


def test_usage_from_ai_message_copies_token_counts() -> None:
    message = AIMessage(
        content="回答",
        usage_metadata={
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "input_token_details": {"cache_read": 3},
        },
        response_metadata={"model_name": "other-model"},
    )

    usage = usage_from_ai_message(message, model="demo-chat")

    assert usage == Usage(model="demo-chat", input_tokens=11, output_tokens=7)


def test_usage_from_ai_message_without_metadata_is_none() -> None:
    message = AIMessage(content="回答")

    assert usage_from_ai_message(message, model="demo-chat") is None


def test_usage_from_ai_message_explicit_none_is_none() -> None:
    message = AIMessage(content="回答", usage_metadata=None)

    assert usage_from_ai_message(message, model="demo-chat") is None


def test_zero_token_counts_stay_zero() -> None:
    message = AIMessage(
        content="",
        usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    )

    usage = usage_from_ai_message(message, model="demo-chat")

    assert usage == Usage(model="demo-chat", input_tokens=0, output_tokens=0)


def test_negative_token_count_is_rejected() -> None:
    message = AIMessage(
        content="回答",
        usage_metadata={"input_tokens": -1, "output_tokens": 2, "total_tokens": 1},
    )

    with pytest.raises(ValidationError):
        usage_from_ai_message(message, model="demo-chat")
