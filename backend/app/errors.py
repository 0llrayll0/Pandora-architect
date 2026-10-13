"""Erros padronizados da API: sempre ``{"detail": str, "code": str}``."""

from __future__ import annotations

from typing import Any


class ApiException(Exception):
    """Erro de domínio traduzido pelo handler global em JSON padronizado."""

    def __init__(
        self,
        detail: str,
        *,
        code: str = "bad_request",
        status_code: int = 400,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = code
        self.status_code = status_code
        self.extra = extra or {}


def bad_request(detail: str, code: str = "bad_request") -> ApiException:
    return ApiException(detail, code=code, status_code=400)


def not_found(detail: str, code: str = "not_found") -> ApiException:
    return ApiException(detail, code=code, status_code=404)


def conflict(detail: str, code: str = "conflict") -> ApiException:
    return ApiException(detail, code=code, status_code=409)


def payload_error(detail: str, code: str = "validation_error") -> ApiException:
    return ApiException(detail, code=code, status_code=422)


__all__ = [
    "ApiException",
    "bad_request",
    "conflict",
    "not_found",
    "payload_error",
]
