# The same pipeline in n8n, Make.com, and Zapier

One webhook, one scoring rule, one POST to the same FastAPI tracker — built
three times so the differences show up in something other than a feature table.

Everything below happened while building. None of it came from documentation.

## The pipeline

```
webhook  →  score (base 30, +20 budget, +20 urgent, +15 business email)  →  POST /api/leads
```

Same tracker, same database, same dashboard. Only the middle changes.

## Scoring the same rule three ways

**n8n** — a Code node, plain JavaScript:

```javascript
let score = 30;
if (msg.includes('budget')) score += 20;
```

**Zapier** — Code by Zapier, also plain JavaScript. Near-identical to n8n,
except the inputs have to be declared field by field in an Input Data table
first. A field that is not mapped is `undefined` inside the code, with no
warning.

**Make.com** — no code step on the free plan. The rule becomes a formula, and
because Make has no way to store an intermediate value inside one module, the
whole expression is written twice — once for the score, once for the tier that
depends on it:

```
{{30 + if(contains(lower(2.message); "budget"); 20; 0)
     + if(contains(lower(2.message); "urgent"); 20; 0)
     + if(contains(2.email; "gmail.com"); 0; 15)}}
```

```
{{if(30 + if(contains(lower(2.message); "budget"); 20; 0)
        + if(contains(lower(2.message); "urgent"); 20; 0)
        + if(contains(2.email; "gmail.com"); 0; 15) >= 60; "hot"; "cold")}}
```

Two copies of one rule. Change a threshold in one and forget the other, and the
score and the tier disagree — with nothing to catch it.

A Tools → Set Variable module fixes this, at the cost of a fourth module in a
three-module scenario.

## What broke

**Zapier flattens arrays.** The code returns `reasons` as a real array and
Zapier's test screen renders it as one — numbered rows and all. The POST step
still sends it as a joined string, because Data values are flattened on the way
out. The tracker replied `Input should be a valid list`. The fix is not in the
JavaScript; getting a JSON array out means abandoning the Data fields for a raw
Custom Request. The field was dropped instead.

**Make module numbers are not positions.** The webhook was module 2, not 1,
because module 1 had been deleted earlier. Every `{{1.name}}` reference failed
with *references non-existing module*. The numbers are identity, not order.

**Neither tool can reach localhost.** n8n ran in the same Docker network as the
tracker and resolved it by service name. Make and Zapier are hosted, so the
tracker had to be exposed through an ngrok tunnel before either could post to
it. Obvious once stated, and the first thing that stops a cloud tool cold.

## Measured

Same three leads through each tool:

| Lead | Expected | n8n | Make | Zapier |
|---|---|---|---|---|
| budget + urgent + business email | 85 hot | 85 hot | 85 hot | 85 hot |
| no signals + gmail | 30 cold | 30 cold | 30 cold | — |

Make's low-scoring lead came back 30/cold, matching. The Zapier run used the
high-scoring lead only.

## Where each one fits

**n8n** is the one to reach for when the logic is real: code without a plan
tier, self-hosted next to the service it talks to, no per-task billing. The
cost is that somebody has to run it.

**Make.com** has the clearest canvas of the three and the formula engine is
genuinely capable — until a value needs to be reused, at which point the lack
of variables inside a module turns one rule into two copies of itself.

**Zapier** has the widest app catalogue and the least friction to a first
working run. Webhooks and multi-step Zaps are paid, and the Data-field
flattening means anything structured has to leave through a raw request.

None of this makes one tool correct. It makes them different in ways that only
show up after the thing is built.
