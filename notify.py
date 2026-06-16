"""注册通知渠道并按电量状态调度发送。"""
import json
import logging
import os
import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from email.mime.text import MIMEText
from urllib.parse import quote
from uuid import uuid4

import requests

from config import EXCELLENT_THRESHOLD, REQUEST_TIMEOUT, THRESHOLD, get_settings
from data import get_cst_time, load_notify_state, save_notify_state

logger = logging.getLogger(__name__)


class NotifyError(RuntimeError):
    """通知渠道返回失败响应。"""


SendFunc = Callable[[dict[str, str], str, str], None]


@dataclass(frozen=True)
class Channel:
    """通知渠道声明。"""

    name: str
    send: SendFunc
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    # True 表示每次运行发送；False 只在低电量时发送。
    daily: bool = False


CHANNELS: dict[str, Channel] = {}


def channel(
    name: str,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
    daily: bool = False,
):
    """注册通知渠道。"""

    def register(func: SendFunc) -> SendFunc:
        CHANNELS[name] = Channel(
            name=name,
            send=func,
            required=required,
            optional=optional,
            daily=daily,
        )
        return func

    return register


def _has_config_value(value: str | None) -> bool:
    """判断环境变量是否提供了有效内容。"""
    return bool(value and value.strip(" ,"))


def channel_config(ch: Channel) -> dict[str, str] | None:
    """读取渠道环境变量。"""
    values = {key: os.getenv(key) for key in (*ch.required, *ch.optional)}
    if any(not _has_config_value(values[key]) for key in ch.required):
        return None
    return {key: value for key, value in values.items() if value}


def dispatch(ch: Channel, title: str, content: str) -> bool:
    """发送单个渠道通知。"""
    cfg = channel_config(ch)
    if cfg is None:
        logger.debug(f"未配置 {ch.name} 参数，跳过")
        return False

    ch.send(cfg, title, content)
    logger.info(f"{ch.name} 通知发送成功")
    return True


def _json_or_raise(response: requests.Response) -> dict:
    """解析 JSON 响应。"""
    try:
        return response.json()
    except ValueError as e:
        raise NotifyError(f"非 JSON 响应: {response.text[:200]}") from e


# Telegram MarkdownV2 官方保留字符。
_MARKDOWN_V2_RESERVED = "_*[]()~`>#+-=|{}.!"


def escape_markdown_v2(text: str) -> str:
    """转义 Telegram MarkdownV2 文本。"""
    return "".join(f"\\{c}" if c in _MARKDOWN_V2_RESERVED else c for c in text)


def split_csv(value: str | None) -> list[str]:
    """拆分逗号分隔配置。"""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def split_csv_int(value: str | None, field_name: str) -> list[int]:
    """拆分逗号分隔数字配置。"""
    result = []
    for item in split_csv(value):
        try:
            result.append(int(item))
        except ValueError as e:
            raise NotifyError(f"{field_name} 必须是数字: {item}") from e
    return result


# 通知渠道


@channel(
    "Telegram",
    required=("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
    daily=True,
)
def send_telegram(cfg: dict[str, str], title: str, content: str) -> None:
    url = f"https://api.telegram.org/bot{cfg['TELEGRAM_BOT_TOKEN']}/sendMessage"
    payload = {
        "chat_id": cfg["TELEGRAM_CHAT_ID"],
        "text": f"*{escape_markdown_v2(title)}*\n\n{escape_markdown_v2(content)}",
        "parse_mode": "MarkdownV2",
    }
    result = _json_or_raise(requests.post(url, data=payload, timeout=REQUEST_TIMEOUT))
    if not result.get("ok"):
        raise NotifyError(result.get("description"))


@channel("Server酱", required=("SERVERCHAN_KEY",))
def send_serverchan(cfg: dict[str, str], title: str, content: str) -> None:
    result = _json_or_raise(
        requests.post(
            f"https://sctapi.ftqq.com/{cfg['SERVERCHAN_KEY']}.send",
            data={"title": title, "desp": content},
            timeout=REQUEST_TIMEOUT,
        )
    )
    if result.get("code") != 0:
        raise NotifyError(result.get("message"))


@channel("邮件", required=("EMAIL", "SMTP_CODE", "SMTP_SERVER"))
def send_email(cfg: dict[str, str], title: str, content: str) -> None:
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = title
    msg["From"] = cfg["EMAIL"]
    msg["To"] = cfg["EMAIL"]

    client = smtplib.SMTP_SSL(cfg["SMTP_SERVER"], smtplib.SMTP_SSL_PORT)
    try:
        client.login(cfg["EMAIL"], cfg["SMTP_CODE"])
        client.sendmail(cfg["EMAIL"], cfg["EMAIL"], msg.as_string())
    finally:
        client.quit()


@channel("Bark", required=("BARK_KEY",), optional=("BARK_URL",))
def send_bark(cfg: dict[str, str], title: str, content: str) -> None:
    base_url = cfg.get("BARK_URL", "https://api.day.app").rstrip("/")
    # title/content 含换行、中文、emoji，必须整体 URL 编码（safe="" 连 / 也编码），
    # 否则拼进 GET 路径会被截断或被 urllib3 判为非法 URL。
    url = f"{base_url}/{cfg['BARK_KEY']}/{quote(title, safe='')}/{quote(content, safe='')}"
    result = _json_or_raise(requests.get(url, timeout=REQUEST_TIMEOUT))
    if result.get("code") != 200:
        raise NotifyError(result.get("message"))


@channel("钉钉", required=("DINGTALK_WEBHOOK",), optional=("DINGTALK_SECRET",))
def send_dingtalk(cfg: dict[str, str], title: str, content: str) -> None:
    url = cfg["DINGTALK_WEBHOOK"]
    secret = cfg.get("DINGTALK_SECRET")
    if secret:
        import base64
        import hashlib
        import hmac
        import time

        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        sign = base64.b64encode(hmac_code).decode("utf-8")
        url = f"{url}&timestamp={timestamp}&sign={sign}"

    payload = {"msgtype": "text", "text": {"content": f"{title}\n\n{content}"}}
    result = _json_or_raise(requests.post(url, json=payload, timeout=REQUEST_TIMEOUT))
    if result.get("errcode") != 0:
        raise NotifyError(result.get("errmsg"))


@channel("飞书", required=("FEISHU_WEBHOOK",), optional=("FEISHU_SECRET",))
def send_feishu(cfg: dict[str, str], title: str, content: str) -> None:
    secret = cfg.get("FEISHU_SECRET")
    if secret:
        import base64
        import hashlib
        import hmac
        import time

        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        sign = base64.b64encode(hmac_code).decode("utf-8")
        payload = {
            "timestamp": timestamp,
            "sign": sign,
            "msg_type": "text",
            "content": {"text": f"{title}\n\n{content}"},
        }
    else:
        payload = {"msg_type": "text", "content": {"text": f"{title}\n\n{content}"}}

    result = _json_or_raise(
        requests.post(cfg["FEISHU_WEBHOOK"], json=payload, timeout=REQUEST_TIMEOUT)
    )
    if result.get("code") != 0:
        raise NotifyError(result.get("msg"))


@channel("go-cqhttp", required=("GOCQHTTP_URL", "GOCQHTTP_TARGET"), optional=("GOCQHTTP_TOKEN",))
def send_gocqhttp(cfg: dict[str, str], title: str, content: str) -> None:
    headers = {}
    if cfg.get("GOCQHTTP_TOKEN"):
        headers["Authorization"] = f"Bearer {cfg['GOCQHTTP_TOKEN']}"

    payload = {"user_id": cfg["GOCQHTTP_TARGET"], "message": f"{title}\n\n{content}"}
    result = _json_or_raise(
        requests.post(
            f"{cfg['GOCQHTTP_URL']}/send_private_msg",
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    )
    if result.get("status") != "ok":
        raise NotifyError(result.get("message"))


@channel("Gotify", required=("GOTIFY_URL", "GOTIFY_TOKEN"))
def send_gotify(cfg: dict[str, str], title: str, content: str) -> None:
    response = requests.post(
        f"{cfg['GOTIFY_URL']}/message",
        json={"title": title, "message": content, "priority": 5},
        headers={"X-Gotify-Key": cfg["GOTIFY_TOKEN"]},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise NotifyError(response.text)


@channel("iGot", required=("IGOT_KEY",))
def send_igot(cfg: dict[str, str], title: str, content: str) -> None:
    result = _json_or_raise(
        requests.post(
            f"https://push.hellyw.com/{cfg['IGOT_KEY']}",
            json={"title": title, "content": content},
            timeout=REQUEST_TIMEOUT,
        )
    )
    if result.get("ret") != 0:
        raise NotifyError(result.get("errMsg"))


@channel("PushDeer", required=("PUSHDEER_KEY",))
def send_pushdeer(cfg: dict[str, str], title: str, content: str) -> None:
    payload = {"pushkey": cfg["PUSHDEER_KEY"], "text": title, "desp": content, "type": "text"}
    result = _json_or_raise(
        requests.post(
            "https://api2.pushdeer.com/message/push", data=payload, timeout=REQUEST_TIMEOUT
        )
    )
    if result.get("code") != 0:
        raise NotifyError(result.get("error"))


@channel(
    "WxPusher",
    required=("WXPUSHER_APP_TOKEN",),
    optional=("WXPUSHER_UIDS", "WXPUSHER_TOPIC_IDS"),
)
def send_wxpusher(cfg: dict[str, str], title: str, content: str) -> None:
    uids = split_csv(cfg.get("WXPUSHER_UIDS"))
    topic_ids = split_csv_int(cfg.get("WXPUSHER_TOPIC_IDS"), "WXPUSHER_TOPIC_IDS")
    if not uids and not topic_ids:
        raise NotifyError("WxPusher 需要配置 WXPUSHER_UIDS 或 WXPUSHER_TOPIC_IDS")

    payload: dict[str, object] = {
        "appToken": cfg["WXPUSHER_APP_TOKEN"],
        "summary": title[:100],
        "content": content,
        "contentType": 1,
    }
    if uids:
        payload["uids"] = uids
    if topic_ids:
        payload["topicIds"] = topic_ids

    result = _json_or_raise(
        requests.post(
            "https://wxpusher.zjiecode.com/api/send/message",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    )
    if result.get("code") != 1000:
        raise NotifyError(result.get("msg") or str(result))


@channel("Chanify", required=("CHANIFY_TOKEN",), optional=("CHANIFY_URL",))
def send_chanify(cfg: dict[str, str], title: str, content: str) -> None:
    base_url = cfg.get("CHANIFY_URL", "https://api.chanify.net").rstrip("/")
    response = requests.post(
        f"{base_url}/v1/sender/{cfg['CHANIFY_TOKEN']}",
        json={"title": title, "text": content},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise NotifyError(response.text)
    if response.headers.get("content-type", "").startswith("application/json"):
        result = response.json()
        if result.get("res", 0) != 0:
            raise NotifyError(result.get("msg") or str(result))


@channel("Synology Chat", required=("SYNOLOGY_CHAT_URL", "SYNOLOGY_CHAT_TOKEN"))
def send_synology_chat(cfg: dict[str, str], title: str, content: str) -> None:
    url = (
        f"{cfg['SYNOLOGY_CHAT_URL']}?api=SYNO.Chat.External&method=incoming"
        f"&version=2&token={cfg['SYNOLOGY_CHAT_TOKEN']}"
    )
    payload = {"payload": json.dumps({"text": f"{title}\n\n{content}"})}
    result = _json_or_raise(requests.post(url, data=payload, timeout=REQUEST_TIMEOUT))
    if not result.get("success"):
        raise NotifyError(str(result))


@channel("PushPlus", required=("PUSHPLUS_TOKEN",))
def send_pushplus(cfg: dict[str, str], title: str, content: str) -> None:
    payload = {"token": cfg["PUSHPLUS_TOKEN"], "title": title, "content": content}
    result = _json_or_raise(
        requests.post("https://www.pushplus.plus/send", json=payload, timeout=REQUEST_TIMEOUT)
    )
    if result.get("code") != 200:
        raise NotifyError(result.get("msg"))


@channel(
    "企业微信",
    required=("WECOM_CORP_ID", "WECOM_AGENT_ID", "WECOM_SECRET"),
    optional=("WECOM_TOUSER",),
)
def send_wecom(cfg: dict[str, str], title: str, content: str) -> None:
    token_result = _json_or_raise(
        requests.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
            f"?corpid={cfg['WECOM_CORP_ID']}&corpsecret={cfg['WECOM_SECRET']}",
            timeout=REQUEST_TIMEOUT,
        )
    )
    if token_result.get("errcode") != 0:
        raise NotifyError(token_result.get("errmsg"))

    payload = {
        "touser": cfg.get("WECOM_TOUSER", "@all"),
        "msgtype": "text",
        "agentid": cfg["WECOM_AGENT_ID"],
        "text": {"content": f"{title}\n\n{content}"},
    }
    result = _json_or_raise(
        requests.post(
            "https://qyapi.weixin.qq.com/cgi-bin/message/send"
            f"?access_token={token_result['access_token']}",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    )
    if result.get("errcode") != 0:
        raise NotifyError(result.get("errmsg"))


@channel("企业微信群机器人", required=("WECOM_BOT_WEBHOOK",))
def send_wecom_bot(cfg: dict[str, str], title: str, content: str) -> None:
    payload = {"msgtype": "text", "text": {"content": f"{title}\n\n{content}"}}
    result = _json_or_raise(
        requests.post(cfg["WECOM_BOT_WEBHOOK"], json=payload, timeout=REQUEST_TIMEOUT)
    )
    if result.get("errcode") != 0:
        raise NotifyError(result.get("errmsg"))


@channel("Qmsg酱", required=("QMSG_KEY",), optional=("QMSG_QQ",))
def send_qmsg(cfg: dict[str, str], title: str, content: str) -> None:
    payload = {"msg": f"{title}\n\n{content}"}
    if cfg.get("QMSG_QQ"):
        payload["qq"] = cfg["QMSG_QQ"]

    result = _json_or_raise(
        requests.post(
            f"https://qmsg.zendee.cn/send/{cfg['QMSG_KEY']}", data=payload, timeout=REQUEST_TIMEOUT
        )
    )
    if result.get("code") != 0:
        raise NotifyError(result.get("reason"))


@channel("智能微秘书", required=("AIBOTK_KEY", "AIBOTK_TARGET"))
def send_aibotk(cfg: dict[str, str], title: str, content: str) -> None:
    payload = {"to": cfg["AIBOTK_TARGET"], "type": 1, "content": f"{title}\n\n{content}"}
    result = _json_or_raise(
        requests.post(
            "https://api-bot.aibotk.com/openapi/v1/chat/send",
            json=payload,
            headers={"Authorization": f"Bearer {cfg['AIBOTK_KEY']}"},
            timeout=REQUEST_TIMEOUT,
        )
    )
    if result.get("code") != 0:
        raise NotifyError(result.get("message"))


@channel("PushMe", required=("PUSHME_KEY",))
def send_pushme(cfg: dict[str, str], title: str, content: str) -> None:
    payload = {"push_key": cfg["PUSHME_KEY"], "title": title, "content": content}
    response = requests.post("https://push.i-i.me/", data=payload, timeout=REQUEST_TIMEOUT)
    if response.text != "success":
        raise NotifyError(response.text)


@channel(
    "Pushover",
    required=("PUSHOVER_APP_TOKEN", "PUSHOVER_USER_KEY"),
    optional=(
        "PUSHOVER_DEVICE",
        "PUSHOVER_PRIORITY",
        "PUSHOVER_SOUND",
        "PUSHOVER_URL",
        "PUSHOVER_URL_TITLE",
        "PUSHOVER_RETRY",
        "PUSHOVER_EXPIRE",
    ),
)
def send_pushover(cfg: dict[str, str], title: str, content: str) -> None:
    payload = {
        "token": cfg["PUSHOVER_APP_TOKEN"],
        "user": cfg["PUSHOVER_USER_KEY"],
        "title": title[:250],
        "message": content,
    }
    optional_fields = {
        "PUSHOVER_DEVICE": "device",
        "PUSHOVER_PRIORITY": "priority",
        "PUSHOVER_SOUND": "sound",
        "PUSHOVER_URL": "url",
        "PUSHOVER_URL_TITLE": "url_title",
        "PUSHOVER_RETRY": "retry",
        "PUSHOVER_EXPIRE": "expire",
    }
    for env_name, payload_name in optional_fields.items():
        if cfg.get(env_name):
            payload[payload_name] = cfg[env_name]

    result = _json_or_raise(
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data=payload,
            timeout=REQUEST_TIMEOUT,
        )
    )
    if result.get("status") != 1:
        errors = result.get("errors")
        if isinstance(errors, list):
            raise NotifyError("; ".join(str(item) for item in errors))
        raise NotifyError(result.get("message") or str(result))


@channel("Chronocat", required=("CHRONOCAT_URL", "CHRONOCAT_TARGET"), optional=("CHRONOCAT_TOKEN",))
def send_chronocat(cfg: dict[str, str], title: str, content: str) -> None:
    headers = {"Content-Type": "application/json"}
    if cfg.get("CHRONOCAT_TOKEN"):
        headers["Authorization"] = f"Bearer {cfg['CHRONOCAT_TOKEN']}"

    payload = {
        "peer": {"chatType": 1, "peerUin": cfg["CHRONOCAT_TARGET"]},
        "elements": [{"elementType": 1, "textElement": {"content": f"{title}\n\n{content}"}}],
    }
    response = requests.post(
        f"{cfg['CHRONOCAT_URL']}/api/message/send",
        json=payload,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise NotifyError(response.text)


@channel("ntfy", required=("NTFY_TOPIC",), optional=("NTFY_URL", "NTFY_TOKEN"))
def send_ntfy(cfg: dict[str, str], title: str, content: str) -> None:
    base_url = cfg.get("NTFY_URL", "https://ntfy.sh")
    headers = {"Title": title}
    if cfg.get("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {cfg['NTFY_TOKEN']}"

    response = requests.post(
        f"{base_url}/{cfg['NTFY_TOPIC']}",
        data=content.encode("utf-8"),
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise NotifyError(response.text)


@channel("Discord", required=("DISCORD_WEBHOOK",))
def send_discord(cfg: dict[str, str], title: str, content: str) -> None:
    response = requests.post(
        cfg["DISCORD_WEBHOOK"],
        json={"content": f"**{title}**\n\n{content}"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code not in (200, 204):
        raise NotifyError(response.text)


@channel("Slack", required=("SLACK_WEBHOOK",))
def send_slack(cfg: dict[str, str], title: str, content: str) -> None:
    response = requests.post(
        cfg["SLACK_WEBHOOK"],
        json={"text": f"*{title}*\n\n{content}"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise NotifyError(response.text)
    body = response.text.strip().lower()
    if body and body != "ok":
        raise NotifyError(response.text)


@channel("Microsoft Teams", required=("TEAMS_WEBHOOK",))
def send_teams(cfg: dict[str, str], title: str, content: str) -> None:
    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": title,
        "themeColor": "0078D4",
        "title": title,
        "text": content.replace("\n", "\n\n"),
    }
    response = requests.post(cfg["TEAMS_WEBHOOK"], json=payload, timeout=REQUEST_TIMEOUT)
    if response.status_code not in (200, 202):
        raise NotifyError(response.text)


@channel(
    "Matrix",
    required=("MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN", "MATRIX_ROOM_ID"),
    optional=("MATRIX_MSGTYPE",),
)
def send_matrix(cfg: dict[str, str], title: str, content: str) -> None:
    homeserver = cfg["MATRIX_HOMESERVER"].rstrip("/")
    room_id = quote(cfg["MATRIX_ROOM_ID"], safe="")
    txn_id = uuid4().hex
    msgtype = cfg.get("MATRIX_MSGTYPE", "m.text")
    payload = {"msgtype": msgtype, "body": f"{title}\n\n{content}"}
    response = requests.put(
        f"{homeserver}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn_id}",
        json=payload,
        headers={"Authorization": f"Bearer {cfg['MATRIX_ACCESS_TOKEN']}"},
        timeout=REQUEST_TIMEOUT,
    )
    result = _json_or_raise(response)
    if response.status_code != 200 or not result.get("event_id"):
        raise NotifyError(result.get("errcode") or result.get("error") or response.text)


@channel("息知", required=("XIZHI_TOKEN",), optional=("XIZHI_URL",))
def send_xizhi(cfg: dict[str, str], title: str, content: str) -> None:
    base_url = cfg.get("XIZHI_URL", "https://xizhi.qqoq.net").rstrip("/")
    response = requests.post(
        f"{base_url}/{cfg['XIZHI_TOKEN']}.send",
        data={"title": title, "content": content},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise NotifyError(response.text)
    try:
        result = response.json()
    except ValueError:
        return
    code = result.get("code")
    if code not in (0, 200, "0", "200", None):
        raise NotifyError(result.get("msg") or result.get("message") or str(result))


@channel(
    "Webhook",
    required=("WEBHOOK_URL",),
    optional=("WEBHOOK_METHOD", "WEBHOOK_HEADERS", "WEBHOOK_BODY_TEMPLATE"),
)
def send_webhook(cfg: dict[str, str], title: str, content: str) -> None:
    method = cfg.get("WEBHOOK_METHOD", "POST").upper()
    headers = json.loads(cfg["WEBHOOK_HEADERS"]) if cfg.get("WEBHOOK_HEADERS") else {}

    if cfg.get("WEBHOOK_BODY_TEMPLATE"):
        body = cfg["WEBHOOK_BODY_TEMPLATE"].replace("{{title}}", title).replace(
            "{{content}}", content
        )
        data = json.loads(body)
    else:
        data = {"title": title, "content": content}

    if method == "GET":
        response = requests.get(
            cfg["WEBHOOK_URL"], params=data, headers=headers, timeout=REQUEST_TIMEOUT
        )
    else:
        response = requests.post(
            cfg["WEBHOOK_URL"], json=data, headers=headers, timeout=REQUEST_TIMEOUT
        )

    if response.status_code not in (200, 201, 204):
        raise NotifyError(response.text)


# 调度入口


def get_status(balance: float) -> str:
    """返回电量状态文案。"""
    if balance > EXCELLENT_THRESHOLD:
        return "充足"
    elif balance > THRESHOLD:
        return "偏低"
    else:
        return "不足"


def format_balance_report(light_balance: float, ac_balance: float) -> str:
    """格式化电量报告。"""
    return (
        f"💡 照明剩余电量：{light_balance} 度（{get_status(light_balance)}）\n"
        f"❄️ 空调剩余电量：{ac_balance} 度（{get_status(ac_balance)}）\n\n"
    )


def is_low_energy(balances: dict[str, float]) -> bool:
    """判断是否触发低电量报警。"""
    return balances["light_Balance"] <= THRESHOLD or balances["ac_Balance"] <= THRESHOLD


def build_low_energy_state(balances: dict[str, float]) -> dict[str, bool]:
    """生成低电量去重状态。"""
    return {
        "light_low": balances["light_Balance"] <= THRESHOLD,
        "ac_low": balances["ac_Balance"] <= THRESHOLD,
    }


def should_send_low_energy_alert(balances: dict[str, float]) -> bool:
    """判断是否应发送本次低电量报警。"""
    if not get_settings().notify_dedup:
        return True

    current_state = build_low_energy_state(balances)
    previous_state = load_notify_state()
    previous_low_state = previous_state.get("low_energy")

    if previous_low_state == current_state:
        logger.info("低电量状态未变化，已按 NOTIFY_DEDUP 跳过重复报警")
        return False

    return True


def update_notify_state(balances: dict[str, float]) -> None:
    """按当前电量更新通知去重状态。"""
    if not get_settings().notify_dedup:
        return

    save_notify_state(
        {
            "low_energy": build_low_energy_state(balances),
            "updated_at": get_cst_time(),
        }
    )


def _dispatch_channels(channels: list[Channel], title: str, content: str) -> int:
    """逐渠道发送通知。"""
    sent_count = 0
    for ch in channels:
        try:
            if dispatch(ch, title, content):
                sent_count += 1
        except Exception as e:
            logger.error(f"{ch.name} 通知失败: {e}")
    return sent_count


def send_alert(title: str, content: str) -> int:
    """向所有已配置渠道发送报警通知。"""
    logger.info("发送报警通知到所有渠道...")
    return _dispatch_channels(list(CHANNELS.values()), title, content)


def send_daily(title: str, content: str) -> int:
    """向日常渠道（Telegram）发送通知。"""
    logger.info("发送日常通知...")
    return _dispatch_channels([ch for ch in CHANNELS.values() if ch.daily], title, content)


def notify(balances: dict[str, float]) -> None:
    """根据电量状态发送通知。"""
    low_energy = is_low_energy(balances)
    title = "⚠️宿舍电量预警⚠️" if low_energy else "🏠宿舍电量通报🏠"
    content = format_balance_report(balances["light_Balance"], balances["ac_Balance"])

    if low_energy:
        content += "⚠️ 电量不足，请尽快充电！"
        if should_send_low_energy_alert(balances):
            sent_count = send_alert(title, content)
            if sent_count:
                update_notify_state(balances)
            else:
                logger.warning("低电量报警未成功发送到任何渠道，保留旧去重状态")
        else:
            update_notify_state(balances)
    else:
        content += "当前电量充足，请保持关注。"
        send_daily(title, content)
        update_notify_state(balances)
