import base64
import email
import json

import httpx

from investiq.config import get_settings
from investiq.models import Notification
from investiq.notify import desktop
from investiq.notify import email as email_mod
from investiq.notify.service import mark_read, notify
from investiq.services.bootstrap import bootstrap
from investiq.services.preferences import set_pref


def test_outbox_delivery_writes_multipart_eml(session, tmp_path):
    d = email_mod.deliver(session, kind="daily_report", to="owner@example.com", provider="outbox", subject="Hello",
                          html="<p>Hi</p>", text="Hi")
    assert d.status == "sent" and d.attempts == 1
    msg = email.message_from_bytes(open(d.provider_message_id, "rb").read())
    assert msg["To"] == "owner@example.com"
    assert {p.get_content_type() for p in msg.walk()} >= {"text/plain", "text/html"}


def test_missing_recipient_is_skipped_not_silently_lost(session):
    d = email_mod.deliver(session, kind="daily_report", to=None, provider="outbox", subject="x", html="", text="")
    assert d.status == "skipped" and "recipient" in d.error


def test_unconfigured_provider_fails_with_reason(session):
    d = email_mod.deliver(session, kind="daily_report", to="a@example.com", provider="smtp", subject="x", html="",
                          text="")
    assert d.status == "failed" and "SMTP is not configured" in d.error


def test_retries_then_records_failure(session):
    class Flaky:
        calls = 0

        def send(self, mail):
            Flaky.calls += 1
            raise ConnectionError("network down")

    d = email_mod.deliver(session, kind="daily_report", to="a@example.com", provider="smtp", subject="x", html="",
                          text="", sender=Flaky(), sleep=lambda s: None)
    assert d.status == "failed" and d.attempts == 3 and Flaky.calls == 3 and "network down" in d.error


def test_smtp_sender_uses_starttls_and_login(monkeypatch):
    monkeypatch.setenv("INVESTIQ_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("INVESTIQ_SMTP_USERNAME", "me")
    monkeypatch.setenv("INVESTIQ_SMTP_PASSWORD", "app-password")
    from investiq.config import reset_settings_cache

    reset_settings_cache()
    log = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            log.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context):
            log.append(("starttls",))

        def login(self, user, pw):
            log.append(("login", user, pw))

        def send_message(self, msg):
            log.append(("send", msg["To"]))

    sender = email_mod.SmtpSender(get_settings(), smtp_factory=FakeSMTP)
    sender.send(email_mod.Outgoing("a@example.com", "s", "<p>h</p>", "t"))
    assert [e[0] for e in log] == ["connect", "starttls", "login", "send"]
    assert log[2] == ("login", "me", "app-password")
    reset_settings_cache()


def test_resend_sender_posts_json(monkeypatch):
    monkeypatch.setenv("INVESTIQ_RESEND_API_KEY", "re_test")
    monkeypatch.setenv("INVESTIQ_EMAIL_FROM", "InvestIQ <reports@example.com>")
    from investiq.config import reset_settings_cache

    reset_settings_cache()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "email_123"})

    sender = email_mod.ResendSender(get_settings(), transport=httpx.MockTransport(handler))
    assert sender.send(email_mod.Outgoing("a@example.com", "s", "<p>h</p>", "t")) == "email_123"
    assert seen["auth"] == "Bearer re_test" and seen["body"]["to"] == ["a@example.com"]
    reset_settings_cache()


def test_toast_payload_is_encoded_not_interpolated():
    title = "'; Remove-Item C:\\ -Recurse; '"
    cmd, env = desktop.build_command(title, "<b>body</b>")
    assert title not in " ".join(cmd)  # text never becomes part of the command line
    payload = json.loads(base64.b64decode(env["INVESTIQ_TOAST"]))
    assert payload["title"] == title and payload["body"] == "<b>body</b>"
    assert "SecurityElement]::Escape" in cmd[-1]


def test_toast_only_on_windows_and_reports_failures():
    assert desktop.send("t", "b", system="Linux").delivered is False

    class Proc:
        returncode = 1
        stderr = "boom"

    res = desktop.send("t", "b", system="Windows", runner=lambda *a, **k: Proc())
    assert res.delivered is False and "boom" in res.detail


def test_notification_centre_preferences_and_dedupe(session):
    bootstrap(session)
    shown = []

    def sender(title, body):
        shown.append(title)
        return desktop.DesktopResult(True, "shown")

    n = notify(session, "grade_change", "RY upgraded", "B+ to A-", dedupe_key="g:1", desktop_sender=sender)
    assert n.deliveries["desktop"] == "shown"
    assert notify(session, "grade_change", "RY upgraded", "again", dedupe_key="g:1", desktop_sender=sender) is None
    set_pref(session, "notifications", {"kinds": {"grade_change": False}}, actor="test")
    n2 = notify(session, "grade_change", "TD downgraded", "x", desktop_sender=sender)
    assert n2.deliveries["desktop"] == "disabled in preferences" and len(shown) == 1
    assert mark_read(session, [n.id, n2.id]) == 2
    assert session.query(Notification).filter(Notification.read_at.is_(None)).count() == 0
