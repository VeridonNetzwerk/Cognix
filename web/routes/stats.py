"""Stats routes (aggregated)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from database.models.stats import AggregatedStat, StatEventType
from web.deps import SessionDep, require_mod
from web.schemas.common import StatsPoint, StatsSeries

router = APIRouter(prefix="/stats", tags=["stats"], dependencies=[Depends(require_mod)])


@router.get("/overview")
async def overview(session: SessionDep, days: int = 30, server_id: str | None = None) -> dict:
    since = date.today() - timedelta(days=days)
    series: list[StatsSeries] = []
    for et in StatEventType:
        stmt = (
            select(AggregatedStat.day, func.sum(AggregatedStat.count))
            .where(AggregatedStat.event_type == et, AggregatedStat.day >= since)
            .group_by(AggregatedStat.day)
            .order_by(AggregatedStat.day.asc())
        )
        if server_id:
            stmt = stmt.where(AggregatedStat.server_id == int(server_id))
        rows = (await session.execute(stmt)).all()
        series.append(
            StatsSeries(
                metric=et.value,
                points=[StatsPoint(day=str(d), count=int(c or 0)) for d, c in rows],
            )
        )
    return {"series": [s.model_dump() for s in series]}
