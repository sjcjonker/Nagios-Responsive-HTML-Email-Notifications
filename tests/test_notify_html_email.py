from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("notify_html_email", ROOT / "notify-html-email.py")
assert SPEC and SPEC.loader
mail = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mail
SPEC.loader.exec_module(mail)


def environment() -> dict[str, str]:
    return {
        "NAGIOS_NOTIFICATIONTYPE": "PROBLEM", "NAGIOS_HOSTNAME": "web1",
        "NAGIOS_HOSTADDRESS": "192.0.2.10", "NAGIOS_SERVICEDESC": "HTTPS",
        "NAGIOS_SERVICESTATE": "WARNING", "NAGIOS_SERVICEOUTPUT": "<script>alert(1)</script>",
        "NAGIOS_LONGSERVICEOUTPUT": r"line one\nline two", "NAGIOS_LONGDATETIME": "now",
        "NAGIOS_SERVICEDURATION": "1m", "NAGIOS_SERVICEATTEMPT": "1",
        "NAGIOS_MAXSERVICEATTEMPTS": "3", "NAGIOS_CONTACTEMAIL": "operator@example.org",
    }


class EmailTests(unittest.TestCase):
    def test_multipart_escape_and_long_output(self) -> None:
        settings = mail.settings_from_environment({})
        notification = mail.from_environment("service", environment())
        message = mail.build_message(notification, settings)
        plain = message.get_body(preferencelist=("plain",)).get_content()
        rendered = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("line one\nline two", plain)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("http://", rendered)
        self.assertNotIn("https://", rendered)

    def test_rejects_header_injection_and_multiple_recipients(self) -> None:
        settings = mail.settings_from_environment({})
        for bad in ("good@example.org\nBcc: bad@example.org", "one@example.org, two@example.org"):
            values = environment(); values["NAGIOS_CONTACTEMAIL"] = bad
            with self.assertRaises(ValueError):
                mail.build_message(mail.from_environment("service", values), settings)

    def test_configures_relay_sender_and_footer(self) -> None:
        settings = mail.settings_from_environment({
            "NAGIOS_SMTP_HOST": "mail.example.org", "NAGIOS_SMTP_PORT": "2525",
            "NAGIOS_SMTP_TIMEOUT": "4", "NAGIOS_MAIL_FROM": "nagios@example.org",
            "NAGIOS_MAIL_FROM_NAME": "Monitoring", "NAGIOS_MAIL_FOOTER": "From monitoring",
        })
        message = mail.build_message(mail.from_environment("service", environment()), settings)
        smtp = mock.MagicMock()
        with mock.patch.object(mail.smtplib, "SMTP", smtp):
            mail.send_message(message, settings)
        smtp.assert_called_once_with("mail.example.org", 2525, timeout=4)
        self.assertIn("From monitoring", message.get_body(preferencelist=("html",)).get_content())


if __name__ == "__main__":
    unittest.main()

