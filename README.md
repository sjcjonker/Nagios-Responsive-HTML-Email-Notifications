# Nagios Responsive HTML Email Notifications

A dependency-free Python 3 implementation of responsive HTML email
notifications for Nagios Core. It sends a multipart message containing both a
plain-text and a self-contained HTML version through an SMTP relay.

This project is inspired by Heini Holm Andersen's
[`heiniha/Nagios-Responsive-HTML-Email-Notifications`](https://github.com/heiniha/Nagios-Responsive-HTML-Email-Notifications).
The original project and author deserve the credit for the responsive Nagios
email concept. This repository contains a new Python implementation and does
not redistribute the original PHP files because the upstream repository does
not currently contain an explicit software license.

## Security properties

- HTML-escapes all Nagios-controlled fields.
- Rejects email header injection and multiple-recipient input.
- Limits untrusted field sizes.
- Converts Nagios' literal `\\n` long-output separators to real line breaks.
- Does not load remote images, fonts, JavaScript or stylesheets.
- Passes notification data through environment variables instead of shell
  command arguments.

## Installation

Install `notify-html-email.py` as an executable Nagios plugin. The default SMTP
relay is `127.0.0.1:25`. Set these environment variables in the Nagios service
environment when different values are required:

| Variable | Default |
| --- | --- |
| `NAGIOS_MAIL_FROM` | `nagios@localhost` |
| `NAGIOS_MAIL_FROM_NAME` | `Nagios` |
| `NAGIOS_MAIL_FOOTER` | `Nagios monitoring notification` |
| `NAGIOS_SMTP_HOST` | `127.0.0.1` |
| `NAGIOS_SMTP_PORT` | `25` |
| `NAGIOS_SMTP_TIMEOUT` | `10` |

Enable `enable_environment_macros=1` in `nagios.cfg` and use the definitions in
`examples/commands.cfg`.

## Test

```console
python3 -m unittest discover -s tests -v
python3 -m py_compile notify-html-email.py
```

The test suite does not send email.

## Upstream relationship and license

See `UPSTREAM.md` for the provenance and intended upstream contact. The new
Python implementation is licensed under GPL-3.0-or-later; see `LICENSE`.

