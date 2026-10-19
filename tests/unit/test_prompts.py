from langchain_core.messages import HumanMessage, SystemMessage

from minirag.llm.prompts import build_chat_prompt, render_chat_prompt

_SYSTEM_PROMPT = (
    "你是 MiniRAG 的对话助手。请直接回答用户的问题。"
    "不要声称查阅了知识库，不要编造引用。"
)


def test_render_chat_prompt_is_system_then_human() -> None:
    messages = render_chat_prompt("你好")

    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert messages[0].content == _SYSTEM_PROMPT
    assert messages[1].content == "你好"


def test_render_chat_prompt_keeps_question_verbatim() -> None:
    question = "  问 {name} 和 {question}  "

    messages = render_chat_prompt(question)

    assert messages[1].content == question
    assert question not in str(messages[0].content)


def test_render_chat_prompt_keeps_empty_question() -> None:
    messages = render_chat_prompt("")

    assert messages[1].content == ""
    assert messages[0].content == _SYSTEM_PROMPT


def test_system_message_does_not_change_with_question() -> None:
    first = render_chat_prompt("甲")
    second = render_chat_prompt("乙")

    assert first[0].content == second[0].content == _SYSTEM_PROMPT
    assert first[1].content == "甲"
    assert second[1].content == "乙"


def test_chat_prompt_invoke_matches_render() -> None:
    rendered = build_chat_prompt().invoke({"question": "原文"}).to_messages()
    direct = render_chat_prompt("原文")

    assert [type(message) for message in rendered] == [SystemMessage, HumanMessage]
    assert rendered[0].content == direct[0].content == _SYSTEM_PROMPT
    assert rendered[1].content == direct[1].content == "原文"
