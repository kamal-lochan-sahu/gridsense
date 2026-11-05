import logging

from core.log_redaction import RedactSecrets

URL = "/api?securityToken=abc-123-secret&documentType=A65&periodStart=202611032300"


def make_record(message, args=()):
    return logging.LogRecord("urllib3.connectionpool", logging.WARNING, __file__, 1, message, args, None)


def test_token_is_masked_in_messages_and_arguments():
    for record in (make_record(f"Retrying after error: {URL}"), make_record("Retrying: %s", (URL,))):
        assert RedactSecrets().filter(record) is True
        text = record.getMessage()
        assert "abc-123-secret" not in text
        assert "securityToken=***&documentType=A65" in text


def test_messages_without_a_token_are_untouched():
    record = make_record("Open-Meteo request failed for %s", ("Berlin",))
    RedactSecrets().filter(record)
    assert record.getMessage() == "Open-Meteo request failed for Berlin"
