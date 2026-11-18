from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    auth, availability, compliance, customers, dashboard, drivers, employees, expenses, health, lookups, notifications,
    reports, settings, shifts, trips, users, vehicles, vendors,
)
from app.core.config import get_settings
from app.core.request_context import new_request_id, request_id_var

cfg = get_settings()

if cfg.environment == "production" and (cfg.jwt_secret.startswith("dev-only") or len(cfg.jwt_secret) < 32):
    raise RuntimeError("Refusing to start in production with a default/short JWT_SECRET. Set a random 32+ character secret.")

app = FastAPI(title=f"{cfg.app_name} API", version="1.0.0",
              docs_url=None if cfg.environment == "production" else "/docs",
              redoc_url=None, openapi_url=None if cfg.environment == "production" else "/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context_and_security_headers(request: Request, call_next):
    rid = new_request_id(request.headers.get("X-Request-ID"))
    token = request_id_var.set(rid)  # picked up by the audit service so every audit row carries it
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"  # API responses hold personal data
    if cfg.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


for r in (health.router, auth.router, users.router, vendors.router, lookups.router, customers.router,
          employees.router, shifts.router, availability.router,  # availability before /drivers/{id}
          drivers.router, vehicles.router, trips.router, notifications.router, settings.router,
          dashboard.router, reports.router, compliance.router, expenses.router):
    app.include_router(r, prefix="/api")
