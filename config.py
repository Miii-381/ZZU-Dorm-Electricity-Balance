"""集中管理路径、阈值和核心环境变量。"""
import os
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

# 电量阈值
THRESHOLD = 10.0
EXCELLENT_THRESHOLD = 100.0

# 数据文件
DATA_DIR = os.getenv("DATA_DIR", "./page/data")
TOKEN_FILE = os.path.join(DATA_DIR, "tokens.json")
TOKEN_ENC_FILE = os.path.join(DATA_DIR, "tokens.enc")
MFA_CHALLENGE_FILE = os.path.join(DATA_DIR, "mfa.json")
MFA_CHALLENGE_ENC_FILE = os.path.join(DATA_DIR, "mfa.enc")
NOTIFY_STATE_FILE = os.path.join(DATA_DIR, "notify_state.json")
TIME_FILE = os.path.join(DATA_DIR, "time.json")
LAST_RECORDS_FILE = os.path.join(DATA_DIR, "last_30_records.json")

# 重试参数
RETRY_ATTEMPTS = 5
RETRY_MULTIPLIER = 1
INITIAL_WAIT = 15
MAX_WAIT = 120

# 运行时区
TIMEZONE = "Asia/Shanghai"

# 必需环境变量
MONITOR_REQUIRED_ENV = ("ACCOUNT", "PASSWORD", "LIGHT_ROOM", "AC_ROOM")

# 网络请求
REQUEST_TIMEOUT = 10


@dataclass(frozen=True)
class Settings:
    """核心环境变量快照。"""

    account: str | None
    password: str | None
    light_room: str | None
    ac_room: str | None
    zzu_device_id: str | None
    notify_dedup: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取核心环境变量快照。"""
    return Settings(
        account=os.getenv("ACCOUNT"),
        password=os.getenv("PASSWORD"),
        light_room=os.getenv("LIGHT_ROOM"),
        ac_room=os.getenv("AC_ROOM"),
        zzu_device_id=os.getenv("ZZU_DEVICE_ID"),
        notify_dedup=is_truthy_env("NOTIFY_DEDUP"),
    )


def get_missing_required_env(names: Iterable[str]) -> list[str]:
    """列出缺失的必需环境变量名。"""
    return [name for name in names if not os.getenv(name)]


def is_truthy_env(name: str) -> bool:
    """按常见布尔写法读取环境变量。"""
    value = os.getenv(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_valid_room_id(room_id: str | None) -> bool:
    """检查 ZZU.Py 房间 ID 的基本结构。"""
    if not room_id:
        return False
    if room_id.count("--") != 1:
        return False
    left, separator, right = room_id.partition("--")
    parts = (*left.split("-"), *right.split("-"))
    return bool(separator and len(parts) == 4 and all(part.isdigit() for part in parts))


def validate_room_settings(settings: Settings | None = None) -> None:
    """提前校验照明和空调房间 ID。"""
    settings = settings or get_settings()
    rooms = {
        "LIGHT_ROOM": settings.light_room,
        "AC_ROOM": settings.ac_room,
    }
    invalid_names = [name for name, room_id in rooms.items() if not is_valid_room_id(room_id)]
    if invalid_names:
        raise ValueError(
            "房间 ID 格式不正确: "
            + ", ".join(invalid_names)
            + "。请使用房间查询器复制完整编号，例如 99-1--1-101。"
        )
