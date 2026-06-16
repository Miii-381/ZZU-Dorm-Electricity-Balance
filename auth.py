"""处理统一认证登录、MFA 初始化和认证文件加密。"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
from os import getenv, makedirs, path, remove
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zzupy.app import CASClient

from config import (
    MFA_CHALLENGE_ENC_FILE,
    MFA_CHALLENGE_FILE,
    TOKEN_ENC_FILE,
    TOKEN_FILE,
    Settings,
    get_missing_required_env,
    get_settings,
)
from data import get_cst_time

logger = logging.getLogger(__name__)

MFA_REQUIRED_ENV = ("ACCOUNT", "PASSWORD")
MFA_CODE_ENV = "MFA_CODE"
MAGIC_V2 = b"ZEM2"
SALT_SIZE = 16
NONCE_SIZE = 12
ITERATIONS_V2 = 600_000

# v1 只用于兼容旧密文，新写入统一使用 v2。
LEGACY_SALT_V1 = b"ZZU-Electricity-Monitor-Salt-v1"
LEGACY_ITERATIONS_V1 = 100_000

# MFA 验证状态需要持久化/恢复的 zzupy 内部字段，集中在此：
# zzupy 调整 MFA 结构时只改这里，且字段缺失会明确报错而非静默失效。
MFA_STATE_FIELDS = ("state", "gid", "attest_server_url")
MFA_RESTORE_FLAGS = {"required": True, "secure_phone_available": True, "verified": False}


def derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    """派生 AES-256-GCM 密钥。"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_file(input_path: str, output_path: str, password: str) -> bool:
    """加密文件为 v2 密文。"""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        salt = os.urandom(SALT_SIZE)
        nonce = os.urandom(NONCE_SIZE)
        key = derive_key(password, salt, ITERATIONS_V2)

        with open(input_path, "rb") as f:
            plaintext = f.read()

        ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
        encrypted_data = base64.b64encode(MAGIC_V2 + salt + nonce + ciphertext)

        with open(output_path, "wb") as f:
            f.write(encrypted_data)

        print(f"加密成功: {input_path} -> {output_path}")
        return True

    except Exception as e:
        print(f"加密失败: {e}")
        return False


def _decrypt_v2(data: bytes, password: str) -> bytes:
    """按 v2 格式解密。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not data.startswith(MAGIC_V2):
        raise ValueError("不是 v2 密文格式")
    salt_start = len(MAGIC_V2)
    nonce_start = salt_start + SALT_SIZE
    ciphertext_start = nonce_start + NONCE_SIZE
    salt = data[salt_start:nonce_start]
    nonce = data[nonce_start:ciphertext_start]
    ciphertext = data[ciphertext_start:]
    key = derive_key(password, salt, ITERATIONS_V2)
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def _decrypt_v1(data: bytes, password: str) -> bytes:
    """按 v1 旧格式解密。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = data[:NONCE_SIZE]
    ciphertext = data[NONCE_SIZE:]
    key = derive_key(password, LEGACY_SALT_V1, LEGACY_ITERATIONS_V1)
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def _decrypt_payload(data: bytes, password: str) -> bytes:
    """按密文版本选择解密方式。"""
    if data.startswith(MAGIC_V2):
        return _decrypt_v2(data, password)
    return _decrypt_v1(data, password)


def decrypt_file(input_path: str, output_path: str, password: str) -> bool:
    """解密文件，自动兼容 v2/v1 格式。"""
    try:
        with open(input_path, "rb") as f:
            encrypted_data = f.read()

        data = base64.b64decode(encrypted_data)
        plaintext = _decrypt_payload(data, password)

        with open(output_path, "wb") as f:
            f.write(plaintext)

        print(f"解密成功: {input_path} -> {output_path}")
        return True

    except Exception as e:
        print(f"解密失败: {e}")
        return False


def encrypt_token_file() -> int:
    """加密 tokens.json。"""
    password = get_settings().password
    if not password:
        print("未设置 PASSWORD 环境变量")
        return 1
    if not path.exists(TOKEN_FILE):
        print(f"文件不存在: {TOKEN_FILE}")
        return 0
    return 0 if encrypt_file(TOKEN_FILE, TOKEN_ENC_FILE, password) else 1


def decrypt_token_file() -> int:
    """解密 tokens.enc。"""
    password = get_settings().password
    if not password:
        print("未设置 PASSWORD 环境变量")
        return 1
    if not path.exists(TOKEN_ENC_FILE):
        print(f"文件不存在: {TOKEN_ENC_FILE}")
        return 0
    return 0 if decrypt_file(TOKEN_ENC_FILE, TOKEN_FILE, password) else 1


def save_token(user_token: str, refresh_token: str, device_id: str | None = None) -> None:
    """保存 CAS token。"""
    token_data = {
        "user_token": user_token,
        "refresh_token": refresh_token,
        "saved_at": get_cst_time(),
    }
    if device_id:
        token_data["device_id"] = device_id

    dir_path = path.dirname(TOKEN_FILE)
    if dir_path and not path.exists(dir_path):
        makedirs(dir_path, exist_ok=True)

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, ensure_ascii=False, indent=2)

    logger.info(f"Token 已保存: {TOKEN_FILE}")


def load_token() -> dict[str, str] | None:
    """读取 CAS token。"""
    if not path.exists(TOKEN_FILE):
        logger.info("Token 文件不存在，将使用账号密码登录")
        return None

    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            token_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"读取 Token 文件失败: {e}")
        return None
    if not isinstance(token_data, dict):
        logger.warning("Token 文件格式无效，将使用账号密码登录")
        return None

    logger.info(f"Token 加载成功，保存时间: {token_data.get('saved_at', '未知')}")
    return token_data


class MFARequiredError(RuntimeError):
    """当前设备需要短信 MFA。"""


class CASLoginError(RuntimeError):
    """CAS 登录失败。"""


class CASAuthenticator:
    """CAS 登录状态机。"""

    def __init__(
        self,
        cas_client: CASClient | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        if cas_client is None:
            from zzupy.app import CASClient

            cas_client = CASClient(self.settings.account, self.settings.password)
        self.cas_client = cas_client
        self.device_id = self.settings.zzu_device_id

    def login(self) -> CASClient:
        """登录 CAS，优先复用 token，必要时回退账密。"""
        token_data = load_token()
        self._apply_device(token_data)

        if token_data and token_data.get("user_token") and token_data.get("refresh_token"):
            logger.info("尝试使用已保存的 Token 登录...")
            if self._login_with_saved_token(token_data):
                return self.cas_client

        self._ensure_mfa_ready()

        logger.info("使用账号密码进行 CAS 认证...")
        self.cas_client.login()

        if not self.cas_client.logged_in:
            raise CASLoginError("CAS 认证失败，无法获取登录态")

        logger.info("CAS 认证成功")
        self._save_current_token(token_data)
        return self.cas_client

    def close(self) -> None:
        """关闭 CAS 客户端资源。"""
        if hasattr(self.cas_client, "close"):
            self.cas_client.close()

    def _apply_device(self, token_data: dict[str, str] | None = None) -> None:
        """应用环境变量或 token 中保存的设备 ID。"""
        device_id = self.device_id or (token_data or {}).get("device_id")
        if device_id:
            self.cas_client.set_device(device_id)
            logger.info("已设置统一认证设备 ID")
        else:
            logger.info("未设置 ZZU_DEVICE_ID，将使用 ZZU.Py 默认设备 ID")

    def _ensure_mfa_ready(self) -> None:
        """在账密登录前确认当前设备不需要短信 MFA。"""
        try:
            if self.cas_client.mfa.is_required():
                raise MFARequiredError(
                    "当前统一认证设备需要短信 MFA，无法在 GitHub Actions 中自动完成。"
                    "请先在本地运行 auth.py 完成一次 MFA，并将设备加入可信设备；"
                    "也可以配置已可信设备的 ZZU_DEVICE_ID。"
                )
        except MFARequiredError:
            raise
        except Exception as e:
            logger.error(f"MFA 状态检测失败: {e}")
            raise

    def _login_with_saved_token(self, token_data: dict[str, str]) -> bool:
        """尝试使用持久化 token 登录。"""
        self.cas_client.set_token(
            token_data["user_token"],
            token_data["refresh_token"],
        )
        try:
            self.cas_client.login()
        except Exception as e:
            if self._can_retry_after_mfa_probe(e):
                try:
                    logger.info(
                        "ZZU.Py 已完成 MFA 探测且当前设备无需验证码，继续校验已保存 Token..."
                    )
                    self.cas_client.login()
                except Exception as retry_error:
                    logger.warning(f"Token 登录重试失败: {retry_error}")
            else:
                logger.warning(f"Token 登录失败: {e}")

        if self.cas_client.logged_in:
            logger.info("Token 登录成功")
            if self._should_save_token_snapshot(token_data):
                logger.info("检测到 Token 或设备信息已更新，正在保存认证文件...")
                self._save_current_token(token_data)
            return True

        logger.warning("Token 已失效，将使用账号密码登录")
        return False

    def _can_retry_after_mfa_probe(self, error: Exception) -> bool:
        """适配 ZZU.Py 7.x 在 token 校验前先探测 MFA 的登录流程。"""
        return (
            type(error).__name__ == "MFAError"
            and bool(getattr(self.cas_client.mfa, "state", None))
            and not bool(getattr(self.cas_client.mfa, "required", False))
        )

    def _should_save_token_snapshot(self, token_data: dict[str, str]) -> bool:
        """判断当前 CAS 状态是否需要重新写入 token 文件。"""
        device_id = self.device_id or token_data.get("device_id")
        return (
            self.cas_client.user_token != token_data.get("user_token")
            or self.cas_client.refresh_token != token_data.get("refresh_token")
            or bool(device_id and token_data.get("device_id") != device_id)
        )

    def _save_current_token(self, token_data: dict[str, str] | None = None) -> None:
        """持久化 CAS 客户端当前 token。"""
        if not self.cas_client.user_token or not self.cas_client.refresh_token:
            logger.warning("CAS 客户端未返回完整 Token，跳过保存")
            return

        save_token(
            self.cas_client.user_token,
            self.cas_client.refresh_token,
            self.device_id or (token_data or {}).get("device_id"),
        )


def configure_logging() -> None:
    """配置脚本日志。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def _remove_file(file_path: str) -> None:
    """删除文件，忽略不存在的路径。"""
    try:
        remove(file_path)
    except FileNotFoundError:
        return


def _remove_challenge_files() -> None:
    """删除 MFA 验证状态文件。"""
    _remove_file(MFA_CHALLENGE_FILE)
    _remove_file(MFA_CHALLENGE_ENC_FILE)


def _apply_device_to_cas(cas: CASClient, device_id: str | None = None) -> None:
    """设置统一认证设备 ID。"""
    if device_id:
        cas.set_device(device_id)
        logger.info("使用已配置的 ZZU_DEVICE_ID")
    else:
        logger.info("使用 ZZU.Py 默认 deviceId")


def _login_and_save_token(cas: CASClient, device_id: str | None = None) -> int:
    """登录 CAS 并保存 token。"""
    cas.login()
    if not cas.logged_in or not cas.user_token or not cas.refresh_token:
        logger.error("CAS 登录失败：未返回 token")
        return 1

    save_token(cas.user_token, cas.refresh_token, device_id)
    logger.info("Token 已保存。请运行 python auth.py encrypt 后，将 tokens.enc 放到 page 分支。")
    logger.info("如统一认证提示可信设备，请在安全中心将当前设备设为可信。")
    return 0


def _get_mfa(cas: CASClient) -> object:
    """获取 zzupy 的 MFA 句柄，接口缺失时给出清晰提示。"""
    mfa = getattr(cas, "mfa", None)
    if mfa is None:
        raise RuntimeError(
            "当前 zzupy 未提供 cas.mfa 接口，无法执行 MFA 流程；"
            "请检查 zzupy 版本（requirements.txt 要求 zzupy>=7.2.0）。"
        )
    return mfa


def _read_mfa_state(mfa: object) -> dict[str, str]:
    """读取需要持久化的 MFA 字段，字段缺失时报清晰错误。"""
    missing = [name for name in MFA_STATE_FIELDS if not hasattr(mfa, name)]
    if missing:
        raise RuntimeError(
            "zzupy 的 MFA 对象缺少字段: "
            + ", ".join(missing)
            + "；可能是 zzupy 版本不兼容，请对照 ZZU.Py 调整 MFA_STATE_FIELDS。"
        )
    return {name: getattr(mfa, name) for name in MFA_STATE_FIELDS}


def _write_mfa_attr(mfa: object, name: str, value: object) -> None:
    """写回 MFA 字段；字段不存在时报错，避免 setattr 静默新建无效属性。"""
    if not hasattr(mfa, name):
        raise RuntimeError(
            f"zzupy 的 MFA 对象不存在字段 {name!r}，无法恢复验证状态；"
            "可能是 zzupy 版本不兼容。"
        )
    setattr(mfa, name, value)


def _save_challenge(cas: CASClient, device_id: str | None = None) -> bool:
    """加密保存可继续验证的 MFA 状态。"""
    password = get_settings().password
    if not password:
        logger.error("缺少 PASSWORD，无法加密 MFA 验证状态")
        return False

    challenge = {
        **_read_mfa_state(_get_mfa(cas)),
        "device_id": device_id or "",
        "created_at": get_cst_time(),
    }

    dir_path = path.dirname(MFA_CHALLENGE_FILE)
    if dir_path and not path.exists(dir_path):
        makedirs(dir_path, exist_ok=True)

    with open(MFA_CHALLENGE_FILE, "w", encoding="utf-8") as f:
        json.dump(challenge, f, ensure_ascii=False, indent=2)

    try:
        if not encrypt_file(MFA_CHALLENGE_FILE, MFA_CHALLENGE_ENC_FILE, password):
            return False
        logger.info("MFA 验证状态已加密保存，可在第二次 Actions 中输入验证码继续")
        return True
    finally:
        _remove_file(MFA_CHALLENGE_FILE)


def _load_challenge() -> dict[str, str] | None:
    """读取上一次保存的 MFA 状态。"""
    password = get_settings().password
    if not password:
        logger.error("缺少 PASSWORD，无法解密 MFA 验证状态")
        return None
    if not path.exists(MFA_CHALLENGE_ENC_FILE):
        logger.error("未找到 MFA 验证状态，请先运行 request 模式发送短信验证码")
        return None

    try:
        if not decrypt_file(MFA_CHALLENGE_ENC_FILE, MFA_CHALLENGE_FILE, password):
            return None
        with open(MFA_CHALLENGE_FILE, encoding="utf-8") as f:
            challenge = json.load(f)
    finally:
        _remove_file(MFA_CHALLENGE_FILE)

    missing_fields = [field for field in MFA_STATE_FIELDS if field not in challenge]
    if missing_fields:
        logger.error("MFA 验证状态缺少字段: %s", ", ".join(missing_fields))
        return None
    return challenge


def _prepare_cas() -> CASClient | None:
    """创建 CAS 客户端。"""
    missing_vars = get_missing_required_env(MFA_REQUIRED_ENV)
    if missing_vars:
        logger.error("缺少必要的环境变量: %s", ", ".join(missing_vars))
        return None
    settings = get_settings()
    from zzupy.app import CASClient

    return CASClient(settings.account, settings.password)


def _restore_challenge(cas: CASClient, challenge: dict[str, str]) -> None:
    """恢复 ZZU.Py 的 MFA 状态。

    ZZU.Py 7.x 暂无稳定序列化入口；内部字段集中在 MFA_STATE_FIELDS /
    MFA_RESTORE_FLAGS，字段缺失时会明确报错而非静默失效。
    """
    mfa = _get_mfa(cas)
    _write_mfa_attr(mfa, "state", challenge["state"])
    _write_mfa_attr(mfa, "gid", challenge["gid"])
    _write_mfa_attr(mfa, "attest_server_url", challenge.get("attest_server_url") or "")
    for name, value in MFA_RESTORE_FLAGS.items():
        _write_mfa_attr(mfa, name, value)


def run_local() -> int:
    """执行本地交互初始化。"""
    cas = _prepare_cas()
    if cas is None:
        return 1

    device_id = get_settings().zzu_device_id
    try:
        _apply_device_to_cas(cas, device_id)

        if cas.mfa.is_required():
            logger.info("当前设备需要 MFA，正在发送短信验证码...")
            cas.mfa.send_sms()
            code = input("请输入短信验证码: ").strip()
            if not code:
                logger.error("短信验证码为空")
                return 1
            try:
                cas.mfa.verify_sms(code)
            except Exception as e:
                logger.error(f"短信验证码校验失败（可能已过期或填写错误）: {e}")
                return 1
            logger.info("MFA 验证成功")
        else:
            logger.info("当前设备无需 MFA")

        return _login_and_save_token(cas, device_id)
    finally:
        if hasattr(cas, "close"):
            cas.close()


def request_mfa() -> int:
    """发送短信验证码并保存 MFA 状态。"""
    cas = _prepare_cas()
    if cas is None:
        return 1

    device_id = get_settings().zzu_device_id
    try:
        _apply_device_to_cas(cas, device_id)

        if cas.mfa.is_required():
            logger.info("当前设备需要 MFA，正在发送短信验证码...")
            cas.mfa.send_sms()
            if not _save_challenge(cas, device_id):
                return 1
            logger.info("短信验证码已发送。请尽快再次运行 workflow 的 verify 模式。")
            return 0

        logger.info("当前设备无需 MFA，将直接登录并保存 token")
        _remove_challenge_files()
        return _login_and_save_token(cas, device_id)
    finally:
        if hasattr(cas, "close"):
            cas.close()


def verify_mfa(code: str | None = None) -> int:
    """使用短信验证码完成 MFA 并保存 token。"""
    sms_code = (code or getenv(MFA_CODE_ENV) or "").strip()
    if not sms_code:
        logger.error("缺少短信验证码。请在 workflow_dispatch 的 code 输入框中填写验证码")
        return 1

    challenge = _load_challenge()
    if challenge is None:
        return 1

    cas = _prepare_cas()
    if cas is None:
        return 1

    device_id = challenge.get("device_id") or get_settings().zzu_device_id

    try:
        _apply_device_to_cas(cas, device_id)
        _restore_challenge(cas, challenge)
        try:
            cas.mfa.verify_sms(sms_code)
        except Exception as e:
            logger.error(f"短信验证码校验失败（可能已过期或填写错误）: {e}")
            return 1
        logger.info("MFA 验证成功")

        result = _login_and_save_token(cas, device_id)
        if result == 0:
            _remove_challenge_files()
        return result
    finally:
        if hasattr(cas, "close"):
            cas.close()


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数。"""
    parser = argparse.ArgumentParser(description="ZZU 统一认证工具")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("local", "request", "verify", "encrypt", "decrypt"),
        default="local",
        help="local=本地交互；request=发送验证码；verify=输入验证码完成验证；encrypt/decrypt=处理 token 密文",
    )
    parser.add_argument("--code", help="verify 模式使用的短信验证码")
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行认证命令。"""
    args = build_parser().parse_args([] if argv is None else argv)
    if args.mode == "request":
        return request_mfa()
    if args.mode == "verify":
        return verify_mfa(args.code)
    if args.mode == "encrypt":
        return encrypt_token_file()
    if args.mode == "decrypt":
        return decrypt_token_file()
    return run_local()


if __name__ == "__main__":
    configure_logging()
    sys.exit(main(sys.argv[1:]))
