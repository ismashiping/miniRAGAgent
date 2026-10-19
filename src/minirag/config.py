"""从环境变量和 ``.env`` 加载运行配置。

本模块属于基础层，不导入其他项目模块，也不访问网络。
"""

from pydantic import AliasChoices, Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# SPEC 只要求超时可配置，没有规定秒数。当前环境里 openai SDK 的总超时是
# 600 秒（openai._constants.DEFAULT_TIMEOUT）。这里用同一个数，避免项目默认
# 和即将接入的客户端默认各写一套。
_DEFAULT_TIMEOUT_SECONDS = 600.0
# SPEC 4.7 与决策 11：外部调用最多重试 2 次。0 表示不重试，仍允许。
_DEFAULT_MAX_RETRIES = 2
_REQUIRED_ENV_VARS = {
    "chat_model": "MINIRAG_CHAT_MODEL",
    "base_url": "MINIRAG_BASE_URL",
    "api_key": "MINIRAG_API_KEY",
}


class Settings(BaseSettings):
    """聊天模型的运行配置。

    设计约定：构造参数优先于进程环境变量，环境变量优先于当前工作目录下的
    ``.env``，都没有时才用字段默认值。这是 pydantic-settings 2.15 的来源顺序。
    测试传入 ``_env_file=None`` 可跳过 ``.env``，避免读到开发者本机文件。

    密钥使用 ``SecretStr``。``str``、``repr`` 和 ``model_dump_json`` 只显示掩码。
    明文只能通过 ``get_secret_value()`` 取出，调用方不得把它写进日志。

    缺少必填项时，``ValidationError`` 的位置使用环境变量名，而不是只写字段名。
    因此每个必填字段的 ``validation_alias`` 都把变量名放在第一位。空字符串视为
    未设置；只含空白的值在校验阶段拒绝。``hide_input_in_errors`` 让错误文本不回显
    已传入的值，避免别的字段校验失败时把 API Key 打出来。

    参数:
        chat_model: 聊天模型名。环境变量 ``MINIRAG_CHAT_MODEL``。必填，不能为空白。
        base_url: OpenAI 兼容接口的基地址。环境变量 ``MINIRAG_BASE_URL``。必填，
            不能为空白。本字段不检查 URL 格式。
        api_key: 调用模型的 API Key。环境变量 ``MINIRAG_API_KEY``。必填，类型为
            ``SecretStr``，不能为空白。
        timeout: 传给模型客户端的总超时，单位秒。环境变量 ``MINIRAG_TIMEOUT``。
            省略时为 600，必须大于 0。
        max_retries: 模型客户端的最大重试次数。环境变量 ``MINIRAG_MAX_RETRIES``。
            省略时为 2，允许 0 到 2。

    返回:
        校验通过后的 ``Settings`` 实例。缺少必填项、必填项为空白，或超时与重试
        越界时抛出 ``ValidationError``。
    """

    model_config = SettingsConfigDict(
        env_prefix="MINIRAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="forbid",
        hide_input_in_errors=True,
    )

    chat_model: str = Field(
        validation_alias=AliasChoices("MINIRAG_CHAT_MODEL", "chat_model"),
    )  # AliasChoices通过多个名的接受输入，这里接受MINIRAG_CHAT_MODEL和chat_model
    base_url: str = Field(
        validation_alias=AliasChoices("MINIRAG_BASE_URL", "base_url"),
    )
    api_key: SecretStr = Field(
        validation_alias=AliasChoices("MINIRAG_API_KEY", "api_key"),
    )
    timeout: float = Field(
        default=_DEFAULT_TIMEOUT_SECONDS,
        gt=0,
        validation_alias=AliasChoices("MINIRAG_TIMEOUT", "timeout"),
    )
    max_retries: int = Field(
        default=_DEFAULT_MAX_RETRIES,
        ge=0,
        le=_DEFAULT_MAX_RETRIES,
        validation_alias=AliasChoices("MINIRAG_MAX_RETRIES", "max_retries"),
    )

    @field_validator("chat_model", "base_url", "api_key")
    @classmethod
    def reject_blank_required_value(cls, value: object, info: ValidationInfo) -> object:
        """拒绝已经读到、但去掉空白后为空的必填配置。

        本方法属于 ``Settings``，在字段类型校验之后执行。环境变量中的空字符串
        由 ``env_ignore_empty`` 提前当成缺失，不会进入这里。这里覆盖只含空格的
        环境变量，以及构造参数里的空字符串。错误文本带环境变量名，和缺失字段
        的报错方式一致。

        参数:
            cls: 正在校验的模型类，由 Pydantic 传入。
            value: 已通过类型校验的值。``chat_model`` 与 ``base_url`` 是 ``str``，
                ``api_key`` 是 ``SecretStr``。
            info: 当前字段信息。``field_name`` 用来查找环境变量名。

        返回:
            空白检查通过的原值，不改写内容。值为空白时抛出 ``ValueError``，
            Pydantic 将其包成 ``ValidationError``。
        """
        field_name = info.field_name
        if field_name not in _REQUIRED_ENV_VARS:
            raise ValueError("缺少必填配置")
        text = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"缺少环境变量 {_REQUIRED_ENV_VARS[field_name]}")
        return value
