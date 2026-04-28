"""Embed factory helpers."""

from __future__ import annotations

import discord

EMBED_COLOR_OK = 0x4ADE80
EMBED_COLOR_WARN = 0xF59E0B
EMBED_COLOR_ERR = 0xEF4444
EMBED_COLOR_INFO = 0x60A5FA

FOOTER_TEXT = "Powered by Cognix · Made by 食べ物"


def _build(title: str, description: str, color: int) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
    )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def info_embed(title: str, description: str = "") -> discord.Embed:
    return _build(title, description, EMBED_COLOR_INFO)


def ok_embed(title: str, description: str = "") -> discord.Embed:
    return _build(title, description, EMBED_COLOR_OK)


def warn_embed(title: str, description: str = "") -> discord.Embed:
    return _build(title, description, EMBED_COLOR_WARN)


def err_embed(title: str, description: str = "") -> discord.Embed:
    return _build(title, description, EMBED_COLOR_ERR)
