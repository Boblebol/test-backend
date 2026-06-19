from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Healthcheck", description="Return `ok` when the API process is running.")
def health() -> dict[str, str]:
    return {"status": "ok"}
