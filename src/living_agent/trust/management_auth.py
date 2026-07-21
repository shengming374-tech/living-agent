"""Bearer authentication boundary for owner control-plane HTTP APIs."""

from __future__ import annotations

import hmac

from pydantic import SecretStr


class ManagementAuthenticator:
    def __init__(
        self,
        *,
        environment: str,
        token: SecretStr | None,
    ) -> None:
        self._token = token.get_secret_value() if token is not None else None
        self.required = environment == "production" or self._token is not None

    def rejection_reason(self, authorization: str | None) -> str | None:
        if not self.required:
            return None
        if authorization is None:
            return "management_token_missing"
        scheme, separator, value = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not value:
            return "management_authorization_invalid"
        if self._token is None or not hmac.compare_digest(value, self._token):
            return "management_token_invalid"
        return None


def is_management_api_path(path: str) -> bool:
    if not path.startswith("/v1/"):
        return False
    return path != "/v1/chat" and not path.startswith("/v1/adapters/")
