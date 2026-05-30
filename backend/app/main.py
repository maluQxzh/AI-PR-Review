from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_analyze import router as analyze_router
from app.api.routes_demo import router as demo_router
from app.api.routes_reports import router as reports_router
from app.config import get_settings
from app.db.session import init_db


def create_app() -> FastAPI:
    settings = get_settings()
    localhost_origin_regex = (
        r"^http://(localhost|127\.0\.0\.1):\d+$"
        if settings.allow_localhost_dev_origins
        else None
    )
    app = FastAPI(title="AI PR Review Demo", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ],
        allow_origin_regex=localhost_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(analyze_router)
    app.include_router(reports_router)
    app.include_router(demo_router)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
