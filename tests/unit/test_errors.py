"""错误码映射与供应商异常分类。

这些测试不调用图，也不访问网络。服务入口如何把分类结果放进响应，
见 ``tests/graph/test_service_errors.py``。
"""

import httpx
import openai
import pytest
from langchain_openai.chat_models.base import (
    OpenAIAPIError,
    OpenAIConnectionError,
    OpenAIRateLimitError,
    OpenAITimeoutError,
)
from pydantic import ValidationError

from minirag.contracts import AskRequest
from minirag.errors import (
    LLMUnavailableError,
    error_info_for_exception,
    invalid_request_info,
)
from minirag.llm.chat_model import raise_provider_failure

_API_KEY = "sk-test-secret-value"
_INVALID_REQUEST_MESSAGE = "请求参数不合法。"
_LLM_UNAVAILABLE_MESSAGE = "模型暂时不可用，请稍后重试。"
_INTERNAL_ERROR_MESSAGE = "服务内部出错，请稍后重试。"


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.com/v1/chat/completions")


def _status_error(
    status_code: int,
    exc_type: type[openai.APIStatusError],
) -> openai.APIStatusError:
    response = httpx.Response(status_code, request=_request())
    return exc_type(f"status {status_code} {_API_KEY}", response=response, body=None)


def test_invalid_request_info_is_stable_and_hides_input() -> None:
    with pytest.raises(ValidationError):
        AskRequest(question="   ", top_k=0)

    info = invalid_request_info()

    assert info.code == "invalid_request"
    assert info.message == _INVALID_REQUEST_MESSAGE
    assert "top_k" not in info.message
    assert _API_KEY not in info.message


def test_llm_unavailable_exception_uses_stable_message() -> None:
    error = LLMUnavailableError()
    leaked = LLMUnavailableError(f"provider said {_API_KEY}")

    info = error_info_for_exception(error)
    leaked_info = error_info_for_exception(leaked)

    assert info.code == "llm_unavailable"
    assert info.message == _LLM_UNAVAILABLE_MESSAGE
    assert str(error) == _LLM_UNAVAILABLE_MESSAGE
    assert leaked_info.message == _LLM_UNAVAILABLE_MESSAGE
    assert _API_KEY not in leaked_info.message


def test_unknown_exception_becomes_internal_error_without_its_text() -> None:
    info = error_info_for_exception(RuntimeError(f"boom {_API_KEY}"))

    assert info.code == "internal_error"
    assert info.message == _INTERNAL_ERROR_MESSAGE
    assert _API_KEY not in info.message
    assert "Traceback" not in info.message
    assert "RuntimeError" not in info.message


def test_validation_error_is_not_treated_as_invalid_request() -> None:
    """图内部的校验失败不是客户端的非法请求。"""
    with pytest.raises(ValidationError) as caught:
        AskRequest(question="")

    info = error_info_for_exception(caught.value)

    assert info.code == "internal_error"
    assert info.message == _INTERNAL_ERROR_MESSAGE
    assert "question" not in info.message


def test_api_timeout_is_reraised_from_the_sdk_error() -> None:
    original = openai.APITimeoutError(_request())

    with pytest.raises(
        LLMUnavailableError, match=f"^{_LLM_UNAVAILABLE_MESSAGE}$"
    ) as caught:
        raise_provider_failure(original)

    assert caught.value.__cause__ is original
    assert caught.value.__suppress_context__ is True
    assert "Request timed out" not in str(caught.value)


def test_langchain_timeout_wrapper_is_provider_unavailable() -> None:
    original = OpenAITimeoutError(_request())

    with pytest.raises(LLMUnavailableError) as caught:
        raise_provider_failure(original)

    assert caught.value.__cause__ is original


@pytest.mark.parametrize(
    "original",
    [
        openai.APIConnectionError(message=f"connect {_API_KEY}", request=_request()),
        OpenAIConnectionError(message=f"connect {_API_KEY}", request=_request()),
        _status_error(429, openai.RateLimitError),
        _status_error(429, OpenAIRateLimitError),
        _status_error(500, openai.InternalServerError),
        _status_error(503, OpenAIAPIError),
    ],
)
def test_connection_rate_limit_and_server_errors_are_provider_failures(
    original: Exception,
) -> None:
    with pytest.raises(
        LLMUnavailableError, match=f"^{_LLM_UNAVAILABLE_MESSAGE}$"
    ) as caught:
        raise_provider_failure(original)

    assert caught.value.__cause__ is original
    assert _API_KEY not in str(caught.value)


def test_existing_domain_error_is_not_wrapped_again() -> None:
    original = LLMUnavailableError()

    with pytest.raises(LLMUnavailableError) as caught:
        raise_provider_failure(original)

    assert caught.value is original


@pytest.mark.parametrize(
    "original",
    [
        TimeoutError("timeout"),
        _status_error(400, openai.BadRequestError),
        _status_error(401, openai.AuthenticationError),
        _status_error(403, openai.PermissionDeniedError),
        _status_error(404, openai.NotFoundError),
        _status_error(408, openai.APIStatusError),
        _status_error(409, openai.ConflictError),
        _status_error(422, openai.UnprocessableEntityError),
    ],
)
def test_non_availability_errors_are_left_unchanged(original: Exception) -> None:
    raise_provider_failure(original)
