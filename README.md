# n8n Lead Pipeline

A lead intake workflow built in n8n, with the parts a visual workflow tool is
bad at moved into a small FastAPI service: atomic deduplication, durable
storage, and a dashboard that shows whether the workflow is actually running.

**[→ Live demo dashboard](https://haiderali2755.github.io/n8n-lead-pipeline/)**

**Personal project** — built to demonstrate the pattern, not for a client.

## The problem it addresses

Most n8n builds are handed over as a workflow and nothing else. That works
until it doesn't, and when it stops working it fails quietly:

- A workflow that stopped firing looks identical to a quiet day with no leads.
- The same form submitted twice creates two leads, two notifications, two
  follow-up calls.
- An error is recorded in the n8n execution log, which nobody opens until a
  client asks why nobody called a customer back.

This project keeps n8n for orchestration — that is what it is good at — and
puts a service behind it for the three things above.

## Architecture

```
Form / webhook
      │
      ▼
┌─────────────────────────────────────────────┐
│ n8n: Lead Intake workflow                   │
│  1. validate and normalise                  │
│  2. claim dedupe key      ──┐               │
│  3. score (rule-based)      │               │
│  4. store lead            ──┤               │
│  5. record failure on error ┘               │
└─────────────────────────────┼───────────────┘
                              ▼
                  ┌────────────────────────┐
                  │ Tracker API (FastAPI)  │
                  │  PostgreSQL            │
                  └───────────┬────────────┘
                              ▼
                    Dashboard (same origin)
```

## Three decisions worth explaining

**Deduplication happens in Postgres, not in n8n.** n8n can check whether it has
seen something before, but check-then-insert is two steps, and two requests
arriving together will both pass the check. The tracker uses a `UNIQUE` primary
key with `ON CONFLICT DO NOTHING` and returns whether a row was actually
inserted. The database decides, so the race cannot happen.

**Scoring is rules, not an LLM.** An API call per lead would be the slowest and
most failure-prone step in the workflow, and the first thing to blow a rate
limit under a traffic spike. Rules are instant, free, deterministic, and a
client can read them and argue with them — which matters more here than
sophistication.

**Failures are recorded, not just logged.** The `Store Lead` node continues on
error into a node that POSTs the failure to the tracker, so the dashboard can
show it. The webhook still answers the caller with a 503 rather than a silent
success, because a form that says "thanks" while dropping the lead is worse
than one that says "try again".

## The workflow

`workflows/lead-intake.json` — import it into n8n via **Workflows → Import from
file**.

| Step | What it does |
|---|---|
| Lead Webhook | `POST /webhook/lead`, responds via a Respond node so status codes are explicit |
| Validate and Normalise | Rejects malformed payloads early with a readable reason |
| Claim Dedupe Key | Atomic claim against the tracker; duplicates get `200 duplicate` |
| Score Lead | Rule-based 0–100 score plus hot/warm/cold tier and the reasons why |
| Store Lead | Persists to Postgres, 3 retries with backoff |
| Record Failure | On error, writes the failure to the tracker so it appears on the dashboard |

Response codes: `202` accepted, `200` duplicate, `400` rejected, `503` stored
failed but queued.

## The dashboard

Served by the tracker at `http://localhost:8000`.

- **Health banner** — healthy, stale, or failing. Staleness is measured as time
  since the last lead, because that is the signal that catches a workflow which
  silently stopped.
- **Hourly volume** with the hot-tier share on the same axis.
- **Tier distribution**, **by source**, **recent leads**, **unresolved failures**.

Charts use categorical slots 1–3 of a validated palette, checked in both light
and dark mode (worst adjacent colour-blind separation ΔE 9.2 light / 9.4 dark).
Status colours in the health banner always ship with an icon and a written
label, never colour alone.

## Running it

Requires Docker.

```bash
docker compose up -d --build
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:8000 |
| Tracker API docs | http://localhost:8000/docs |
| n8n editor | http://localhost:5678 |

Then in n8n: import `workflows/lead-intake.json`, open it, and activate it.

Send a test lead:

```bash
curl -X POST http://localhost:5678/webhook/lead \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Sara Ahmed",
    "email": "sara@acme-industrial.com",
    "message": "We need a quote for 200 units, budget approved, timeline is urgent.",
    "source": "website-form"
  }'
```

That one scores highly: business domain, several buying signals, detailed
message. Send it twice within 15 minutes and the second call returns
`{"status":"duplicate"}` without creating a second lead.

## The demo page

`docs/` holds a static copy of the dashboard for GitHub Pages. It is the same
interface rendering fixtures captured off a running instance rather than
polling the API, because Pages serves static files only. The page says so at
the top rather than implying it is live.

Timestamps are rebased at render time against the newest lead, so the snapshot
reads as recent months later instead of drifting into "3 weeks ago".

To regenerate it:

```bash
docker compose up -d
python3 scripts/seed.py
python3 scripts/capture_demo.py
```

## Layout

```
workflows/lead-intake.json   The n8n workflow, importable
api/main.py                  FastAPI tracker: dedupe, storage, stats
dashboard/index.html         Live monitoring dashboard, no build step
docs/                        Static demo for GitHub Pages
scripts/seed.py              Sample data using the workflow's own scoring rules
scripts/capture_demo.py      Regenerates the demo fixtures from a running stack
docker-compose.yml           n8n + Postgres + tracker
```

## Stack

n8n · Python · FastAPI · PostgreSQL · Docker
