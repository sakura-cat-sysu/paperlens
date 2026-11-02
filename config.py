"""模型配置仅在 API 和 Worker 服务端读取；文件存储由 backend.storage 管理。"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PAGES = 50
MAX_TEXT_CHARS = 100_000
MIN_FILES = 2
MAX_FILES = 3
MAX_QUESTION_CHARS = 2_000


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    model: str = ""
    timeout_seconds: float = 60.0

    @property
    def is_deepseek(self) -> bool:
        # 只为官方域名发送专用参数，不影响其他兼容 OpenAI 的服务。
        try:
            return urlparse(self.base_url).hostname == "api.deepseek.com"
        except ValueError:
            return False

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(
            name for name, value in (
                ("OPENAI_API_KEY", self.api_key), ("OPENAI_MODEL", self.model)
            ) if not value.strip()
        )


def load_settings() -> Settings:
    # 不向进程环境写值，重读时可得到更新后的 .env。系统环境变量优先。
    values = dotenv_values(PROJECT_ROOT / ".env")

    def read(name):
        return (os.environ.get(name, values.get(name)) or "").strip()

    return Settings(
        api_key=read("OPENAI_API_KEY"),
        base_url=read("OPENAI_BASE_URL"),
        model=read("OPENAI_MODEL"),
    )
