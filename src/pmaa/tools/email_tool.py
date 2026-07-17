import imaplib
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid, parseaddr
from html import unescape
from typing import Any

from pmaa.config import load_settings


class EmailConfigurationError(RuntimeError):
    pass


@dataclass
class EmailSummary:
    message_id: str
    from_addr: str
    subject: str
    date: str
    snippet: str
    unread: bool = False
    body: str = ""


class QQEmailBackend:
    def __init__(
        self,
        address: str | None = None,
        auth_code: str | None = None,
        imap_host: str | None = None,
        imap_port: int | None = None,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
    ) -> None:
        current_settings = load_settings()
        self.address = address or current_settings.qq_email_address
        self.auth_code = auth_code or current_settings.qq_email_auth_code
        self.imap_host = imap_host or current_settings.qq_email_imap_host
        self.imap_port = imap_port or current_settings.qq_email_imap_port
        self.smtp_host = smtp_host or current_settings.qq_email_smtp_host
        self.smtp_port = smtp_port or current_settings.qq_email_smtp_port

    def _ensure_configured(self) -> None:
        if not self.address or not self.auth_code:
            raise EmailConfigurationError(
                "QQ_EMAIL_ADDRESS and QQ_EMAIL_AUTH_CODE are required."
            )

    def list_recent(self, limit: int = 5, unread_only: bool = False) -> list[EmailSummary]:
        self._ensure_configured()
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as client:
            client.login(self.address, self.auth_code)
            client.select("INBOX", readonly=True)
            criteria = "UNSEEN" if unread_only else "ALL"
            status, data = client.search(None, criteria)
            if status != "OK" or not data:
                return []
            ids = data[0].split()[-limit:]
            summaries: list[EmailSummary] = []
            for msg_id in reversed(ids):
                status, fetch_data = client.fetch(msg_id, "(BODY.PEEK[] FLAGS)")
                if status != "OK" or not fetch_data:
                    continue
                raw_message = _first_bytes_payload(fetch_data)
                if raw_message is None:
                    continue
                flags_text = " ".join(
                    item.decode("utf-8", errors="ignore")
                    for item in fetch_data
                    if isinstance(item, bytes)
                )
                message = BytesParser(policy=policy.default).parsebytes(raw_message)
                summaries.append(
                    EmailSummary(
                        message_id=msg_id.decode("ascii", errors="ignore"),
                        from_addr=str(message.get("From", "")),
                        subject=_decode_header_value(str(message.get("Subject", ""))),
                        date=str(message.get("Date", "")),
                        snippet=_extract_text_snippet(message),
                        unread="\\Seen" not in flags_text,
                    )
                )
            return summaries

    def count_unread(self) -> int:
        self._ensure_configured()
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as client:
            client.login(self.address, self.auth_code)
            client.select("INBOX", readonly=True)
            status, data = client.search(None, "UNSEEN")
            if status != "OK" or not data:
                return 0
            return len(data[0].split())

    def count_today_unread(self) -> int:
        self._ensure_configured()
        since = datetime.now().strftime("%d-%b-%Y")
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as client:
            client.login(self.address, self.auth_code)
            client.select("INBOX", readonly=True)
            status, data = client.search(None, "UNSEEN", "SINCE", since)
            if status != "OK" or not data:
                return 0
            return len(data[0].split())

    def get_message(self, message_id: str, mark_read: bool = False) -> EmailSummary | None:
        self._ensure_configured()
        if not message_id:
            return None
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as client:
            client.login(self.address, self.auth_code)
            client.select("INBOX", readonly=not mark_read)
            status, fetch_data = client.fetch(message_id.encode("ascii"), "(BODY.PEEK[] FLAGS)")
            if status != "OK" or not fetch_data:
                return None
            raw_message = _first_bytes_payload(fetch_data)
            if raw_message is None:
                return None
            flags_text = " ".join(
                item.decode("utf-8", errors="ignore")
                for item in fetch_data
                if isinstance(item, bytes)
            )
            message = BytesParser(policy=policy.default).parsebytes(raw_message)
            body = _message_text(message).strip()
            if mark_read and "\\Seen" not in flags_text:
                client.store(message_id.encode("ascii"), "+FLAGS", "\\Seen")
            return EmailSummary(
                message_id=message_id,
                from_addr=str(message.get("From", "")),
                subject=_decode_header_value(str(message.get("Subject", ""))),
                date=str(message.get("Date", "")),
                snippet=_extract_text_snippet(message),
                unread=False if mark_read else "\\Seen" not in flags_text,
                body=body,
            )

    def send(self, to: str, subject: str, body: str) -> str:
        self._ensure_configured()
        if not parseaddr(to)[1]:
            raise ValueError("Recipient email address is invalid.")
        message = EmailMessage()
        message["From"] = self.address
        message["To"] = to
        message["Subject"] = subject or "无主题"
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid()
        message.set_content(body)
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as client:
            client.login(self.address, self.auth_code)
            client.send_message(message)
        return str(message["Message-ID"])


class EmailTool:
    def __init__(self, backend: QQEmailBackend | None = None) -> None:
        self._backend = backend or QQEmailBackend()

    def __call__(self, request: dict[str, Any] | str) -> dict[str, Any]:
        payload = _coerce_request(request)
        action = str(payload.get("action", "list_recent"))
        if action == "list_recent":
            return self._list_recent(payload)
        if action == "count_unread":
            return self._count_unread()
        if action == "count_today_unread":
            return self._count_today_unread()
        if action == "get_message":
            return self._get_message(payload)
        if action == "draft_reply":
            return self._draft_reply(payload)
        if action == "prepare_send":
            return self._prepare_send(payload)
        return {
            "tool_name": "email",
            "status": "unsupported",
            "answer": f"暂不支持的邮件动作：{action}",
        }

    def _list_recent(self, payload: dict[str, Any]) -> dict[str, Any]:
        limit = int(payload.get("limit") or 5)
        unread_only = bool(payload.get("unread_only") or False)
        try:
            messages = self._backend.list_recent(limit=limit, unread_only=unread_only)
        except EmailConfigurationError as exc:
            return _configuration_error(str(exc))
        if not messages:
            scope = "未读邮件" if unread_only else "最近邮件"
            return {
                "tool_name": "email",
                "action": "list_recent",
                "status": "completed",
                "answer": f"没有读取到{scope}。",
                "messages": [],
            }
        return {
            "tool_name": "email",
            "action": "list_recent",
            "status": "completed",
            "answer": _format_recent_messages(messages),
            "messages": [message.__dict__ for message in messages],
        }

    def _count_unread(self) -> dict[str, Any]:
        try:
            count = self._backend.count_unread()
        except EmailConfigurationError as exc:
            return _configuration_error(str(exc))
        return {
            "tool_name": "email",
            "action": "count_unread",
            "status": "completed",
            "unread_count": count,
            "answer": f"当前有 {count} 封未读邮件。",
        }

    def _count_today_unread(self) -> dict[str, Any]:
        try:
            if hasattr(self._backend, "count_today_unread"):
                count = self._backend.count_today_unread()
            else:
                count = self._backend.count_unread()
        except EmailConfigurationError as exc:
            return _configuration_error(str(exc))
        return {
            "tool_name": "email",
            "action": "count_today_unread",
            "status": "completed",
            "unread_count": count,
            "answer": f"今天有 {count} 封未读邮件。",
        }

    def _get_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        message_id = str(payload.get("message_id", "")).strip()
        mark_read = bool(payload.get("mark_read") or False)
        if not message_id:
            return {
                "tool_name": "email",
                "action": "get_message",
                "status": "completed",
                "answer": "请先选择一封邮件。",
            }
        try:
            try:
                message = self._backend.get_message(message_id, mark_read=mark_read)
            except TypeError:
                message = self._backend.get_message(message_id)
        except EmailConfigurationError as exc:
            return _configuration_error(str(exc))
        if message is None:
            return {
                "tool_name": "email",
                "action": "get_message",
                "status": "completed",
                "answer": "没有找到这封邮件，可能邮件序号已经变化，请重新读取收件箱。",
            }
        return {
            "tool_name": "email",
            "action": "get_message",
            "status": "completed",
            "answer": message.body or message.snippet,
            "message": message.__dict__,
        }

    def _draft_reply(self, payload: dict[str, Any]) -> dict[str, Any]:
        message_id = str(payload.get("message_id", "")).strip()
        try:
            message = (
                self._backend.get_message(message_id)
                if message_id
                else (self._backend.list_recent(limit=1, unread_only=False) or [None])[0]
            )
        except EmailConfigurationError as exc:
            return _configuration_error(str(exc))
        if message is None:
            return {
                "tool_name": "email",
                "action": "draft_reply",
                "status": "completed",
                "answer": "没有找到可用于回复的邮件，请先读取收件箱并选择一封邮件。",
            }
        reply_body = (
            f"您好，\n\n"
            f"我已经收到您的邮件。关于“{message.subject or '这封邮件'}”，"
            "我会尽快确认后回复您更完整的信息。\n\n"
            "谢谢。"
        )
        return {
            "tool_name": "email",
            "action": "draft_reply",
            "status": "completed",
            "answer": (
                "已根据最近一封邮件生成回复草稿，尚未发送。\n\n"
                f"收件人：{message.from_addr}\n\n"
                f"主题：Re: {message.subject}\n\n"
                f"正文：\n{reply_body}"
            ),
            "draft": {
                "to": parseaddr(message.from_addr)[1] or message.from_addr,
                "subject": f"Re: {message.subject}",
                "body": reply_body,
                "source_message_id": message.message_id,
            },
        }

    def _prepare_send(self, payload: dict[str, Any]) -> dict[str, Any]:
        to = str(payload.get("to", "")).strip()
        subject = str(payload.get("subject", "")).strip() or "无主题"
        body = str(payload.get("body", "")).strip()
        if not to or not parseaddr(to)[1]:
            return {
                "tool_name": "email",
                "action": "prepare_send",
                "status": "completed",
                "answer": "请补充有效收件人邮箱地址后，我再帮你生成待发送邮件。",
            }
        if not body:
            return {
                "tool_name": "email",
                "action": "prepare_send",
                "status": "completed",
                "answer": "请补充邮件正文后，我再帮你生成待发送邮件。",
            }
        return {
            "success": False,
            "tool_name": "email",
            "status": "confirmation_required",
            "action": "email.send",
            "permission_level": "dangerous",
            "requires_confirmation": True,
            "dry_run": True,
            "plan": {
                "operation": "send_email",
                "to": to,
                "subject": subject,
                "body": body,
            },
            "rollback": {
                "status": "not_possible",
                "reason": "Email delivery cannot be reliably rolled back after SMTP send.",
            },
        }


def send_email_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    to = str(plan.get("to", "")).strip()
    subject = str(plan.get("subject", "")).strip()
    body = str(plan.get("body", "")).strip()
    try:
        message_id = QQEmailBackend().send(to=to, subject=subject, body=body)
    except Exception as exc:
        return {
            "status": "failed",
            "reason": str(exc),
        }
    return {
        "status": "executed",
        "message_id": message_id,
        "to": to,
        "subject": subject,
    }


def _coerce_request(request: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(request, dict):
        return request
    return {"action": "list_recent", "query": str(request)}


def _configuration_error(message: str) -> dict[str, Any]:
    return {
        "tool_name": "email",
        "status": "configuration_error",
        "answer": f"邮箱工具尚未配置完整：{message}",
    }


def _format_recent_messages(messages: list[EmailSummary]) -> str:
    lines = ["## 最近邮件"]
    for index, message in enumerate(messages, start=1):
        unread = "未读" if message.unread else "已读"
        lines.extend(
            [
                "",
                f"{index}. **{message.subject or '无主题'}**",
                f"   - 状态：{unread}",
                f"   - 发件人：{message.from_addr}",
                f"   - 时间：{message.date}",
                f"   - 摘要：{message.snippet}",
            ]
        )
    return "\n".join(lines)


def _decode_header_value(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _first_bytes_payload(fetch_data: list[Any]) -> bytes | None:
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _extract_text_snippet(message: EmailMessage, max_chars: int = 240) -> str:
    text = _message_text(message).strip()
    text = " ".join(text.split())
    return text[:max_chars]


def _message_text(message: EmailMessage) -> str:
    if message.is_multipart():
        html_body = ""
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return str(part.get_content())
                except Exception:
                    continue
            if part.get_content_type() == "text/html" and not html_body:
                try:
                    html_body = str(part.get_content())
                except Exception:
                    continue
        return _html_to_text(html_body) if html_body else ""
    try:
        content = str(message.get_content())
    except Exception:
        return ""
    if message.get_content_type() == "text/html":
        return _html_to_text(content)
    return content


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())
