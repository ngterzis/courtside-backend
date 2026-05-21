# Courtside — Backend Requirements

This document is the single source of truth for any backend implementation.
It is framework- and language-agnostic. The frontend is a Vite + React + TypeScript
SPA that talks to these endpoints and expects these exact JSON shapes.

---

## Auth

**Mechanism:** JWT stored in `localStorage` on the client, sent as a Bearer token.

```
Authorization: Bearer <jwt>
```

All `/api/me/*` and `/api/games/*` endpoints require a valid token.
Return `401` when the token is missing, expired, or invalid — the frontend redirects to `/login`.

**JWT payload:**
```json
{ "sub": "<playerId>", "iat": 1234567890, "exp": 1234567890 }
```

Sign with HS256 or RS256. Recommended expiry: **15 minutes** with a refresh token
(httpOnly cookie or separate long-lived JWT) that issues new access tokens silently.
If you skip refresh tokens initially, use a longer access token expiry (e.g. 7 days)
and accept the trade-off.

```
POST /api/auth/login
  Body:    { email: string, password: string }
  200:     { token: string, player: Player }
  401:     { error: "invalid_credentials" }

POST /api/auth/logout
  200:     {}       (client deletes token from localStorage)

GET  /api/me
  Headers: Authorization: Bearer <token>
  200:     Player
  401:     (missing or invalid token)
```

**Frontend wiring:** on login, store the token with `localStorage.setItem('courtside_token', token)`.
Attach it to every API request. On 401, clear the token and redirect to `/login`.
The real security leverage here is a strong Content Security Policy to prevent XSS
in the first place, and HTTPS everywhere.

---

## Data models

These are the exact shapes the frontend deserialises. Field names are **camelCase**.
All dates are **ISO 8601 strings** (`YYYY-MM-DD` for dates, full ISO for timestamps).

```
Player {
  id:            string
  name:          string
  jerseyNumber:  number
  position:      "Guard" | "Forward" | "Center"
  teamId:        string
  onboardedAt:   string | null   // null = onboarding not yet completed
}

Season {
  id:        string
  label:     string              // e.g. "Spring '26"
  startDate: string              // YYYY-MM-DD
  endDate:   string | null       // null = active season
}

GameStats {
  points:         number
  rebounds:       number
  assists:        number
  steals:         number
  blocks:         number
  turnovers:      number
  fouls:          number
  fgMade:         number
  fgAttempted:    number
  threeMade:      number
  threeAttempted: number
  ftMade:         number
  ftAttempted:    number
  // Derived — always compute server-side and include on EVERY Game and SeasonAverages response.
  // The frontend prefers these values and only falls back to client-side computation when absent.
  // Formulas:
  fgPct:    number               // fgMade / fgAttempted  (0 if fgAttempted = 0)
  threePct: number               // threeMade / threeAttempted
  ftPct:    number               // ftMade / ftAttempted
  tsPct:    number               // points / (2 * (fgAttempted + 0.44 * ftAttempted))
}

CoachNote {
  id:         string
  gameId:     string
  authorName: string
  text:       string
  createdAt:  string             // ISO timestamp
}

Game {
  id:            string
  seasonId:      string
  date:          string          // YYYY-MM-DD
  opponent:      string
  homeAway:      "H" | "A"
  result:        "W" | "L"
  teamScore:     number
  opponentScore: number
  stats:         GameStats
  personalBests: string[]        // stat field names that were season highs in this game
                                 // e.g. ["points", "assists"]
  coachNote?:    CoachNote
}

SeasonAverages extends GameStats {
  seasonId:    string
  gamesPlayed: number
  // All GameStats fields are per-game averages, including the derived ones.
}

ArchetypeReceiptLine {
  stat:       string             // e.g. "AST/g", "TS%"
  value:      string             // formatted value, e.g. "5.0", "56%"
  percentile: number             // 0–100, position-adjusted percentile vs teammates
  comment:    string             // short prose explanation, e.g. "elite assist rate"
}

ArchetypeScore {
  name:        string
  score:       number            // 0–100 fit score for this archetype
  isPrimary?:  boolean
  isSecondary?: boolean
}

Archetype {
  primary:     ArchetypeName
  secondary:   ArchetypeName
  explanation: string            // 1–2 sentence AI-generated prose
  receipt:     ArchetypeReceiptLine[]
  scores?:     ArchetypeScore[]  // fit scores for all archetypes, sorted descending
  assignedAt:  string            // ISO timestamp
  seasonId:    string
}

ArchetypeName =
  "Playmaker" | "Efficient Scorer" | "Glass Cleaner" | "Defensive Anchor" |
  "3&D Wing" | "Rim Protector" | "Spark Plug" | "Floor General" | "Hustle Player"

TeamRank {
  stat:       string             // GameStats field name, e.g. "assists", "threePct"
  percentile: number             // 0–100 vs all players on the same team this season
  label:      string             // human label, e.g. "#1 on team", "above avg", "below avg"
}

TrendPoint {
  date:      string              // YYYY-MM-DD (game date)
  value:     number
  gameId?:   string
  opponent?: string
}
```

---

## Onboarding

```
POST /api/me/onboard
  Body: { jerseyNumber: number, position: "Guard" | "Forward" | "Center" }
  200:  Player                   (with onboardedAt now set)
  400:  { error: string }
```

After a successful login, the frontend checks `player.onboardedAt`. If `null` it
redirects to `/onboarding`. After `POST /api/me/onboard` it redirects to `/`.

---

## Seasons

```
GET /api/seasons
  200: Season[]                  // all seasons, newest first

GET /api/seasons/current
  200: Season                    // the season with endDate = null
```

---

## Games

```
GET /api/me/games?seasonId=<id>&limit=<n>&offset=<n>
  200: { games: Game[], total: number }
  // If seasonId is omitted, use the current season.
  // Default limit: 50. Games ordered by date descending.

GET /api/games/:id
  200: Game
  404: { error: "not_found" }
```

The frontend also calls `useLastGame` which expects a single `Game` (the most recent
for the season). Implement this as a convenience:

```
GET /api/me/games/last?seasonId=<id>
  200: Game | null
```

Or return it as part of `GET /api/me/games?limit=1`.

---

## Season averages

```
GET /api/me/season-averages?seasonId=<id>
  200: SeasonAverages
```

Compute averages server-side from all games in the season. Include derived stats
(fgPct, threePct, ftPct, tsPct).

---

## Team ranks

```
GET /api/me/team-ranks?seasonId=<id>
  200: TeamRank[]
```

Compares this player's season averages against all other players on the same team
for the given season. Return a `TeamRank` entry for at least: `assists`, `rebounds`,
`steals`, `threePct`. The frontend uses these to populate the radar chart and archetype
profile section.

Percentile labels:
- 90–100 → "#1 on team" (or "#2 on team" if not top)
- 70–89  → "top 3"
- 50–69  → "above avg"
- 30–49  → "below avg"
- 0–29   → "bottom 3"

---

## Archetype

### Current season archetype

```
GET /api/me/archetype?seasonId=<id>
  200: Archetype
  404: { error: "insufficient_games" }   // fewer than 3 games played
```

### Cross-season history

```
GET /api/me/archetype/history
  200: Archetype[]                        // one per season, newest first
```

### Assignment logic

The archetype can be rule-based, AI-generated, or a hybrid. The frontend only
consumes the `Archetype` object — it does not care how the backend computes it.

**Minimum viable approach (rule-based):**

1. Compute the player's percentile rank against teammates for each stat.
2. Score each archetype using a weighted formula over those percentiles.
3. Sort archetypes by score; `primary` = highest, `secondary` = second-highest.
4. Build the `receipt` array from the 3–5 stats most influential in the primary score.
5. Write the `explanation` with the Anthropic SDK (one-shot, not streamed):
   - System: "You are a basketball analytics assistant. Write 1–2 sentences explaining
     why this player is a {primary} / {secondary}. Be specific and reference their
     stats. No filler phrases."
   - User: pass the receipt lines as structured data.
6. Cache the result. Regenerate when a new game is logged for this player/season,
   or on manual admin trigger.

**`scores` array:** include a fit score (0–100) for every archetype, sorted
descending. The frontend renders a bar chart from this.

---

## Chat

```
POST /api/chat
  Body:    { messages: Array<{ role: "user" | "assistant", content: string }> }
  200:     text/event-stream (SSE)
```

### SSE format

Each token chunk:
```
data: {"text":"<token>"}\n\n
```

Terminator:
```
data: [DONE]\n\n
```

The frontend's SSE parser (`src/routes/chat.tsx → readSSE`) expects exactly this
format. Do not send any other event types or field names.

### Context injection (server-side, never sent from client)

Before calling the Anthropic API, prepend a system message that includes:

```
You are Courtside Agent, a basketball analytics assistant for a recreational league.
Answer questions about the player's own stats only. Never name or compare teammates.
Do not speculate about playing time, injuries, or coaching decisions.
Be concise and specific — reference actual numbers.

Player: {name}, #{jerseyNumber}, {position}
Season: {seasonLabel} ({gamesPlayed} games)

Season averages:
  PTS {points} | AST {assists} | REB {rebounds} | STL {steals}
  TOV {turnovers} | TS% {tsPct} | FG% {fgPct} | 3PT% {threePct}

Archetype: {primary} / {secondary}
  "{explanation}"

Recent games (last 5, newest first):
  {date} vs {opponent} ({H|A}): {points}pts {rebounds}reb {assists}ast
  ...

Last game highlights: {personalBests if any}
```

Inject real values at request time. Fetch the player's current season averages,
archetype, and last 5 games from your database — do not trust any context the
client sends.

### Streaming

Use the Anthropic SDK with `stream: true`. Forward each `text_delta` event directly
to the SSE response as `data: {"text":"<delta>"}\n\n`. When the stream ends, write
`data: [DONE]\n\n` and close the connection.

### Guardrails (system prompt)

- No teammate names or comparisons
- No off-topic responses (not about their stats → politely decline)
- No speculation about playing time, injuries, or coaching decisions

---

## Notifications

```
GET  /api/me/notifications
  200: Notification[]            // all, newest first

POST /api/me/notifications/:id/read
  200: {}
```

```
Notification {
  id:        string
  type:      "personal_best" | "stats_ready" | "coach_note" |
             "archetype_changed" | "weekly_summary"
  payload:   object              // type-specific data (game id, stat name, etc.)
  createdAt: string
  readAt:    string | null
}
```

Notifications are created server-side by background jobs:
- `personal_best` — when a new game is saved and a stat exceeds the player's prior season high
- `stats_ready` — when a new game is saved for this player
- `archetype_changed` — when the archetype assignment changes vs previous
- `weekly_summary` — Sunday digest (scheduled job)
- `coach_note` — when a coach note is attached to a game for this player

---

## Query key / cache invalidation map

When a new game is saved for a player, invalidate these on the client by pushing
a `stats_ready` notification. The frontend re-fetches on notification receipt.

| Endpoint | Query key |
|---|---|
| GET /api/me | `['me']` |
| GET /api/seasons | `['seasons']` |
| GET /api/seasons/current | `['seasons', 'current']` |
| GET /api/me/archetype | `['archetype', seasonId]` |
| GET /api/me/archetype/history | `['archetype', 'history']` |
| GET /api/me/games | `['games', { seasonId }]` |
| GET /api/games/:id | `['game', gameId]` |
| GET /api/me/season-averages | `['season-averages', seasonId]` |
| GET /api/me/team-ranks | `['team-ranks', seasonId]` |
| GET /api/me/notifications | `['notifications']` |

---

## Wiring the frontend

When the real backend is ready, replace the mock implementations in
`src/lib/queries.ts`. Each `useQuery` currently returns mock data — swap
each `queryFn` to call `fetch('/api/...')` and return the parsed JSON.

The `POST /api/chat` endpoint is already wired in `src/routes/chat.tsx`.
The Vite dev plugin in `vite.config.ts` (`mock-chat-api`) can be removed
once a real server handles `/api/chat`.

---

## Error envelope

All error responses:
```json
{ "error": "<machine_readable_code>", "message": "<human_readable>" }
```

Standard HTTP status codes: 400 bad request, 401 unauthenticated, 403 forbidden,
404 not found, 422 validation error, 500 server error.
