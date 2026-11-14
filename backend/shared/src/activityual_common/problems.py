import logging

from fastapi import Request

from .logging import correlation_id_var

log = logging.getLogger("activityual.problems")

class ProblemError(Exception):
    def __init__(
        self,
        type_suffix: str,
        status: int,
        title: str,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
        errors: list[dict] | None = None,
    ) -> None:
        super().__init__(title)
        self.type_suffix, self.status, self.title = type_suffix, status, title
        self.detail, self.headers, self.errors = detail, headers or {}, errors or []

def not_found(what: str = "Resource") -> ProblemError:
    return ProblemError("not-found", 404, f"{what} not found")


def unauthenticated(detail: str = "Authentication required") -> ProblemError:
    return ProblemError("unauthenticated", 401, "Authentication required", detail,
                        {"WWW-Authenticate": 'Bearer error="invalid_token"'})


def _body(request: Request, type_suffix: str, status: int, title: str,
          detail: str | None, errors: list[dict] | None) -> dict:
    return{
        "type": type_suffix, 
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "correlationId": correlation_id_var.get(),
        "errors": errors or [],
    }