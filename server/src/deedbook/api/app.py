"""Application FastAPI deedbook (docs/adr D002)."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from deedbook.api.errors import extract_validation_errors
from deedbook.api.routes import router


def create_app() -> FastAPI:
    """Crée et configure l'application FastAPI deedbook."""
    app = FastAPI(
        title="deedbook",
        version="0.1.0",
        description="Moteur d'audit et de gouvernance pour bases de données PostgreSQL",
        docs_url="/docs",
        redoc_url=None,
    )

    @app.exception_handler(HTTPException)
    async def custom_http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        """Garantit que le corps d'erreur JSON respecte le format d'erreur du projet."""
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "http_error", "detail": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def custom_validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Normalise les erreurs de validation FastAPI vers le format spec §5."""
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": "validation_failed",
                "detail": extract_validation_errors(exc),
            },
        )

    @app.get("/health", tags=["system"], summary="Vérification de disponibilité")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)

    # Chargement dynamique des modules activés dans la politique
    from importlib import import_module

    from deedbook.config import policy

    enabled_modules = policy().get("modules", {}).get("enabled", [])
    for mod_name in enabled_modules:
        try:
            mod = import_module(f"deedbook.modules.{mod_name}.routes")
            if hasattr(mod, "router"):
                app.include_router(mod.router)
        except ModuleNotFoundError:
            pass

    return app
