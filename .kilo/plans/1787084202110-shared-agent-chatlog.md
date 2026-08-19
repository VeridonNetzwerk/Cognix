# Plan: Shared Agent Conversation Ledger (Kilo ↔ Other AI)

## Goal
Enable Kilo Code and a second AI tool (Windsurf / Devin) to see each other's chat
history and current project state by maintaining a **single, repo-resident, append-only
conversation ledger** that both tools read at session start and append to after turns.

## Hard constraint (state to user)
There is **no native real-time bidirectional sync** between Kilo Code and Devin or
Windsurf. No official API bridge exists. The ledger approach is a *polled shared file*,
not a live socket. Each tool sees the other's chat only after a sync/write occurs and is
picked up (locally for Windsurf, via git push/pull for Devin).

## Design

### 1. Canonical ledger file
Create `AGENT_CHATLOG.md` at the repo root (not hidden, so Windsurf and Devin both index it).
- Top section: `# Project State` — short, kept-current summary of branch, what's in progress,
  open decisions, blockers.
- Below: append-only `# Session Log` with one entry block per turn/session.

Entry format (keeps it scannable, avoids raw transcript bloat):
```
## [YYYY-MM-DD HH:MM TZ] — <Agent: Kilo | Windsurf | Devin>
- Request: <one line>
- Actions: <bullet list of files changed / commands run>
- Decisions: <what was decided and why>
- Open: <unresolved questions / handoffs for the other agent>
```

### 2. Protocol (documented in `AGENT_CHATLOG.md` header + `AGENTS.md`)
- Every agent, at the **start of work**, reads the full `AGENT_CHATLOG.md`.
- After a meaningful turn (or end of session), appends one entry block as above.
- Keep entries as **summaries**, not full transcripts. Archive stale entries to
  `AGENT_CHATLOG.archive.md` when the log exceeds ~400 lines.
- Resolve edit conflicts via git (append-only + per-turn blocks minimize clashes).

### 3. Kilo-side automation (on-demand, not automatic)
Kilo has no post-turn hook, so syncing is **user-triggered**. Provide:
- `.kilo/command/sync-chat.md` — a slash command that instructs Kilo to:
  1. Summarize the current conversation (request, actions, decisions, open items).
  2. Update the `# Project State` block if stale.
  3. Append a new entry to `AGENT_CHATLOG.md`.
  User runs `/sync-chat` (or simply asks "sync the chat log") to push Kilo's context out.
- Optionally `.kilo/agent/context-sync.md` — an agent persona dedicated to maintaining the
  ledger, so the user can delegate with `/context-sync`.

Do **not** attempt to auto-parse Kilo's internal session storage (location/format is
implementation-specific and unstable); on-demand summarization by the agent is the robust path.

### 4. Other-AI specifics
- **Windsurf (Codeium IDE, local):** Point Cascade at this repo. In its session prompt, tell
  it to read `AGENT_CHATLOG.md` first and append its turns. Live file access → near real-time.
- **Devin (Cognition, cloud):** Link the GitHub repo. Commit/push `AGENT_CHATLOG.md` so Devin
  sees it; instruct Devin (session prompt) to read + append. Pull the updated log back and
  commit so Kilo/Windsurf see Devin's turns. Sync cadence = git push/pull, not live.

## Files to create / edit
- `AGENT_CHATLOG.md` — ledger + protocol header (new).
- `AGENT_CHATLOG.archive.md` — archived old entries (new, can start empty).
- `.kilo/command/sync-chat.md` — Kilo sync command (new).
- `.kilo/agent/context-sync.md` — optional dedicated sync agent (new).
- `AGENTS.md` — add a short "Cross-agent context" section pointing to the ledger (new or edit).

## Validation
1. Run `/sync-chat` in Kilo → confirm a new entry + updated `# Project State` appear in
   `AGENT_CHATLOG.md`.
2. Open the same repo in Windsurf; confirm Cascade reads the file and can append a turn.
3. (If Devin) commit/push the log, start a Devin session on the repo, confirm it reads the
   entry; append a Devin turn, pull + commit, confirm Kilo sees it via `/sync-chat` context.
4. Verify conflict handling: make non-overlapping edits from both sides, commit, confirm clean merge.

## Assumptions / open questions
- **Target tool unclear (Windsurf vs Devin vs both).** Plan covers both; the only difference is
  whether sync uses local file access (Windsurf) or git push/pull (Devin). Confirm which.
- User accepts **on-demand** sync (manual `/sync-chat` or per-request), not automatic real-time.
- Ledger entries are **summaries**, not verbatim transcripts (keeps file usable).
