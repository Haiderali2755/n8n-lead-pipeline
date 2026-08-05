# Lead Intake — Zapier

Zapier has no blueprint export, so the Zap is written out here instead of
shipped as a file. Rebuilding it from this page takes about ten minutes.

Three steps: catch the webhook, score in JavaScript, POST to the tracker.

## 1. Trigger — Webhooks by Zapier → Catch Hook

Leave **Pick off a Child Key** empty so the whole payload comes through.

Zapier generates the URL. Send it one sample request before continuing, or
there are no fields to map in the later steps:

```bash
curl -X POST https://hooks.zapier.com/hooks/catch/YOUR/HOOK/ \
  -H 'Content-Type: application/json' \
  -d '{"name":"Sara Ahmed","email":"sara@acme-industrial.com",
       "message":"We need a quote for 200 units, budget approved, timeline is urgent.",
       "source":"website-form"}'
```

## 2. Action — Code by Zapier → Run JavaScript

**Input Data** maps three fields from step 1:

| Key | Value |
|---|---|
| `email` | `1. Email` |
| `message` | `1. Message` |
| `name` | `1. Name` |

Only what is listed here reaches the code. `inputData.source` is undefined
unless it is mapped, which is a quiet way to lose a field.

```javascript
const msg = (inputData.message || '').toLowerCase();
const email = inputData.email || '';

let score = 30;
const reasons = [];

if (msg.includes('budget')) { score += 20; reasons.push('budget mentioned'); }
if (msg.includes('urgent')) { score += 20; reasons.push('urgency signal'); }
if (!email.includes('gmail.com') && !email.includes('yahoo.com')) {
  score += 15;
  reasons.push('business email');
}

const tier = score >= 60 ? 'hot' : score >= 40 ? 'warm' : 'cold';

return { score, tier, reasons: reasons.length ? reasons : ['no signals'] };
```

Same rules as the n8n workflow: base 30, +20 for a budget signal, +20 for
urgency, +15 for a non-consumer email domain.

## 3. Action — Webhooks by Zapier → POST

| Field | Value |
|---|---|
| URL | `YOUR_TRACKER_URL/api/leads` |
| Payload Type | `json` |
| Wrap Request In Array | No |
| Header | `X-API-Key: YOUR_TRACKER_API_KEY` |

Data:

| Key | Value |
|---|---|
| `name` | `1. Name` |
| `email` | `1. Email` |
| `message` | `1. Message` |
| `source` | `zapier` |
| `score` | `2. Score` |
| `tier` | `2. Tier` |

## The array that does not survive

`reasons` is missing from that table on purpose.

The code returns it as a real array, and Zapier's own test screen displays it
as one — numbered rows, `1 budget mentioned`, `2 urgency signal`. But the POST
step flattens every Data value to a string on the way out (`unflatten: true` in
the request it builds), so the tracker received `"budget mentioned, urgency
signal, business email"` where it expected a list, and answered:

```
Input should be a valid list
```

Joining the array in JavaScript produces the same string, so the fix is not in
the code. Getting a JSON array out of Zapier means sending the whole body as
raw JSON through **Custom Request** instead of using the Data fields, which
gives up the field mapping the step exists for.

The field was dropped. `score` and `tier` are what the dashboard reads, and
both are numbers and strings that survive the flattening intact.

## Trial note

This Zap uses Webhooks and multi-step, both Zapier paid features. It was built
and published during the 14-day Pro trial. On the free plan it stops running —
the build is real, the Zap is not permanently live.
