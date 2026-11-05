"""Keep secrets out of the logs.

urllib3 logs the full request URL when it retries, and the ENTSO-E URL carries the security
token as a query parameter, so every log record is scrubbed before it is written.
"""
import logging
import re

_TOKEN = re.compile(r"(securityToken=)[^&\s'\")]+", re.IGNORECASE)


class RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = _TOKEN.sub(r"\1***", message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


def install(logger: logging.Logger | None = None) -> None:
    """Attach the filter to every handler of ``logger`` (default: the root logger)."""
    for handler in (logger or logging.getLogger()).handlers:
        if not any(isinstance(f, RedactSecrets) for f in handler.filters):
            handler.addFilter(RedactSecrets())
