import operator
from typing import get_args, get_type_hints

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.channels.binop import BinaryOperatorAggregate

from minirag.config import Settings
from minirag.graph.builder import build_graph
from minirag.graph.context import AppContext
from minirag.graph.state import AgentState

_API_KEY = "sk-test-secret-value"
_ENV_NAMES = (
    "MINIRAG_CHAT_MODEL",
    "MINIRAG_BASE_URL",
    "MINIRAG_API_KEY",
    "MINIRAG_TIMEOUT",
    "MINIRAG_MAX_RETRIES",
)


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
    return FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content=text,
                usage_metadata={
                    "input_tokens": 4,
                    "output_tokens": 6,
                    "total_tokens": 10,
                },
            ),
            AIMessage(content="第二条不会被本次调用使用"),
        ]
    )


def test_build_graph_connects_start_to_respond_chat() -> None:
    graph = build_graph()

    assert set(graph.builder.nodes) == {"respond_chat"}
    assert graph.builder.edges == {
        ("__start__", "respond_chat"),
        ("respond_chat", "__end__"),
    }
    assert graph.checkpointer is None


def test_usage_records_uses_append_reducer() -> None:
    hints = get_type_hints(AgentState, include_extras=True)
    annotated = hints["usage_records"]
    graph = build_graph()
    channel = graph.channels["usage_records"]
    left = [{"model": "demo-chat", "input_tokens": 1, "output_tokens": 2}]
    right = [{"model": "demo-chat", "input_tokens": None, "output_tokens": None}]

    assert get_args(annotated)[1] is operator.add
    assert isinstance(channel, BinaryOperatorAggregate)
    assert channel.operator is operator.add
    assert channel.operator(left, right) == left + right


async def test_chat_graph_writes_fake_answer_and_one_usage_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    selected = _model("图里的回答")
    other = _model("另一个模型")
    graph = build_graph()
    state: AgentState = {"request_id": "req-1", "question": "今天天气如何"}

    result = await graph.ainvoke(
        state,
        context=AppContext(settings=settings, chat_model=selected),
    )

    assert result["answer"] == "图里的回答"
    assert result["question"] == "今天天气如何"
    assert result["request_id"] == "req-1"
    assert "status" not in result
    assert "error" not in result
    assert len(result["usage_records"]) == 1
    record = result["usage_records"][0]
    assert record["model"] == "demo-chat"
    assert record["input_tokens"] == 4
    assert record["output_tokens"] == 6
    assert selected.i == 1
    assert other.i == 0
    assert _API_KEY not in str(result)
