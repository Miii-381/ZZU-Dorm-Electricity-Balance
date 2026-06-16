"""执行一次电量监控任务。"""
import logging
import sys

from config import MONITOR_REQUIRED_ENV, get_missing_required_env, validate_room_settings
from data import (
    get_cst_time,
    record_energy_data,
    update_last_records,
    write_step_summary,
)
from monitor import EnergyMonitor
from notify import notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_monitor_once() -> dict[str, float | str]:
    """执行一次电量监控任务。"""
    logger.info("启动宿舍电量监控程序...")

    missing_vars = get_missing_required_env(MONITOR_REQUIRED_ENV)
    if missing_vars:
        raise RuntimeError(f"缺少必要的环境变量: {', '.join(missing_vars)}")
    validate_room_settings()

    monitor = EnergyMonitor()
    try:
        balances = monitor.get_balance()
    finally:
        monitor.close()

    logger.info(
        f"照明剩余电量: {balances['light_Balance']} 度, "
        f"空调剩余电量: {balances['ac_Balance']} 度"
    )

    notify(balances)

    latest_record = {
        "time": get_cst_time("%m-%d %H:%M:%S"),
        "light_Balance": balances["light_Balance"],
        "ac_Balance": balances["ac_Balance"],
    }

    current_month_data = record_energy_data(latest_record)
    update_last_records(current_month_data)
    write_step_summary(latest_record)

    logger.info("程序运行结束")
    return latest_record


def main() -> int:
    """命令行入口。"""
    try:
        run_monitor_once()
    except Exception as e:
        logger.error(f"电量监控任务失败: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
