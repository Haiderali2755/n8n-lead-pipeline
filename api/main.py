"""Tracker API for the n8n lead pipeline.

n8n handles orchestration. This service handles the parts a visual workflow
tool is bad at: atomic deduplication, durable storage, and a queryable record
of what the workflow actually did.

The split matters. A workflow that silently stops firing looks identical to a
workflow with no incoming leads, and the usual n8n answer is "check the
executions tab" — which nobody does until a client asks why nobody called them
back. Every run lands here instead, successes and failures alike.
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgres://leads:leads@localhost:5432/leads"
)
API_KEY = os.getenv("TRACKER_API_KEY", "dev-key-change-me")
DEDUPE_WINDOW_MINUTES = int(os.getenv("DEDUPE_WINDOW_MINUTES", "15"))

pool: Optional[asyncpg.Pool] = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id           BIGSERIAL PRIMARY KEY,
    email        TEXT        NOT NULL,
    name         TEXT        NOT NULL,
    message      TEXT        NOT NULL DEFAULT '',
    source       TEXT        NOT NULL DEFAULT 'unknown',
    score        INT         NOT NULL,
    tier         TEXT        NOT NULL,
    reasons      JSONB       NOT NULL DEFAULT '[]'::jsonb,
    ai_intent    TEXT,
    ai_urgency   TEXT,
    ai_summary   TEXT,
    ai_status    TEXT,
    received_at  TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS leads_created_idx ON leads (created_at DESC);
CREATE INDEX IF NOT EXISTS leads_tier_idx ON leads (tier);

-- The dedupe table is the reason this API exists rather than doing the check
-- inside n8n. A UNIQUE constraint makes the claim atomic: two requests racing
-- with the same key, one wins, the other is told it lost. Checking "does this
-- exist" and then inserting would let both through under concurrency.
CREATE TABLE IF NOT EXISTS dedupe_claims (
    dedupe_key  TEXT        PRIMARY KEY,
    workflow    TEXT        NOT NULL,
    claimed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS dedupe_claimed_idx ON dedupe_claims (claimed_at);

CREATE TABLE IF NOT EXISTS failures (
    id          BIGSERIAL PRIMARY KEY,
    workflow    TEXT        NOT NULL,
    node        TEXT        NOT NULL,
    error       TEXT        NOT NULL,
    payload     JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved    BOOLEAN     NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS failures_occurred_idx ON failures (occurred_at DESC);

-- Added after the AI enrichment step. Separate ALTERs so an existing install
-- picks them up on restart without a manual migration.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS ai_intent  TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS ai_urgency TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS ai_summary TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS ai_status  TEXT;
"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
    yield
    await pool.close()


app = FastAPI(
    title="n8n Lead Pipeline Tracker",
    description="Deduplication, storage and observability for the lead intake workflow.",
    version="1.0.0",
    lifespan=lifespan,
)

# The dashboard is served from this same origin, so CORS is only needed if a
# client wants to query the API from their own front end.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def require_api_key(x_api_key: str = Header(default="")) -> None:
    """Write endpoints are key-protected.

    The webhook itself is public by necessity, but nothing should be able to
    write leads or clear failures without the key.
    """
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing x-api-key")


class ClaimRequest(BaseModel):
    dedupe_key: str = Field(min_length=1, max_length=255)
    workflow: str = Field(default="unknown", max_length=100)


class LeadIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    message: str = Field(default="", max_length=5000)
    source: str = Field(default="unknown", max_length=100)
    score: int = Field(ge=0, le=100)
    tier: str = Field(pattern="^(hot|warm|cold)$")
    reasons: list[str] = Field(default_factory=list)
    ai_intent: Optional[str] = None
    ai_urgency: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_status: Optional[str] = None
    received_at: Optional[datetime] = None


class FailureIn(BaseModel):
    workflow: str = Field(max_length=100)
    node: str = Field(max_length=200)
    error: str = Field(max_length=2000)
    payload: Optional[dict] = None


@app.post("/api/events/claim", dependencies=[Depends(require_api_key)])
async def claim(req: ClaimRequest):
    """Atomically claim a dedupe key.

    Returns claimed=true for the first caller and claimed=false for any
    duplicate within the window. ON CONFLICT DO NOTHING plus checking whether a
    row came back is what makes this race-free — the database decides, not the
    application.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=DEDUPE_WINDOW_MINUTES)

    async with pool.acquire() as conn:
        # Housekeeping: expired claims would otherwise grow without bound and
        # block a genuine repeat enquiry months later.
        await conn.execute("DELETE FROM dedupe_claims WHERE claimed_at < $1", cutoff)

        row = await conn.fetchrow(
            """
            INSERT INTO dedupe_claims (dedupe_key, workflow)
            VALUES ($1, $2)
            ON CONFLICT (dedupe_key) DO NOTHING
            RETURNING dedupe_key
            """,
            req.dedupe_key,
            req.workflow,
        )

    return {"claimed": row is not None, "dedupe_key": req.dedupe_key}


@app.post("/api/leads", status_code=201, dependencies=[Depends(require_api_key)])
async def create_lead(lead: LeadIn):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO leads (email, name, message, source, score, tier, reasons,
                               ai_intent, ai_urgency, ai_summary, ai_status, received_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12)
            RETURNING id, created_at
            """,
            lead.email,
            lead.name,
            lead.message,
            lead.source,
            lead.score,
            lead.tier,
            __import__("json").dumps(lead.reasons),
            lead.ai_intent,
            lead.ai_urgency,
            lead.ai_summary,
            lead.ai_status,
            lead.received_at or datetime.now(timezone.utc),
        )
    return {"id": row["id"], "created_at": row["created_at"].isoformat()}


@app.post("/api/failures", status_code=201, dependencies=[Depends(require_api_key)])
async def record_failure(f: FailureIn):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO failures (workflow, node, error, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id
            """,
            f.workflow,
            f.node,
            f.error,
            __import__("json").dumps(f.payload or {}),
        )
    return {"id": row["id"]}


@app.get("/api/stats")
async def stats(hours: int = 24):
    """Everything the dashboard needs in one round trip."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with pool.acquire() as conn:
        totals = await conn.fetchrow(
            """
            SELECT
                count(*)                                    AS total,
                count(*) FILTER (WHERE tier = 'hot')        AS hot,
                count(*) FILTER (WHERE tier = 'warm')       AS warm,
                count(*) FILTER (WHERE tier = 'cold')       AS cold,
                coalesce(round(avg(score))::int, 0)         AS avg_score
            FROM leads WHERE received_at >= $1
            """,
            since,
        )
        ai_health = await conn.fetchrow(
            """
            SELECT count(*) FILTER (WHERE ai_status = 'ok')                   AS ai_ok,
                   count(*) FILTER (WHERE ai_status IS NOT NULL
                                      AND ai_status <> 'ok')                  AS ai_failed
            FROM leads WHERE received_at >= $1
            """,
            since,
        )
        fail_count = await conn.fetchval(
            "SELECT count(*) FROM failures WHERE occurred_at >= $1 AND NOT resolved",
            since,
        )
        last_lead = await conn.fetchval("SELECT max(received_at) FROM leads")
        by_source = await conn.fetch(
            """
            SELECT source, count(*) AS n, coalesce(round(avg(score))::int, 0) AS avg_score
            FROM leads WHERE received_at >= $1
            GROUP BY source ORDER BY n DESC LIMIT 8
            """,
            since,
        )
        timeline = await conn.fetch(
            """
            SELECT date_trunc('hour', received_at) AS hour,
                   count(*) AS n,
                   count(*) FILTER (WHERE tier = 'hot') AS hot
            FROM leads WHERE received_at >= $1
            GROUP BY hour ORDER BY hour
            """,
            since,
        )

    # Staleness is the signal that matters most. A workflow that stopped firing
    # looks exactly like a quiet day unless you measure time since last lead.
    minutes_since = None
    if last_lead:
        minutes_since = int(
            (datetime.now(timezone.utc) - last_lead).total_seconds() / 60
        )

    return {
        "window_hours": hours,
        "totals": dict(totals),
        "ai": dict(ai_health),
        "open_failures": fail_count,
        "minutes_since_last_lead": minutes_since,
        "by_source": [dict(r) for r in by_source],
        "timeline": [
            {"hour": r["hour"].isoformat(), "n": r["n"], "hot": r["hot"]}
            for r in timeline
        ],
    }


@app.get("/api/leads")
async def list_leads(limit: int = 50, tier: Optional[str] = None):
    query = "SELECT * FROM leads"
    args = []
    if tier in ("hot", "warm", "cold"):
        query += " WHERE tier = $1"
        args.append(tier)
    query += f" ORDER BY received_at DESC LIMIT ${len(args) + 1}"
    args.append(min(limit, 200))

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)

    return [
        {
            **dict(r),
            "reasons": __import__("json").loads(r["reasons"]),
            "received_at": r["received_at"].isoformat(),
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@app.get("/api/failures")
async def list_failures(limit: int = 25):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM failures ORDER BY occurred_at DESC LIMIT $1",
            min(limit, 100),
        )
    return [
        {
            **dict(r),
            "payload": __import__("json").loads(r["payload"] or "{}"),
            "occurred_at": r["occurred_at"].isoformat(),
        }
        for r in rows
    ]


@app.get("/health")
async def health():
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "database": "reachable"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"database unreachable: {e}")


# Dashboard is served last so the API routes above take precedence.
DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")
if os.path.isdir(DASHBOARD_DIR):
    app.mount(
        "/static", StaticFiles(directory=DASHBOARD_DIR), name="static"
    )

    @app.get("/")
    async def dashboard(_: Request):
        return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))
