import logging

from shared.logging.redaction import RedactingFilter, redact


def test_redacts_credentials_and_tokens():
    text = ('POST /auth/token {"username": "HACK344", "password": "s3cret!"} '
            'Authorization: Bearer abc.def.ghi wss://h/market?token=eyJhbGciOi '
            '{"accessToken": "8f2ce91a77", "token": "eyJhbGciOiJIUzI1NiIs"}')
    out = redact(text)
    for secret in ("s3cret!", "abc.def.ghi", "eyJhbGciOi", "8f2ce91a77", "eyJhbGciOiJIUzI1NiIs"):
        assert secret not in out
    assert "HACK344" in out  # the UCC is an identifier, not a secret


def test_filter_rewrites_log_records():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "login with password=%s", ("hunter2",), None)
    assert RedactingFilter().filter(record)
    assert "hunter2" not in record.getMessage()
