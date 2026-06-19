from fastapi import FastAPI

from app.modules.auth.routes import router as auth_router
from app.modules.dev.routes import router as dev_router
from app.modules.documents.routes import router as documents_router
from app.modules.health.routes import router as health_router
from app.modules.partner_webhooks.routes import router as webhooks_router


OPENAPI_TAGS = [
    {
        "name": "Auth",
        "description": "Authenticate demo users and inspect the current JWT identity.",
    },
    {
        "name": "Documents",
        "description": "Create, upload, process and read tenant documents.",
    },
    {
        "name": "Partner webhook",
        "description": "Receive the signed asynchronous result from the external partner.",
    },
    {
        "name": "Local test helpers",
        "description": "Local/test-only helpers used to run the full flow from Swagger.",
    },
    {
        "name": "Health",
        "description": "Simple runtime healthcheck.",
    },
]

API_DESCRIPTION = """
Primmo tenant document ingestion API.

Client flow:
1. Login with `POST /auth/login` and use the returned bearer token.
2. Create a document with `POST /documents`.
3. Upload the PDF with the returned presigned `upload_url`.
4. Call `POST /documents/{document_id}/complete-upload`.
5. Follow status with `GET /documents/{document_id}` or the SSE stream.
6. Read the extracted result once the document is `ready`.

Swagger can use the local `/dev` helpers to upload a PDF and sign a partner webhook.
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="Primmo Documents API",
        summary="Tenant PDF ingestion and processing API.",
        description=API_DESCRIPTION,
        version="0.1.0",
        openapi_tags=OPENAPI_TAGS,
    )
    app.include_router(auth_router)
    app.include_router(documents_router)
    app.include_router(webhooks_router)
    app.include_router(dev_router)
    app.include_router(health_router)
    return app


app = create_app()
