"""Единый формат ошибок API (§11): {"error": {"code", "message", "details"}}."""

from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_id import HEADER as REQUEST_ID_HEADER

log = structlog.get_logger(__name__)

_STATUS_MESSAGES: dict[int, tuple[str, str]] = {
    400: ("bad_request", "Некорректный запрос"),
    401: ("unauthorized", "Нужна авторизация"),
    403: ("forbidden", "Недостаточно прав"),
    404: ("not_found", "Не найдено"),
    405: ("method_not_allowed", "Метод не поддерживается"),
    409: ("conflict", "Конфликт данных"),
    413: ("payload_too_large", "Слишком большой запрос"),
    422: ("validation_error", "Проверь введённые данные"),
    429: ("too_many_requests", "Слишком много запросов, попробуй позже"),
    503: ("unavailable", "Сервис временно недоступен"),
}


class AppError(Exception):
    """Ошибка бизнес-логики с кодом и русским сообщением для клиента."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def error_response(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def _default_for(status_code: int) -> tuple[str, str]:
    if status_code in _STATUS_MESSAGES:
        return _STATUS_MESSAGES[status_code]
    if status_code >= 500:
        return "internal_error", "Что-то пошло не так, попробуй ещё раз"
    return HTTPStatus(status_code).phrase.lower().replace(" ", "_"), "Ошибка запроса"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _default_for(exc.status_code)
        # Стандартный detail FastAPI английский — заменяем, оставляем только явно заданный.
        if isinstance(exc.detail, str) and exc.detail != HTTPStatus(exc.status_code).phrase:
            message = exc.detail
        response = error_response(exc.status_code, code, message)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"loc": list(e.get("loc", ())), "type": e.get("type"), "msg": e.get("msg")}
            for e in exc.errors()
        ]
        code, message = _STATUS_MESSAGES[422]
        return error_response(422, code, message, {"fields": fields})

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        log.error(
            "unhandled_error", error_type=type(exc).__name__, request_id=request_id, exc_info=exc
        )
        code, message = _default_for(500)
        response = error_response(500, code, message)
        if request_id:
            response.headers[REQUEST_ID_HEADER] = request_id
        return response
