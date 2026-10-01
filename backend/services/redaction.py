"""Keep API keys out of log lines and error messages.

FRED only accepts its key as a `?api_key=` query parameter, and httpx puts the
requested URL into its exception messages, so an `f"... {e}"` can write the key
into a log or send it to the browser. Every message built from a FRED response
or exception goes through `redact_secrets` first.
"""
import logging
import re
from typing import Optional

REDACTED = "***"

# A key travelling in a URL or a "key=value" fragment, whatever its shape (FRED's
# is 32 plain hex characters, with no prefix a pattern could recognise).
_KEY_PARAM = re.compile(r"(?i)\b(api[_-]?key)(=|%3D)[^&\s'\"<>)]+")
# Keys with a recognisable shape: Google (AIza...) and OpenAI (sk-...).
_KNOWN_SHAPES = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|sk-[A-Za-z0-9_\-]{20,}")


def redact_secrets(text: object, *keys: Optional[str]) -> str:
    """`text` as a string with each of `keys`, any `api_key=...` and any
    recognisable key shape replaced by `***`."""
    out = str(text)
    for key in keys:
        if key and key.strip():
            out = out.replace(key.strip(), REDACTED)
    out = _KEY_PARAM.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
    return _KNOWN_SHAPES.sub(REDACTED, out)


class RedactingFilter(logging.Filter):
    """Redacts the formatted message of every record that passes through it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


# httpx logs "HTTP Request: GET <full url>" at INFO for EVERY request, and FRED's
# URL carries the key — with a valid key too, not only a rejected one.
_NOISY_URL_LOGGERS = ("httpx", "httpcore")


def install_log_redaction() -> None:
    """Attach RedactingFilter to the loggers that print URLs and to every root
    handler, so nothing written by any library can carry a key."""
    for name in _NOISY_URL_LOGGERS:
        lg = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in lg.filters):
            lg.addFilter(RedactingFilter())
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
