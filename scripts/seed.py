#!/usr/bin/env python3
"""Seed the tracker with sample leads so the dashboard has something to show.

Runs the same scoring rules as the workflow's Code node, so the demo data is
consistent with what the live pipeline would produce rather than invented.
"""

import json
import os
import random
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API = os.getenv("TRACKER_URL", "http://localhost:8000")
KEY = os.getenv("TRACKER_API_KEY", "dev-key-change-me")

FREE_EMAIL = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "aol.com", "icloud.com", "proton.me", "protonmail.com",
}
BUYING_SIGNALS = [
    "quote", "pricing", "price", "cost", "budget", "demo",
    "urgent", "asap", "timeline", "contract", "proposal",
]

SAMPLES = [
    ("Sara Ahmed", "sara@acme-industrial.com", "website-form",
     "We need a quote for 200 units. Budget is approved and the timeline is urgent."),
    ("Bilal Khan", "bilal.khan@northwind-logistics.co", "website-form",
     "Looking for pricing on your enterprise plan. Can we book a demo this week?"),
    ("Tom Reeves", "tomreeves88@gmail.com", "facebook-ad",
     "hi"),
    ("Ayesha Malik", "a.malik@meridian-health.org", "referral",
     "Our procurement team is evaluating vendors. Please send a proposal including "
     "implementation timeline and total cost of ownership for a 50 seat deployment."),
    ("Dan Whitfield", "dan@bluepeak.io", "website-form",
     "What does this cost for a small team?"),
    ("Growth Team", "outreach@seo-backlinks-pro.biz", "website-form",
     "We offer premium guest post and backlink opportunities for your site."),
    ("Nadia Rahman", "nadia@quantum-textiles.com", "linkedin",
     "Interested in a demo. We're replacing our current supplier and need a "
     "contract in place before end of quarter."),
    ("Ali Raza", "aliraza2010@yahoo.com", "facebook-ad",
     "is this available in pakistan"),
    ("Hina Sheikh", "h.sheikh@vertex-manufacturing.com", "referral",
     "Following up on our call. Please share the proposal and pricing breakdown."),
    ("Omar Farooq", "omar@gmail.com", "website-form",
     "I'd like to know more about what you offer and whether it fits our use case."),
    ("Zara Iqbal", "zara@apex-consulting.net", "linkedin",
     "Need a quote urgently. Budget approved for this quarter."),
    ("Junaid Aslam", "junaid@swiftcargo.pk", "website-form",
     "Can you handle 500 shipments per month? What's the pricing structure?"),
]


def score_lead(email: str, name: str, message: str):
    """Mirror of the workflow's scoring rules."""
    domain = email.split("@")[-1]
    text = f"{message} {name}".lower()

    score = 30
    reasons = []

    if domain and domain not in FREE_EMAIL:
        score += 25
        reasons.append("business email domain")

    hits = [w for w in BUYING_SIGNALS if w in text]
    if hits:
        score += min(len(hits) * 8, 24)
        reasons.append(f"buying signals: {', '.join(hits)}")

    if len(message) > 200:
        score += 8
        reasons.append("detailed message")
    elif len(message) < 20:
        score -= 15
        reasons.append("very short message")

    if any(w in text for w in ("seo", "backlink", "guest post", "crypto")):
        score -= 40
        reasons.append("matches common spam pattern")

    score = max(0, min(100, score))
    tier = "hot" if score >= 72 else "warm" if score >= 42 else "cold"
    return score, tier, reasons


def post(path: str, body: dict):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-api-key": KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def main():
    random.seed(7)  # reproducible demo data
    now = datetime.now(timezone.utc)
    created = 0

    for i in range(28):
        name, email, source, message = random.choice(SAMPLES)
        score, tier, reasons = score_lead(email, name, message)

        # Spread across the last 20 hours so the timeline chart has shape.
        received = now - timedelta(
            hours=random.uniform(0, 20), minutes=random.uniform(0, 59)
        )

        status, body = post(
            "/api/leads",
            {
                "email": email,
                "name": name,
                "message": message,
                "source": source,
                "score": score,
                "tier": tier,
                "reasons": reasons,
                "received_at": received.isoformat(),
            },
        )
        if status == 201:
            created += 1
        else:
            print(f"  lead {i} failed: {status} {body}")

    print(f"created {created} leads")

    # One resolved-looking failure so the failures panel is not empty in the
    # demo. A dashboard that only ever shows the happy path proves nothing.
    post(
        "/api/failures",
        {
            "workflow": "lead-intake",
            "node": "Store Lead",
            "error": "connect ETIMEDOUT — tracker unreachable during deploy",
            "payload": {"email": "demo@example.com"},
        },
    )
    print("created 1 sample failure")


if __name__ == "__main__":
    main()
