#!/usr/bin/env python3
"""Turn the live dashboard into the static demo page in docs/.

The live dashboard polls the tracker API. GitHub Pages serves static files
only, so this rewrites the fetches to read captured fixtures instead, and adds
a banner saying exactly that. Everything else — layout, charts, logic — is the
same file, so the demo cannot drift away from the real thing.

Run after scripts/capture_demo.py.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SRC = os.path.join(ROOT, "dashboard", "index.html")
OUT = os.path.join(ROOT, "docs", "index.html")

s = open(SRC).read()

# 1. Read fixtures instead of the API.
s = s.replace(
    """      fetch(`/api/stats?hours=${hours}`).then((r) => r.json()),
      fetch('/api/leads?limit=12').then((r) => r.json()),
      fetch('/api/failures?limit=10').then((r) => r.json()),""",
    """      fetch(`data/stats-${hours}.json`).then((r) => r.json()),
      fetch('data/leads.json').then((r) => r.json()),
      fetch('data/failures.json').then((r) => r.json()),""")

# 2. Rebase timestamps at render time. The fixtures are frozen, so without
#    this the page would read "3 weeks ago" a month from now.
s = s.replace(
    "const $ = (id) => document.getElementById(id);",
    """const $ = (id) => document.getElementById(id);

// Static snapshot: captured timestamps are fixed, so shift them all by one
// offset at render time. Real intervals between leads are preserved.
let TIME_SHIFT_MS = 0;
function computeShift(leads) {
  if (!leads.length) return;
  const newest = Math.max(...leads.map((l) => new Date(l.received_at).getTime()));
  TIME_SHIFT_MS = Date.now() - newest - 6 * 60 * 1000;
}
const shifted = (iso) => new Date(new Date(iso).getTime() + TIME_SHIFT_MS);""")

for old, new in [
    ("const when = new Date(r.received_at).toLocaleString(undefined,",
     "const when = shifted(r.received_at).toLocaleString(undefined,"),
    ("const when = new Date(r.occurred_at).toLocaleString(undefined,",
     "const when = shifted(r.occurred_at).toLocaleString(undefined,"),
    ("    const t = new Date(d.hour).toLocaleString(undefined,",
     "    const t = shifted(d.hour).toLocaleString(undefined,"),
    ("  const first = new Date(data[0].hour).toLocaleString(undefined,",
     "  const first = shifted(data[0].hour).toLocaleString(undefined,"),
    ("  const last = new Date(data[data.length - 1].hour).toLocaleString(undefined,",
     "  const last = shifted(data[data.length - 1].hour).toLocaleString(undefined,"),
]:
    s = s.replace(old, new)

s = s.replace("""    renderHealth(stats);""",
"""    computeShift(leads);
    if (leads.length) {
      const newest = shifted(leads[0].received_at).getTime();
      stats.minutes_since_last_lead = Math.max(0, Math.round((Date.now() - newest) / 60000));
    }
    renderHealth(stats);""")

# 3. Nothing to poll in a snapshot.
s = s.replace("""load();
// Polling rather than websockets: this is a monitor, not a live feed, and a
// 30s refresh is well inside the resolution anyone acts on.
setInterval(load, 30000);""",
"""load();
// No polling. The live dashboard refreshes every 30s against the API; a
// static snapshot has nothing to poll.""")

# 4. Say it is a snapshot. A demo that does not admit it is a demo is a lie
#    by omission.
s = s.replace("""  <div class="health" id="health">""",
"""  <div class="demo-note">
    <b>Static snapshot.</b> This is the real dashboard rendered from data
    captured off a running instance, so you can see the interface without
    installing anything. The live version polls the tracker API every 30
    seconds. Run it yourself with <code>docker compose up</code> —
    <a href="https://github.com/Haiderali2755/n8n-lead-pipeline">source</a>.
  </div>

  <div class="demo-note">
    <b>Three tools, one API.</b> The same pipeline was built in n8n, Make.com
    and Zapier, all posting to this tracker. The
    <a href="https://github.com/Haiderali2755/n8n-lead-pipeline/blob/main/COMPARISON.md">comparison</a>
    records where each one broke — Make rewriting one rule twice, Zapier
    flattening an array into a string on the way out.
  </div>

  <div class="health" id="health">""")

s = s.replace("""  .kpis { display: grid;""",
"""  .demo-note { background: var(--surface-2); border-radius: 10px; padding: 13px 16px;
               margin: 20px 0 0; font-size: 13px; color: var(--text-secondary);
               border-left: 3px solid var(--text-muted); }
  .demo-note b { color: var(--text-primary); font-weight: 640; }
  .demo-note code { background: var(--surface-3); padding: 1px 6px; border-radius: 4px;
                    font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }
  .demo-note a { color: inherit; }

  .kpis { display: grid;""")

s = s.replace("<title>Lead Pipeline — Monitor</title>",
              "<title>Lead Pipeline Monitor — Live Demo</title>")

# Fail loudly if the source changed shape, rather than shipping a broken page.
required = ["data/stats-", "TIME_SHIFT_MS", "Static snapshot", "AI enrichment",
            "Three tools, one API"]
missing = [r for r in required if r not in s]
if missing:
    sys.exit(f"transform failed, missing: {missing}\nDid dashboard/index.html change shape?")
if "setInterval(load" in s:
    sys.exit("transform failed: polling loop still present")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w").write(s)
print(f"wrote {OUT} ({len(s)} bytes)")
