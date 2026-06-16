"""查询电量并应用重试策略。"""
import logging

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from zzupy.app import ECardClient

from auth import CASAuthenticator
from config import (
    INITIAL_WAIT,
    MAX_WAIT,
    RETRY_ATTEMPTS,
    RETRY_MULTIPLIER,
    get_settings,
)

logger = logging.getLogger(__name__)

# 可重试的异常按"类名"匹配，刻意不 import zzupy 的具体异常类：
# 这样即使 zzupy 升级后调整了异常模块路径或重命名了类，本模块也不会因
# ImportError 而整体崩溃；最坏情况只是某个被改名的异常不再触发重试（安全降级）。
# 需要扩充时把类名加进集合即可（与 auth.py 中按类名匹配 "MFAError" 的做法一致）。
RETRYABLE_EXCEPTION_NAMES = frozenset(
    {
        # zzupy 抛出的临时性错误
        "LoginError",
        "NetworkError",
        "NotLoggedInError",
        # requests / urllib3 网络层错误（若 zzupy 不包装而直接透传）
        "ConnectionError",
        "Timeout",
        "ConnectTimeout",
        "ReadTimeout",
        "ChunkedEncodingError",
    }
)


def should_retry_exception(exception: BaseException) -> bool:
    """按异常类名（含父类）判断是否值得重试，避免与 zzupy 的具体异常类硬耦合。"""
    return any(
        klass.__name__ in RETRYABLE_EXCEPTION_NAMES for klass in type(exception).__mro__
    )


def create_retry_decorator(stop_attempts: int = RETRY_ATTEMPTS, wait_strategy=None):
    """创建电量查询重试装饰器。"""
    if wait_strategy is None:
        wait_strategy = wait_exponential(
            multiplier=RETRY_MULTIPLIER,
            min=INITIAL_WAIT,
            max=MAX_WAIT,
        )

    return retry(
        stop=stop_after_attempt(stop_attempts),
        wait=wait_strategy,
        retry=retry_if_exception(should_retry_exception),
        reraise=True,
    )


class EnergyMonitor:
    """电量查询入口。"""

    def __init__(self, authenticator: CASAuthenticator | None = None):
        self.authenticator = authenticator or CASAuthenticator()
        self.get_balance = create_retry_decorator()(self._get_balance)

    def close(self) -> None:
        """释放认证客户端资源。"""
        self.authenticator.close()

    def _open_ecard(self) -> ECardClient:
        """创建并登录一卡通客户端。"""
        cas_client = self.authenticator.login()
        logger.info("创建一卡通客户端...")
        ecard = ECardClient(cas_client)
        enter = getattr(ecard, "__enter__", None)
        if enter is not None:
            ecard = enter()
        try:
            ecard.login()
            logger.info("一卡通登录成功")
            return ecard
        except Exception:
            self._close_ecard(ecard)
            raise

    def _close_ecard(self, ecard: ECardClient) -> None:
        """关闭一卡通客户端。"""
        exit_method = getattr(ecard, "__exit__", None)
        if exit_method is not None:
            exit_method(None, None, None)
            return

        close = getattr(ecard, "close", None)
        if close is not None:
            close()

    def _get_room_balance(
        self,
        ecard: ECardClient,
        room_name: str,
        room_id: str,
    ) -> tuple[float, ECardClient]:
        """查询单个房间，认证失效时刷新登录态后重试一次。"""
        try:
            return ecard.get_remaining_energy(room=room_id), ecard
        except Exception as e:
            if not should_retry_exception(e):
                raise
            logger.warning(f"{room_name} 查询失败，刷新登录态后重试: {e}")
            self._close_ecard(ecard)
            refreshed_ecard = self._open_ecard()
            try:
                return refreshed_ecard.get_remaining_energy(room=room_id), refreshed_ecard
            except Exception:
                self._close_ecard(refreshed_ecard)
                raise

    def _get_balance(self) -> dict[str, float]:
        """获取电量余额。"""
        settings = get_settings()
        if settings.light_room is None or settings.ac_room is None:
            raise RuntimeError("缺少房间环境变量")

        logger.info("获取电量余额...")
        ecard = self._open_ecard()
        try:
            light_balance, ecard = self._get_room_balance(
                ecard, "照明", settings.light_room,
            )
            ac_balance, ecard = self._get_room_balance(
                ecard, "空调", settings.ac_room,
            )
        finally:
            self._close_ecard(ecard)

        logger.info(f"照明: {light_balance} 度, 空调: {ac_balance} 度")

        return {
            "light_Balance": light_balance,
            "ac_Balance": ac_balance,
        }
