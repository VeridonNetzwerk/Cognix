# Slash commands

| Command | Cog | Permission | Description |
|---|---|---|---|
| `/ping` | utility | – | Show bot latency |
| `/info` | utility | – | Diagnostics: uptime, memory, latency, server count |
| `/userinfo [user]` | utility | – | User info |
| `/serverinfo` | utility | – | Guild info |
| `/roll [max]` | utility | – | Random 1..N |
| `/flip` | utility | – | Coin flip |
| `/ban <user> [reason] [delete_days]` | moderation | Ban members | Ban user |
| `/unban <user_id> [reason]` | moderation | Ban members | Unban user |
| `/kick <user> [reason]` | moderation | Kick members | Kick member |
| `/mute <user> [reason] [duration]` | moderation | Moderate members | Timeout (max 28d) |
| `/unmute <user> [reason]` | moderation | Moderate members | Remove timeout |
| `/warn <user> <reason>` | moderation | Moderate members | Warn member |
| `/purge <count> [user]` | moderation | Manage messages | Delete recent messages |
| `/ticket-panel` | tickets | Manage channels | Post ticket-creation panel |
| `/ticket-close` | tickets | – | Close current ticket thread |
| `/backup` | backups | Administrator | Snapshot roles & channels |
| `/play <query>` | music | – | Play / queue track |
| `/pause` `/resume` `/skip` `/queue` `/stop` | music | – | Music controls |

Durations accept `1h30m`, `45m`, `2d`, etc.
