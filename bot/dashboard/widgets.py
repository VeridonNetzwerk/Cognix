"""Core dashboard widgets — always available regardless of loaded cogs."""

CORE_WIDGETS = [
    {
        "id": "bot_status",
        "title": "Bot Status",
        "template": "widgets/bot_status.html",
        "size": "medium",
        "icon": "ph-robot",
        "cog": "__core__",
    },
    {
        "id": "metrics_overview",
        "title": "Overview",
        "template": "widgets/metrics_overview.html",
        "size": "medium",
        "icon": "ph-gauge",
        "cog": "__core__",
    },
    {
        "id": "recent_audit",
        "title": "Recent Audit Events",
        "template": "widgets/recent_audit.html",
        "size": "medium",
        "icon": "ph-scroll",
        "cog": "__core__",
    },
]
