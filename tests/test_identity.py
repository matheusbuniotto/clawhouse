"""Signed-in Databricks identity, resolved from forwarded headers."""

import pytest

from crabriks.identity import Unauthenticated, resolve_caller


def test_email_wins_and_the_token_is_kept_for_the_request() -> None:
    caller = resolve_caller(
        {
            "X-Forwarded-Email": "ada@example.com",
            "X-Forwarded-User": "ada",
            "X-Forwarded-Access-Token": "dapi-secret",
        }
    )

    assert caller.user_id == "ada@example.com"
    assert caller.access_token == "dapi-secret"


def test_user_header_is_the_fallback_identity() -> None:
    caller = resolve_caller({"x-forwarded-user": "ada"})

    assert caller.user_id == "ada"
    assert caller.access_token == ""


def test_dev_user_stands_in_only_when_no_header_is_present() -> None:
    caller = resolve_caller({}, dev_user="local@example.com")

    assert caller.user_id == "local@example.com"


def test_missing_identity_is_rejected() -> None:
    with pytest.raises(Unauthenticated):
        resolve_caller({})


def test_a_present_header_ignores_the_dev_user() -> None:
    caller = resolve_caller(
        {"x-forwarded-email": "ada@example.com"},
        dev_user="local@example.com",
    )

    assert caller.user_id == "ada@example.com"
