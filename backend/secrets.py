"""模型密钥的本地加密存储。

密钥只在写库前加密、调用模型前解密；接口和日志里只出现掩码。
主密钥优先取 PAPERLENS_SECRET_KEY，否则使用 .data/secret.key 中自动生成的随机值。
该文件已在 .gitignore 中，不会被提交。
"""

import os
import stat
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = PROJECT_ROOT / ".data" / "secret.key"


class SecretError(RuntimeError):
    """密文无法解出明文，需要用户重新填写密钥。"""


def _master_key() -> bytes:
    configured = (os.getenv("PAPERLENS_SECRET_KEY") or "").strip()
    if configured:
        return configured.encode()
    if KEY_FILE.exists():
        value = KEY_FILE.read_bytes().strip()
        if value:
            return value
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    value = Fernet.generate_key()
    KEY_FILE.write_bytes(value)
    try:
        # 只保留属主读写；Windows 上 chmod 只影响只读位，失败也不影响使用。
        KEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return value


@lru_cache
def _fernet() -> Fernet:
    return Fernet(_master_key())


def reset_cache():
    """测试或更换主密钥后重新读取。"""
    _fernet.cache_clear()


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        raise SecretError("已保存的模型密钥无法解密，请重新填写。") from None


def hint(value: str) -> str:
    """展示用掩码，例如 sk-…c3f9。不含完整密钥。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "…" + value[-2:]
    prefix = "sk-" if value.startswith("sk-") else value[:2]
    return f"{prefix}…{value[-4:]}"
