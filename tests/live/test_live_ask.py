"""A-S0-7：真实配置下运行 ``python -m minirag ask``。

没有必填配置时跳过。跳过表示这条真实服务场景尚未验证，不是测试通过。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from minirag.config import Settings

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"


def _settings_or_skip() -> Settings:
    try:
        return Settings(_env_file=_ROOT / ".env")
    except ValidationError:
        pytest.skip(
            "未配置 MINIRAG_CHAT_MODEL、MINIRAG_BASE_URL、MINIRAG_API_KEY，A-S0-7 未验证"
        )


@pytest.mark.live
def test_live_ask_returns_answer_without_api_key_in_output() -> None:
    """子进程执行命令。标准输出是回答，标准错误里的项目日志不含密钥。"""
    settings = _settings_or_skip()
    secret = settings.api_key.get_secret_value()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-m", "minirag", "ask", "你好"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    if secret and secret in combined:
        raise AssertionError("命令输出中出现了 API Key")
    redacted_out = (
        completed.stdout.replace(secret, "[REDACTED]") if secret else completed.stdout
    )
    redacted_err = (
        completed.stderr.replace(secret, "[REDACTED]") if secret else completed.stderr
    )
    assert completed.returncode == 0, redacted_err
    assert redacted_out.strip()
    assert "Traceback" not in redacted_err
    assert "开始问答" in redacted_err
    assert "问答完成" in redacted_err
