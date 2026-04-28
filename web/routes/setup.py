"""Setup wizard routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from web.deps import SessionDep
from web.schemas.auth import SetupRequest, SetupResponse, SetupStatus
from web.services.setup_service import SetupError, get_status, perform_setup

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatus)
async def setup_status(session: SessionDep) -> SetupStatus:
    data = await get_status(session)
    return SetupStatus(**data)


@router.post("/initialize", response_model=SetupResponse)
async def initialize(req: SetupRequest, session: SessionDep) -> SetupResponse:
    try:
        return await perform_setup(session, req)
    except SetupError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
