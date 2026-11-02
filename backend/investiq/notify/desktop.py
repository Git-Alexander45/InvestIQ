"""Native Windows toast notifications via PowerShell (no extra dependencies).

The title/body are passed base64-encoded in an environment variable and XML-escaped inside the
script, so notification text can never be interpreted as a command.
"""

from __future__ import annotations

import base64
import json
import os
import platform
import subprocess
from dataclasses import dataclass

APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$p = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:INVESTIQ_TOAST)) | ConvertFrom-Json
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [Security.SecurityElement]::Escape($p.title)
$b = [Security.SecurityElement]::Escape($p.body)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>InvestIQ: $t</text><text>$b</text></binding></visual></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($p.app_id).Show($toast)
"""


@dataclass
class DesktopResult:
    delivered: bool
    detail: str


def build_command(title: str, body: str) -> tuple[list[str], dict[str, str]]:
    payload = json.dumps({"title": title[:120], "body": body[:400], "app_id": APP_ID})
    env = {**os.environ, "INVESTIQ_TOAST": base64.b64encode(payload.encode("utf-8")).decode("ascii")}
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", SCRIPT]
    return cmd, env


def send(title: str, body: str, *, runner=subprocess.run, system: str | None = None) -> DesktopResult:
    if (system or platform.system()) != "Windows":
        return DesktopResult(False, "desktop notifications are only available on Windows")
    cmd, env = build_command(title, body)
    try:
        proc = runner(cmd, env=env, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DesktopResult(False, f"toast failed: {exc}")
    if proc.returncode != 0:
        return DesktopResult(False, f"toast failed: {(proc.stderr or '')[:200]}")
    return DesktopResult(True, "shown")
