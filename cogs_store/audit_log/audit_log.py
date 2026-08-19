"""Audit Log cog: provides the Recent Audit Events dashboard widget.

This cog exposes the ``recent_audit`` widget which displays the latest
entries from the audit log table.  It belongs to the ``Logging`` category
in the cog store.
"""

from __future__ import annotations

COG_INFO = {
    "name": "Audit Log",
    "description": "Recent audit events dashboard widget",
    "category": "Logging",
    "requires_admin": False,
    "version": "1.0.0",
}

WIDGETS = [
    {
        "id": "recent_audit",
        "title": "Recent Audit Events",
        "template": "widgets/recent_audit.html",
        "size": "medium",
        "icon": "ph-scroll",
    },
]
