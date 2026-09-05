#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

"""Send self-contained HTML Nagios notifications through an SMTP relay."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
import html
import os
import smtplib
import sys
from typing import Mapping


MAX_FIELD_LENGTH = 32_000
STATE_COLORS = {
    "UP": "#16803c", "OK": "#16803c", "RECOVERY": "#16803c",
    "WARNING": "#b77900", "UNKNOWN": "#6b7280",
    "DOWN": "#c62828", "CRITICAL": "#c62828",
}


@dataclass(frozen=True)
class Notification:
    kind: str
    notification_type: str
    host_name: str
    address: str
    state: str
    output: str
    long_output: str
    timestamp: str
    duration: str
    attempt: str
    max_attempts: str
    recipient: str
    service_name: str = ""
    author: str = ""
    comment: str = ""
    recipients: str = ""


@dataclass(frozen=True)
class MailSettings:
    smtp_host: str
    smtp_port: int
    smtp_timeout: int
    from_address: str
    from_name: str
    footer: str


def required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value:
        raise ValueError(f"required Nagios environment variable is missing: {name}")
    return value


def bounded(value: str) -> str:
    if len(value) <= MAX_FIELD_LENGTH:
        return value
    return value[: MAX_FIELD_LENGTH - 14] + "\n[truncated]"


def nagios_long_output(value: str) -> str:
    return bounded(value.replace(r"\n", "\n"))


def safe_header(value: str, field: str) -> str:
    if any(character in value for character in "\r\n"):
        raise ValueError(f"{field} contains a line break")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field} contains a control character")
    return value


def single_address(value: str, field: str) -> Address:
    safe_header(value, field)
    try:
        address = Address(addr_spec=value)
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not a valid single email address") from exc
    if not address.username or not address.domain:
        raise ValueError(f"{field} is not a valid single email address")
    return address


def positive_integer(environment: Mapping[str, str], name: str, default: str) -> int:
    value = environment.get(name, default)
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if number <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return number


def settings_from_environment(environment: Mapping[str, str]) -> MailSettings:
    return MailSettings(
        smtp_host=safe_header(environment.get("NAGIOS_SMTP_HOST", "127.0.0.1"), "SMTP host"),
        smtp_port=positive_integer(environment, "NAGIOS_SMTP_PORT", "25"),
        smtp_timeout=positive_integer(environment, "NAGIOS_SMTP_TIMEOUT", "10"),
        from_address=environment.get("NAGIOS_MAIL_FROM", "nagios@localhost"),
        from_name=safe_header(environment.get("NAGIOS_MAIL_FROM_NAME", "Nagios"), "sender name"),
        footer=bounded(environment.get("NAGIOS_MAIL_FOOTER", "Nagios monitoring notification")),
    )


def from_environment(kind: str, environment: Mapping[str, str]) -> Notification:
    if kind not in {"host", "service"}:
        raise ValueError(f"unknown notification kind: {kind}")
    service = kind == "service"
    prefix = "SERVICE" if service else "HOST"
    return Notification(
        kind=kind,
        notification_type=required(environment, "NAGIOS_NOTIFICATIONTYPE"),
        host_name=required(environment, "NAGIOS_HOSTNAME"),
        address=environment.get("NAGIOS_HOSTADDRESS", ""),
        state=required(environment, f"NAGIOS_{prefix}STATE"),
        output=bounded(environment.get(f"NAGIOS_{prefix}OUTPUT", "")),
        long_output=nagios_long_output(environment.get(f"NAGIOS_LONG{prefix}OUTPUT", "")),
        timestamp=environment.get("NAGIOS_LONGDATETIME", ""),
        duration=environment.get(f"NAGIOS_{prefix}DURATION", ""),
        attempt=environment.get(f"NAGIOS_{prefix}ATTEMPT", ""),
        max_attempts=environment.get(f"NAGIOS_MAX{prefix}ATTEMPTS", ""),
        recipient=required(environment, "NAGIOS_CONTACTEMAIL"),
        service_name=required(environment, "NAGIOS_SERVICEDESC") if service else "",
        author=environment.get("NAGIOS_NOTIFICATIONAUTHORNAME", "") or environment.get("NAGIOS_NOTIFICATIONAUTHOR", ""),
        comment=bounded(environment.get("NAGIOS_NOTIFICATIONCOMMENT", "")),
        recipients=environment.get("NAGIOS_NOTIFICATIONRECIPIENTS", ""),
    )


def subject(notification: Notification) -> str:
    if notification.service_name:
        value = f"[Nagios] {notification.notification_type}: {notification.service_name} on {notification.host_name} is {notification.state}"
    else:
        value = f"[Nagios] {notification.notification_type}: {notification.host_name} is {notification.state}"
    return safe_header(value, "subject")


def plain_body(notification: Notification, footer: str) -> str:
    lines = ["Nagios alert notification", "", f"Notification type: {notification.notification_type}", f"Host: {notification.host_name}"]
    if notification.service_name:
        lines.append(f"Service: {notification.service_name}")
    lines.extend([
        f"State: {notification.state}", f"Address: {notification.address}",
        f"Date/time: {notification.timestamp}", f"Duration: {notification.duration}",
        f"Attempt: {notification.attempt}/{notification.max_attempts}", "",
        "Status information:", notification.output,
    ])
    if notification.long_output:
        lines.extend(["", notification.long_output])
    if notification.author or notification.comment:
        lines.extend(["", f"Author: {notification.author}", f"Comment: {notification.comment}"])
    if notification.recipients:
        lines.extend(["", f"Notified recipients: {notification.recipients}"])
    lines.extend(["", footer])
    return "\n".join(lines).rstrip() + "\n"


def html_body(notification: Notification, footer: str) -> str:
    escaped = {field: html.escape(str(value), quote=True) for field, value in notification.__dict__.items()}
    safe_footer = html.escape(footer, quote=True)
    color = STATE_COLORS.get(notification.state.upper(), "#44546a")
    service_row = f'<tr><th>Service</th><td>{escaped["service_name"]}</td></tr>' if notification.service_name else ""
    recipients_row = f'<tr><th>Notified recipients</th><td>{escaped["recipients"]}</td></tr>' if notification.recipients else ""
    comment = ""
    if notification.author or notification.comment:
        comment = f'<section><h2>Notification comment</h2><div class="output"><strong>{escaped["author"]}</strong>\n{escaped["comment"]}</div></section>'
    separator = "\n\n" if notification.long_output else ""
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{escaped["host_name"]}</title><style>
body{{margin:0;padding:24px 12px;background:#f3f4f6;color:#17202a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}}
.card{{max-width:640px;margin:auto;background:#fff;border:1px solid #d9dee5;border-radius:18px;overflow:hidden}}
header,.footer{{padding:14px 22px;background:#293241;color:#fff;text-align:center}} header h1{{margin:0;font-size:18px}}
.state{{padding:20px 22px;background:{color};color:#fff;text-align:center}} .state p{{margin:0 0 4px}} .state h2{{margin:0;font-size:30px}}
main{{padding:20px 22px 26px}} table{{width:100%;border-collapse:collapse}} th,td{{padding:8px 0;border-bottom:1px solid #edf0f4;text-align:left;vertical-align:top}} th{{width:36%;color:#667085}}
section{{margin-top:22px}} section h2{{font-size:15px;color:#667085}} .output{{padding:14px;border-radius:10px;background:#f7f8fa;white-space:pre-wrap;overflow-wrap:anywhere;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}}
</style></head><body><div class="card"><header><h1>Nagios alert notification</h1></header>
<div class="state"><p>{escaped["notification_type"]}</p><h2>{escaped["state"]}</h2></div><main>
<table role="presentation"><tr><th>Host</th><td>{escaped["host_name"]}</td></tr>{service_row}
<tr><th>Address</th><td>{escaped["address"]}</td></tr><tr><th>Date/time</th><td>{escaped["timestamp"]}</td></tr>
<tr><th>Duration</th><td>{escaped["duration"]}</td></tr><tr><th>Attempt</th><td>{escaped["attempt"]}/{escaped["max_attempts"]}</td></tr>{recipients_row}</table>
<section><h2>Status information</h2><div class="output">{escaped["output"]}{separator}{escaped["long_output"]}</div></section>{comment}</main>
<div class="footer">{safe_footer}</div></div></body></html>'''


def build_message(notification: Notification, settings: MailSettings) -> EmailMessage:
    message = EmailMessage()
    message["From"] = Address(display_name=settings.from_name, addr_spec=str(single_address(settings.from_address, "sender")))
    message["To"] = single_address(notification.recipient, "recipient")
    message["Subject"] = subject(notification)
    message.set_content(plain_body(notification, settings.footer))
    message.add_alternative(html_body(notification, settings.footer), subtype="html")
    return message


def send_message(message: EmailMessage, settings: MailSettings) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout) as smtp:
        smtp.send_message(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--nagios-host", action="store_true")
    mode.add_argument("--nagios-service", action="store_true")
    args = parser.parse_args()
    try:
        settings = settings_from_environment(os.environ)
        notification = from_environment("host" if args.nagios_host else "service", os.environ)
        send_message(build_message(notification, settings), settings)
    except ValueError as exc:
        print(f"HTML email notification configuration error: {exc}", file=sys.stderr)
        return 2
    except (OSError, smtplib.SMTPException) as exc:
        print(f"HTML email notification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

