import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import requests

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphError(RuntimeError):
    pass


@dataclass
class Message:
    id: str
    subject: str
    received_at: str


@dataclass
class Attachment:
    id: str
    name: str
    content_type: str


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _get(url: str, token: str, params: dict | None = None) -> dict:
    resp = requests.get(url, headers=_headers(token), params=params, timeout=30)
    if resp.status_code != 200:
        raise GraphError(f"GET {url} failed: {resp.status_code} {resp.text}")
    return resp.json()


def list_candidate_messages(
    token: str, mailbox_user: str, subject_keyword: str, since: datetime
) -> Iterable[Message]:
    """List recent messages with attachments, filtered client-side by subject.

    We filter on receivedDateTime + hasAttachments server-side (both are
    well-supported $filter fields) and match the subject keyword in Python,
    to avoid relying on Graph's string-search OData quirks per mailbox.
    """
    since_iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"{_GRAPH_BASE}/users/{mailbox_user}/mailFolders/Inbox/messages"
    params = {
        "$filter": f"receivedDateTime ge {since_iso} and hasAttachments eq true",
        "$select": "id,subject,receivedDateTime",
        "$orderby": "receivedDateTime asc",
        "$top": "50",
    }
    keyword = subject_keyword.lower()
    while url:
        data = _get(url, token, params)
        params = None  # nextLink already encodes query params
        for item in data.get("value", []):
            subject = item.get("subject") or ""
            if keyword in subject.lower():
                yield Message(
                    id=item["id"],
                    subject=subject,
                    received_at=item.get("receivedDateTime", ""),
                )
        url = data.get("@odata.nextLink")


def list_pdf_attachments(token: str, mailbox_user: str, message_id: str) -> list[Attachment]:
    url = f"{_GRAPH_BASE}/users/{mailbox_user}/messages/{message_id}/attachments"
    data = _get(url, token, {"$select": "id,name,contentType"})
    out = []
    for item in data.get("value", []):
        name = (item.get("name") or "").lower()
        content_type = item.get("contentType") or ""
        if name.endswith(".pdf") or content_type == "application/pdf":
            out.append(Attachment(id=item["id"], name=item.get("name", ""), content_type=content_type))
    return out


def download_attachment(token: str, mailbox_user: str, message_id: str, attachment_id: str) -> bytes:
    url = f"{_GRAPH_BASE}/users/{mailbox_user}/messages/{message_id}/attachments/{attachment_id}"
    data = _get(url, token, {"$select": "contentBytes"})
    content_bytes = data.get("contentBytes")
    if not content_bytes:
        raise GraphError(f"Attachment {attachment_id} on message {message_id} has no contentBytes")
    return base64.b64decode(content_bytes)


def mark_message_read(token: str, mailbox_user: str, message_id: str) -> None:
    url = f"{_GRAPH_BASE}/users/{mailbox_user}/messages/{message_id}"
    resp = requests.patch(url, headers=_headers(token), json={"isRead": True}, timeout=30)
    if resp.status_code not in (200, 204):
        logger.warning("Failed to mark message %s as read: %s %s", message_id, resp.status_code, resp.text)


def default_lookback(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)
