"""Интеграция с MAX Bot API."""

from app.integrations.max.client import MaxApiError, MaxClient, client_from_settings

__all__ = ["MaxApiError", "MaxClient", "client_from_settings"]
