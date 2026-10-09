"""
Log redaction: strips bearer tokens, passwords, access tokens and `token=` query values from
every log line before it is emitted, so 021 credentials and socket keys never reach the logs.
"""
import logging
import re

_PATTERNS = [
    # Authorization: Bearer <token>
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    # "password": "...", password=..., 'accessToken': '...', access_token=...
    (
        re.compile(r"(?i)([\"']?(?:password|accesstoken|access_token|api_key|apikey|secret)[\"']?\s*[:=]\s*[\"']?)[^\"'&\s,}]+"),
        r"\1[REDACTED]",
    ),
    # ?token=<ephemeral key> in websocket URLs, "token": "<jwt>" in JSON bodies
    (re.compile(r"(?i)(token=)[^&\s\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)([\"']token[\"']\s*:\s*[\"'])[^\"']{12,}"), r"\1[REDACTED]"),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        return True
