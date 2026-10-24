"""组装入口只根据配置创建聊天模型，构造过程不访问网络。"""

import socket
from pathlib import Path

import pytest
from langchain_openai import ChatOpenAI

from minirag.bootstrap import build_app_context, load_app_context
from minirag.config import Settings
from minirag.graph.context import AppContext

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
    """构造依赖期间若发生 DNS 或 TCP 连接，则本测试失败。"""

    def _reject(operation: str):
        def _fail(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(f"构造依赖时不应访问网络，但调用了 {operation}")

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


def test_build_app_context_binds_settings_and_chat_model_without_network(
    monkeypatch: pytest.MonkeyPatch,
    block_network: None,
) -> None:
    settings = _settings(monkeypatch, timeout=12.5, max_retries=0)

    context = build_app_context(settings)

    assert isinstance(context, AppContext)
    assert context.settings is settings
    assert isinstance(context.chat_model, ChatOpenAI)
    assert context.chat_model.model_name == "demo-chat"
    assert context.chat_model.openai_api_base == "https://example.com/v1"
    assert context.chat_model.request_timeout == 12.5
    assert context.chat_model.max_retries == 0
    visible = "\n".join([str(context), repr(context)])
    assert _API_KEY not in visible


def test_load_app_context_reads_environment_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    block_network: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MINIRAG_CHAT_MODEL", "env-chat")
    monkeypatch.setenv("MINIRAG_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("MINIRAG_API_KEY", _API_KEY)
    monkeypatch.setenv("MINIRAG_TIMEOUT", "9")
    monkeypatch.setenv("MINIRAG_MAX_RETRIES", "1")

    context = load_app_context()

    assert isinstance(context, AppContext)
    assert context.settings.chat_model == "env-chat"
    assert context.settings.base_url == "https://example.com/v1"
    assert context.settings.timeout == 9
    assert context.settings.max_retries == 1
    assert context.settings.api_key.get_secret_value() == _API_KEY
    assert isinstance(context.chat_model, ChatOpenAI)
    assert context.chat_model.model_name == "env-chat"
    assert context.chat_model.request_timeout == 9
    assert context.chat_model.max_retries == 1
    assert _API_KEY not in repr(context)
