from pathlib import Path

import pytest
from pydantic import ValidationError

from minirag.config import Settings

_ENV_NAMES = (
    "MINIRAG_CHAT_MODEL",
    "MINIRAG_BASE_URL",
    "MINIRAG_API_KEY",
    "MINIRAG_TIMEOUT",
    "MINIRAG_MAX_RETRIES",
)
_API_KEY = "sk-test-secret-value"
_ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _set_required(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    _clear_env(monkeypatch)
    values = {
        "MINIRAG_CHAT_MODEL": "demo-chat",
        "MINIRAG_BASE_URL": "https://example.com/v1",
        "MINIRAG_API_KEY": _API_KEY,
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(
        monkeypatch,
        MINIRAG_TIMEOUT="30.5",
        MINIRAG_MAX_RETRIES="1",
    )

    settings = Settings(_env_file=None)

    assert settings.chat_model == "demo-chat"
    assert settings.base_url == "https://example.com/v1"
    assert settings.api_key.get_secret_value() == _API_KEY
    assert settings.timeout == 30.5
    assert settings.max_retries == 1


def test_timeout_and_retries_default_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SPEC 4.7 与决策 11：重试默认且最多 2 次。
    # SPEC 没有给出超时秒数；600 是当前环境 openai SDK 的总超时。
    _set_required(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.timeout == 600.0
    assert settings.max_retries == 2


def test_missing_api_key_error_includes_variable_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("MINIRAG_CHAT_MODEL", "demo-chat")
    monkeypatch.setenv("MINIRAG_BASE_URL", "https://example.com/v1")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    message = str(exc_info.value)
    assert "MINIRAG_API_KEY" in message
    assert _API_KEY not in message


@pytest.mark.parametrize("api_key", ["", "   "])
def test_blank_api_key_is_reported_as_missing(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str,
) -> None:
    _set_required(monkeypatch, MINIRAG_API_KEY=api_key)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "MINIRAG_API_KEY" in str(exc_info.value)


@pytest.mark.parametrize("api_key", ["", "   "])
def test_blank_constructor_api_key_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str,
) -> None:
    _clear_env(monkeypatch)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            chat_model="demo-chat",
            base_url="https://example.com/v1",
            api_key=api_key,
        )

    assert "MINIRAG_API_KEY" in str(exc_info.value)


def test_blank_model_and_base_url_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(
        monkeypatch,
        MINIRAG_CHAT_MODEL="   ",
        MINIRAG_BASE_URL="",
    )

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    message = str(exc_info.value)
    assert "MINIRAG_CHAT_MODEL" in message
    assert "MINIRAG_BASE_URL" in message


def test_missing_model_and_base_url_name_their_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("MINIRAG_API_KEY", _API_KEY)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    message = str(exc_info.value)
    assert "MINIRAG_CHAT_MODEL" in message
    assert "MINIRAG_BASE_URL" in message
    assert _API_KEY not in message


def test_repr_and_str_do_not_reveal_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)

    settings = Settings(_env_file=None)
    rendered = (
        str(settings),
        repr(settings),
        str(settings.api_key),
        repr(settings.api_key),
        settings.model_dump_json(),
    )

    assert all(_API_KEY not in text for text in rendered)
    assert settings.api_key.get_secret_value() == _API_KEY


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("MINIRAG_TIMEOUT", "0"),
        ("MINIRAG_TIMEOUT", "-1"),
        ("MINIRAG_TIMEOUT", "not-a-number"),
        ("MINIRAG_MAX_RETRIES", "-1"),
        ("MINIRAG_MAX_RETRIES", "3"),
    ],
)
def test_invalid_timeout_and_retries_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    env_value: str,
) -> None:
    _set_required(monkeypatch, **{env_name: env_value})

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert _API_KEY not in str(exc_info.value)


def test_unknown_setting_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, unknown_setting="x")


def test_constructor_arguments_override_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)

    settings = Settings(
        _env_file=None,
        chat_model="from-init",
        base_url="https://init.example/v1",
        api_key="init-secret",
        timeout=9,
        max_retries=0,
    )

    assert settings.chat_model == "from-init"
    assert settings.base_url == "https://init.example/v1"
    assert settings.api_key.get_secret_value() == "init-secret"
    assert settings.timeout == 9.0
    assert settings.max_retries == 0
    assert "init-secret" not in repr(settings)


def test_disabled_env_file_is_not_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "dotenv-only-secret"
    (tmp_path / ".env").write_text(
        "MINIRAG_CHAT_MODEL=file-model\n"
        "MINIRAG_BASE_URL=https://file.example/v1\n"
        f"MINIRAG_API_KEY={secret}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    message = str(exc_info.value)
    assert "MINIRAG_API_KEY" in message
    assert secret not in message
    assert "file-model" not in message


def test_dotenv_loads_and_environment_overrides_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "MINIRAG_CHAT_MODEL=file-model\n"
        "MINIRAG_BASE_URL=https://file.example/v1\n"
        "MINIRAG_API_KEY=file-secret\n"
        "MINIRAG_TIMEOUT=11\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)

    from_file = Settings()

    assert from_file.chat_model == "file-model"
    assert from_file.base_url == "https://file.example/v1"
    assert from_file.api_key.get_secret_value() == "file-secret"
    assert from_file.timeout == 11.0
    assert from_file.max_retries == 2
    assert "file-secret" not in str(from_file)

    monkeypatch.setenv("MINIRAG_API_KEY", "env-secret")
    monkeypatch.setenv("MINIRAG_TIMEOUT", "22")
    overridden = Settings()

    assert overridden.chat_model == "file-model"
    assert overridden.base_url == "https://file.example/v1"
    assert overridden.api_key.get_secret_value() == "env-secret"
    assert overridden.timeout == 22.0
    assert "file-secret" not in str(overridden)
    assert "env-secret" not in str(overridden)


def test_env_example_contains_placeholders_only() -> None:
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "MINIRAG_API_KEY=your-api-key" in text
    assert "sk-" not in text
    for name in _ENV_NAMES:
        assert name in text
