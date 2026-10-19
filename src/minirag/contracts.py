"""CLI、图和 HTTP 共用的问答契约。

入库报告 ``IngestReport`` 留到 S1-05，不在本模块定义。
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ErrorCode = Literal[
    "invalid_request",
    "retrieval_failed",
    "llm_unavailable",
    "service_unavailable",
    "internal_error",
]
Intent = Literal["chat", "knowledge", "calculate"]
AnswerStatus = Literal["answered", "insufficient_evidence", "error"]

_QUESTION_MIN_LENGTH = 1
_QUESTION_MAX_LENGTH = 2000
_TOP_K_MIN = 1
_TOP_K_MAX = 20
_TOP_K_DEFAULT = 5


class AskRequest(BaseModel):
    """一次问答请求。CLI、LangGraph 入口和 HTTP 共用这一份结构。

    参数:
        question: 用户问题。去掉首尾空白后长度必须在 1 到 2000 之间。
        session_id: 可选会话标识。缺省为 ``None``，由入口生成并在响应中返回。
        user_id: 可选用户标识。调用方提供的不透明字符串，不是安全边界。缺省为 ``None``。
        top_k: 检索返回条数。默认 5，允许范围 1 到 20。

    返回:
        校验通过后的 ``AskRequest`` 实例。任一字段非法时抛出 ``ValidationError``。
    """

    question: str = Field(
        min_length=_QUESTION_MIN_LENGTH,
        max_length=_QUESTION_MAX_LENGTH,
    )
    session_id: str | None = None
    user_id: str | None = None
    top_k: int = Field(default=_TOP_K_DEFAULT, ge=_TOP_K_MIN, le=_TOP_K_MAX)

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value: object) -> object:
        """在长度检查之前去掉 ``question`` 的首尾空白。

        参数:
            cls: 正在校验的模型类，由 Pydantic 传入。
            value: 调用方传入的原始问题。此时尚未做类型转换。

        返回:
            ``value`` 是字符串时，返回去掉首尾空白后的字符串。否则原样返回，
            交给后续类型校验拒绝。
        """
        if isinstance(value, str):
            return value.strip()
        return value


class ErrorInfo(BaseModel):
    """面向调用方的错误。只在 ``AskResponse.status`` 为 ``error`` 时出现。

    设计约定：``code`` 只接受 SPEC 4.10 列出的五个错误码。``message`` 是面向
    用户的说明，不包含堆栈。SPEC 没有规定 ``message`` 的最小长度，因此空字符串
    可以通过本模型。

    参数:
        code: 错误码。允许 ``invalid_request``、``retrieval_failed``、
            ``llm_unavailable``、``service_unavailable``、``internal_error``。
        message: 面向用户的错误说明。

    返回:
        校验通过后的 ``ErrorInfo`` 实例。未知错误码抛出 ``ValidationError``。
    """

    code: ErrorCode
    message: str


class Usage(BaseModel):
    """一次请求的用量汇总。

    参数:
        model: 产生这段用量的模型名称。
        input_tokens: 输入 Token 数，必须大于等于 0。0 是真实计数。
        output_tokens: 输出 Token 数，必须大于等于 0。0 是真实计数。

    返回:
        校验通过后的 ``Usage`` 实例。Token 为负数时抛出 ``ValidationError``。
    """

    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class Citation(BaseModel):
    """知识问答回答中的一条引用。
    参数:
        marker: 回答中的引用编号，原样保存为字符串。
        chunk_id: 被引用切片的标识。
        doc_id: 切片所属文档的标识。
        heading: 切片标题。没有标题时为 ``None``。
        snippet: 展示给调用方的切片摘录。
        vector_score: 向量召回分数。该路未参与时为 ``None``。
        bm25_score: BM25 召回分数。该路未参与时为 ``None``。
        rrf_score: RRF 融合分数。未计算时为 ``None``。
        rerank_score: 重排分数。未重排时为 ``None``。

    返回:
        校验通过后的 ``Citation`` 实例。
    """

    marker: str
    chunk_id: str
    doc_id: str
    heading: str | None = None
    snippet: str
    vector_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None


class AskResponse(BaseModel):
    """一次问答响应。CLI、图和 HTTP 共用这一份结构。

    参数:
        request_id: 本次请求标识。
        session_id: 会话标识。请求未提供时由入口生成。
        status: 回答状态。取值为 ``answered``、``insufficient_evidence`` 或 ``error``。
        intent: 路由意图。取值为 ``chat``、``knowledge`` 或 ``calculate``。
            请求校验失败时为 ``None``，这不是第四种意图。
        answer: 回答文本。``status`` 为 ``error`` 时是面向用户的简短说明。
        citations: 引用列表。非 ``knowledge`` 时必须为空。省略时为新的空列表。
        degraded: 降级组件名。保存时按名称排序。无降级时为空列表。
        error: 错误信息。仅 ``status`` 为 ``error`` 时提供，其他状态必须为 ``None``。
        usage: 本次请求的模型用量汇总。任一调用拿不到用量时为 ``None``。
        latency_ms: 入口测量的端到端耗时，单位毫秒，必须大于等于 0。

    返回:
        校验通过后的 ``AskResponse`` 实例。状态与错误、意图与引用不一致时抛出
        ``ValidationError``。
    """

    request_id: str
    session_id: str
    status: AnswerStatus
    intent: Intent | None = None
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    degraded: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None
    usage: Usage | None = None
    latency_ms: int = Field(ge=0)

    @field_validator("degraded")
    @classmethod
    def sort_degraded(cls, value: list[str]) -> list[str]:
        """把降级组件名按字典序保存，使各入口构造的响应顺序一致。

        参数:
            cls: 正在校验的模型类，由 Pydantic 传入。
            value: 已通过类型校验的降级组件名列表。

        返回:
            按名称排序的新列表。没有降级组件时为空列表。
        """
        return sorted(value)

    @model_validator(mode="after")
    def check_status_consistency(self) -> "AskResponse":
        """检查 ``status``、``error``、``intent`` 与 ``citations`` 是否一致。

        本方法属于 ``AskResponse``。``mode="after"`` 表示各字段已经单独校验通过，
        因此这里能同时看到它们。返回类型写成字符串 ``"AskResponse"``，以兼容
        Python 3.10。

        规则：``status`` 为 ``error`` 时必须有 ``error``，其他状态的 ``error``
        必须为 ``None``。``intent`` 不是 ``knowledge`` 时 ``citations`` 必须为空。
        不要求 ``knowledge`` 必须带引用。

        参数:
            self: 字段校验已通过的响应实例。本方法没有其他参数。

        返回:
            通过检查的当前实例。任一规则失败时抛出 ``ValueError``，Pydantic 将其
            包成 ``ValidationError``。
        """
        if self.status == "error" and self.error is None:
            raise ValueError("status 为 error 时必须提供 error")
        if self.status != "error" and self.error is not None:
            raise ValueError("status 不是 error 时 error 必须为 None")
        if self.intent != "knowledge" and self.citations:
            raise ValueError("非 knowledge 意图时 citations 必须为空")
        return self
