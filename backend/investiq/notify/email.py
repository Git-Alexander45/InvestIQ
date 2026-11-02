"""Email delivery: SMTP, Resend, or a local outbox folder (default when nothing is configured).

Credentials come only from environment variables. Every attempt is recorded in email_deliveries.
External email services may cost money; see docs/DATA_SOURCES.md (external costs).
"""

from __future__ import annotations

import smtplib
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from investiq.config import Settings, get_settings
from investiq.models import EmailDelivery


class EmailError(RuntimeError):
    pass


@dataclass
class Outgoing:
    to: str
    subject: str
    html: str
    text: str


def _message(settings: Settings, mail: Outgoing) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.email_from or "InvestIQ <investiq@localhost>"
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg["Message-ID"] = make_msgid(domain="investiq.local")
    msg.set_content(mail.text)
    msg.add_alternative(mail.html, subtype="html")
    return msg


class SmtpSender:
    name = "smtp"

    def __init__(self, settings: Settings, smtp_factory=smtplib.SMTP) -> None:
        if not settings.smtp_host:
            raise EmailError("SMTP is not configured (INVESTIQ_SMTP_HOST)")
        self.s = settings
        self.factory = smtp_factory

    def send(self, mail: Outgoing) -> str:
        msg = _message(self.s, mail)
        with self.factory(self.s.smtp_host, self.s.smtp_port, timeout=30) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self.s.smtp_username:
                smtp.login(self.s.smtp_username, self.s.secret("smtp_password") or "")
            smtp.send_message(msg)
        return str(msg["Message-ID"])


class ResendSender:
    name = "resend"
    URL = "https://api.resend.com/emails"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        key = settings.secret("resend_api_key")
        if not key or not settings.email_from:
            raise EmailError("Resend needs INVESTIQ_RESEND_API_KEY and INVESTIQ_EMAIL_FROM (verified sender domain)")
        self.s = settings
        self.client = httpx.Client(timeout=30, transport=transport, headers={"Authorization": f"Bearer {key}"})

    def send(self, mail: Outgoing) -> str:
        resp = self.client.post(self.URL, json={"from": self.s.email_from, "to": [mail.to], "subject": mail.subject,
                                                "html": mail.html, "text": mail.text})
        if resp.status_code >= 400:
            raise EmailError(f"Resend HTTP {resp.status_code}: {resp.text[:200]}")
        return str(resp.json().get("id", ""))


class OutboxSender:
    """Writes .eml files locally. Used when no email provider is configured, so reports are never lost."""

    name = "outbox"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.dir = Path(settings.outbox_dir)

    def send(self, mail: Outgoing) -> str:
        self.dir.mkdir(parents=True, exist_ok=True)
        msg = _message(self.s, mail)
        name = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + ".eml"
        (self.dir / name).write_bytes(bytes(msg))
        return str(self.dir / name)


def sender_for(provider: str, settings: Settings | None = None):
    settings = settings or get_settings()
    if provider == "smtp":
        return SmtpSender(settings)
    if provider == "resend":
        return ResendSender(settings)
    return OutboxSender(settings)


def deliver(session: Session, *, kind: str, to: str | None, provider: str, subject: str, html: str, text: str,
            report_id: int | None = None, cycle_id: int | None = None, sender=None, attempts: int = 3,
            sleep=time.sleep) -> EmailDelivery:
    d = EmailDelivery(report_id=report_id, cycle_id=cycle_id, kind=kind, to_address=to or "(not configured)",
                      provider=provider, subject=subject[:255], status="pending")
    session.add(d)
    session.flush()
    if not to:
        d.status, d.error = "skipped", "no recipient address configured in Settings"
        return d
    try:
        sender = sender or sender_for(provider)
    except EmailError as exc:
        d.status, d.error = "failed", str(exc)
        return d
    for i in range(attempts):
        d.attempts = i + 1
        try:
            d.provider_message_id = sender.send(Outgoing(to, subject, html, text))[:255]
            d.status, d.sent_at, d.error = "sent", datetime.now(UTC), None
            return d
        except Exception as exc:  # network/auth errors are recorded, then retried
            d.error = f"{type(exc).__name__}: {exc}"[:2000]
            if i + 1 < attempts:
                sleep(2 ** i)
    d.status = "failed"
    return d
