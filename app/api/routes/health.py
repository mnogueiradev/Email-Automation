"""Process liveness endpoint."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health/live", include_in_schema=False)
def liveness() -> dict[str, str]:
    """Report that the API process can answer requests; no dependencies are probed."""

    return {"status": "ok"}
