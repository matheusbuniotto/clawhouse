"""Databricks Apps identity, read from the reverse-proxy headers on each request."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

AuthMode = Literal["forwarded", "dev"]


class Unauthenticated(Exception):
    """The request did not carry a Databricks user identity."""


@dataclass(frozen=True, slots=True)
class Caller:
    """The signed-in user for this request. The token is not stored."""

    user_id: str
    access_token: str
    auth_mode: AuthMode = "forwarded"


def resolve_caller(
    headers: Mapping[str, str],
    *,
    dev_user: str | None = None,
) -> Caller:
    """Resolve the caller from `X-Forwarded-*` headers.

    Email wins over the IdP user id. `dev_user` applies only when the proxy
    sent neither, so local runs can open the chat without pretending a header
    was present.
    """
    lowered = {name.lower(): value for name, value in headers.items() if value}
    user_id = lowered.get("x-forwarded-email") or lowered.get("x-forwarded-user")
    token = lowered.get("x-forwarded-access-token", "")
    if user_id:
        return Caller(user_id=user_id, access_token=token, auth_mode="forwarded")
    if dev_user:
        return Caller(user_id=dev_user, access_token=token, auth_mode="dev")
    raise Unauthenticated
