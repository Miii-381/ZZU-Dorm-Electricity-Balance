"""读写页面 JSON 数据并维护索引。"""
import json
import logging
from datetime import datetime
from glob import glob
from os import getenv, makedirs, path, remove, replace
from tempfile import NamedTemporaryFile

import pytz

from config import DATA_DIR, LAST_RECORDS_FILE, NOTIFY_STATE_FILE, TIME_FILE, TIMEZONE

logger = logging.getLogger(__name__)

SUMMARY_TEMPLATE = """
## Balance Record
| **剩余电费** | **照明房间** | **空调房间** |
| --------------- | -------------------- | -------------- |
| {time}  |    {light_Balance}      |    {ac_Balance} |
"""


def get_cst_time(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """返回中国标准时间字符串。"""
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz).strftime(fmt)


def load_json(
    file_path: str,
    *,
    missing_ok: bool = True,
    corrupt_ok: bool = False,
) -> list | dict | None:
    """读取 JSON 文件。"""
    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if not missing_ok:
            raise
        logger.warning(f"JSON 文件不存在: {file_path}")
        return None
    except json.JSONDecodeError as e:
        if not corrupt_ok:
            logger.error(f"JSON 文件损坏: {file_path}: {e}")
            raise
        logger.warning(f"加载 JSON 文件失败 {file_path}: {e}")
        return None


def save_json(data: list | dict, file_path: str, indent: int = 2) -> bool:
    """原子写入 JSON 文件。"""
    dir_path = path.dirname(file_path)
    if dir_path and not path.exists(dir_path):
        makedirs(dir_path, exist_ok=True)

    tmp_path = ""
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=dir_path or ".", delete=False) as f:
            tmp_path = f.name
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.write("\n")
            f.flush()

        replace(tmp_path, file_path)
        tmp_path = ""
        logger.info(f"数据已保存: {file_path}")
        return True
    finally:
        if tmp_path and path.exists(tmp_path):
            try:
                remove(tmp_path)
            except OSError:
                logger.warning(f"清理临时 JSON 文件失败: {tmp_path}")


def load_record_list(file_path: str, *, missing_ok: bool = False) -> list[dict]:
    """读取电量记录列表，损坏或结构异常时中止。"""
    if missing_ok and not path.exists(file_path):
        return []
    loaded = load_json(file_path, missing_ok=False)
    if not isinstance(loaded, list):
        raise ValueError(f"电量记录文件格式无效: {file_path}")
    return loaded


def load_optional_json(file_path: str) -> list | dict | None:
    """读取可丢弃状态文件，失败时返回 None。"""
    if not path.exists(file_path):
        return None
    try:
        return load_json(file_path, corrupt_ok=True)
    except OSError as e:
        logger.warning(f"加载 JSON 文件失败 {file_path}: {e}")
        return None


def list_json_months() -> list[str]:
    """列出 JSON 月份文件（仅保留可解析为 YYYY-MM 的合法文件名）。"""
    if not path.exists(DATA_DIR):
        return []

    pattern = path.join(DATA_DIR, "[0-9][0-9][0-9][0-9]-[0-9][0-9].json")
    parsed = []
    for file_path in glob(pattern):
        name = path.splitext(path.basename(file_path))[0]
        try:
            parsed.append((datetime.strptime(name, "%Y-%m"), name))
        except ValueError:
            logger.warning(f"忽略非法月份文件名: {file_path}")
    return [name for _, name in sorted(parsed, reverse=True)]


def normalize_record(record: dict) -> dict | None:
    """把电量记录整理为页面使用的字段。"""
    try:
        return {
            "time": str(record["time"]),
            "light_Balance": float(record["light_Balance"]),
            "ac_Balance": float(record["ac_Balance"]),
        }
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"跳过无效电量记录: {e}")
        return None


def load_notify_state() -> dict:
    """读取通知去重状态。"""
    loaded = load_optional_json(NOTIFY_STATE_FILE)
    return loaded if isinstance(loaded, dict) else {}


def save_notify_state(state: dict) -> None:
    """保存通知去重状态。"""
    save_json(state, NOTIFY_STATE_FILE)


def record_energy_data(data: dict) -> list[dict] | None:
    """追加一条电量记录到当月文件。"""
    month_str = get_cst_time("%Y-%m")
    file_path = path.join(DATA_DIR, f"{month_str}.json")
    normalized = normalize_record(data)
    if not normalized:
        return None

    existing_data = load_record_list(file_path, missing_ok=True)
    existing_data.append(normalized)
    save_json(existing_data, file_path)

    return existing_data


def update_time_list() -> list[str]:
    """刷新可用月份列表。"""
    if not path.exists(DATA_DIR):
        raise FileNotFoundError(f"数据目录不存在: {DATA_DIR}")

    json_files = list_json_months()

    save_json(json_files, TIME_FILE)
    logger.info("时间列表已更新")

    return json_files


def update_last_records(current_month_data: list[dict] | None = None) -> None:
    """刷新最近 30 条记录缓存。"""
    time_list = update_time_list()

    if current_month_data is None and time_list:
        current_month_file = path.join(DATA_DIR, f"{time_list[0]}.json")
        current_month_data = load_record_list(current_month_file)

    current_count = len(current_month_data) if current_month_data else 0

    if current_count < 30 and len(time_list) > 1:
        prev_month_file = path.join(DATA_DIR, f"{time_list[1]}.json")
        prev_month_data = load_record_list(prev_month_file)

        need_count = min(30 - current_count, len(prev_month_data))
        combined_data = prev_month_data[-need_count:] + (current_month_data or [])
    else:
        combined_data = current_month_data or []

    last_30 = combined_data[-30:]
    save_json(last_30, LAST_RECORDS_FILE)

    logger.info("最近 30 条记录已更新")


def write_step_summary(record: dict[str, float | str]) -> None:
    """写入 GitHub Actions Step Summary。"""
    summary_path = getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(
            SUMMARY_TEMPLATE.format(
                time=record["time"],
                light_Balance=record["light_Balance"],
                ac_Balance=record["ac_Balance"],
            )
        )
        f.write("\n")
