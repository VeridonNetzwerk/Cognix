"""CRUD API for customizable embed templates."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from database.models.embed_template import EmbedTemplate
from web.deps import SessionDep, require_admin, require_mod

router = APIRouter(prefix="/embeds", tags=["embeds"], dependencies=[Depends(require_mod)])


class EmbedFieldIn(BaseModel):
    name: str = ""
    value: str = ""
    inline: bool = False


class EmbedTemplateIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    server_id: int | None = None
    enabled: bool = True
    title: str = ""
    description: str = ""
    color: int = 0x60A5FA
    footer_text: str = ""
    footer_icon_url: str = ""
    thumbnail_url: str = ""
    image_url: str = ""
    author_name: str = ""
    author_icon_url: str = ""
    author_url: str = ""
    fields: list[EmbedFieldIn] = []
    extras: dict[str, Any] = {}


def _serialize(t: EmbedTemplate) -> dict:
    return {
        "id": t.id, "key": t.key, "server_id": t.server_id, "enabled": t.enabled,
        "title": t.title, "description": t.description, "color": t.color,
        "footer_text": t.footer_text, "footer_icon_url": t.footer_icon_url,
        "thumbnail_url": t.thumbnail_url, "image_url": t.image_url,
        "author_name": t.author_name, "author_icon_url": t.author_icon_url,
        "author_url": t.author_url, "fields": t.fields, "extras": t.extras,
    }


@router.get("")
async def list_templates(session: SessionDep) -> list[dict]:
    rows = (await session.scalars(select(EmbedTemplate).order_by(EmbedTemplate.key))).all()
    return [_serialize(t) for t in rows]


@router.get("/{tpl_id}")
async def get_template(tpl_id: int, session: SessionDep) -> dict:
    t = await session.get(EmbedTemplate, tpl_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return _serialize(t)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(payload: EmbedTemplateIn, session: SessionDep) -> dict:
    existing = await session.scalar(
        select(EmbedTemplate).where(EmbedTemplate.key == payload.key,
                                    EmbedTemplate.server_id == payload.server_id)
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "key+server_id already exists")
    t = EmbedTemplate(**{
        **payload.model_dump(),
        "fields": [f.model_dump() for f in payload.fields],
    })
    session.add(t)
    await session.flush()
    return _serialize(t)


@router.patch("/{tpl_id}")
async def update_template(tpl_id: int, payload: EmbedTemplateIn, session: SessionDep) -> dict:
    t = await session.get(EmbedTemplate, tpl_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    data = payload.model_dump()
    data["fields"] = [f.model_dump() if hasattr(f, "model_dump") else f for f in payload.fields]
    for k, v in data.items():
        setattr(t, k, v)
    return _serialize(t)


@router.delete("/{tpl_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_admin)])
async def delete_template(tpl_id: int, session: SessionDep) -> None:
    t = await session.get(EmbedTemplate, tpl_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    await session.delete(t)
