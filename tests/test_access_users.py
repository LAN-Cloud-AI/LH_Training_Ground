from csl_lab.webapp.access_users import (
    _emails_to_include,
    _extract_emails,
    normalize_email,
)


def test_normalize_email():
    assert normalize_email("  Foo@Example.COM ") == "foo@example.com"


def test_normalize_email_rejects_invalid():
    try:
        normalize_email("not-an-email")
        assert False
    except ValueError:
        pass


def test_extract_and_roundtrip_include():
    include = [
        {"email": {"email": "a@x.com"}},
        {"email": {"email": "b@y.com"}},
        {"email": {"email": "a@x.com"}},
    ]
    emails = _extract_emails(include)
    assert emails == ["a@x.com", "b@y.com"]
    assert _emails_to_include(emails) == [
        {"email": {"email": "a@x.com"}},
        {"email": {"email": "b@y.com"}},
    ]
