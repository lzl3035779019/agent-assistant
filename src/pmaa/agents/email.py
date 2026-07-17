import re


class EmailAgent:
    name = "email"

    def build_tool_request(self, user_input: str) -> dict:
        text = user_input.strip()
        normalized = text.lower()
        if any(marker in normalized for marker in ["回复", "回邮件", "reply"]):
            return {"action": "draft_reply", "query": text}
        if any(marker in normalized for marker in ["发送", "发邮件", "写邮件", "send email"]):
            return {
                "action": "prepare_send",
                "query": text,
                **_parse_send_fields(text),
            }
        unread_only = any(marker in normalized for marker in ["未读", "新邮件", "unread", "new mail"])
        return {
            "action": "list_recent",
            "query": text,
            "limit": 5,
            "unread_only": unread_only,
        }


def _parse_send_fields(text: str) -> dict[str, str]:
    to_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    subject_match = re.search(
        r"(?:主题|subject)[:：]\s*(.+?)(?=\s*(?:内容|正文|body)[:：]|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    body_match = re.search(
        r"(?:内容|正文|body)[:：]\s*(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return {
        "to": to_match.group(0) if to_match else "",
        "subject": subject_match.group(1).strip() if subject_match else "",
        "body": body_match.group(1).strip() if body_match else "",
    }
