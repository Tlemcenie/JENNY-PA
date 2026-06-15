"""Parsing brut IMAP → ``EmailPayload``."""

from __future__ import annotations

from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from typing import TYPE_CHECKING

from jenny.connectors.email.schema import EmailPayload

if TYPE_CHECKING:
    from email.message import Message


def _first_addr(addrs: list[tuple[str, str]]) -> tuple[str, str]:
    if not addrs:
        return ("", "")
    name, addr = addrs[0]
    return (name or "", addr or "")


def _extract_text(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and "attachment" not in (part.get("Content-Disposition") or ""):
                try:
                    return part.get_content()
                except Exception:
                    continue
        return ""
    if msg.get_content_type() == "text/plain":
        try:
            return msg.get_content()
        except Exception:
            return ""
    return ""


def parse_mime_to_email_payload(raw: bytes, fallback_to_email: str) -> EmailPayload | None:
    """Construit un ``EmailPayload`` depuis les octets MIME bruts."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    mid = msg.get("Message-ID") or f"<no-id-{hash(raw) & 0xFFFFFFFF:x}@imap.local>"
    from_list = getaddresses([msg.get("From") or ""])
    from_name, from_email = _first_addr(from_list)
    if not from_email:
        return None
    to_list = getaddresses([msg.get("To") or fallback_to_email])
    _, to_email = _first_addr(to_list)
    if not to_email:
        to_email = fallback_to_email
    text_body = _extract_text(msg).strip()
    if not text_body:
        return None
    subj = msg.get("Subject") or ""
    date_hdr = msg.get("Date")
    try:
        if date_hdr:
            sent = parsedate_to_datetime(date_hdr)
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=UTC)
        else:
            sent = datetime.now(UTC)
    except Exception:
        sent = datetime.now(UTC)
    return EmailPayload(
        message_id=mid.strip(),
        from_email=from_email,  # type: ignore[arg-type]
        from_name=from_name or None,
        to_email=to_email,  # type: ignore[arg-type]
        subject=subj or None,
        text_body=text_body,
        html_body=None,
        sent_at=sent,
        received_at=datetime.now(UTC),
        attachments=[],
        headers={k: v for k, v in msg.items()},
    )


def fetch_unseen_mails_sync(
    host: str,
    user: str,
    password: str,
    mailbox: str,
    use_ssl: bool,
) -> list[bytes]:
    """Lit les courriels non lus, les marque \\Seen (thread IMAP bloquant)."""
    import imaplib

    klass = imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4
    conn = klass(host)
    conn.login(user, password)
    conn.select(mailbox)
    typ, data = conn.search(None, "UNSEEN")
    out: list[bytes] = []
    if typ != "OK" or not data or not data[0]:
        conn.logout()
        return out
    for num in data[0].split():
        typ2, body = conn.fetch(num, "(RFC822)")
        if typ2 == "OK" and body and isinstance(body[0], tuple) and len(body[0]) >= 2:
            raw = body[0][1]
            if isinstance(raw, bytes):
                out.append(raw)
        conn.store(num, "+FLAGS", "\\Seen")
    conn.logout()
    return out
