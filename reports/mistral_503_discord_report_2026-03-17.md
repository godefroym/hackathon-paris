## Mistral Conversations/Web Search 503 report

Hi Mistral team,

We are seeing repeated `503` errors on the Conversations API when using the built-in `web_search` tool.

### Environment

- SDK: `mistralai 1.12.4`
- Python: `3.12` in Docker worker
- Workflow backend: Temporal worker
- Worker host timezone: Europe/Paris
- Main failing path:
  - `client.beta.conversations.start_async(model="mistral-medium-latest", inputs=query, tools=[{"type": "web_search"}])`

### Observed errors

We consistently see:

```text
API error occurred: Status 503. Body: {"object":"Error","message":"Failed to create conversation response.","type":"invalid_request_error","code":3000}
```

We also sometimes see:

```text
Status 503 Content-Type "text/plain; charset=UTF-8"
upstream connect error or disconnect/reset before headers
reset reason: overflow
```

### Concrete queries that triggered the issue

- `Il y a 3 millions d'êtres humains sur Terre`
- `source officielle Il y a 3 millions d'êtres humains sur Terre`
- `Le sida est une bactérie`

### Concrete timestamps observed

- `2026-03-17T14:36:07Z`
- `2026-03-17T14:50:23Z`

Those correspond to multiple failing workflows in our logs.

### Minimal reproduction

```python
from mistralai import Mistral

client = Mistral(api_key="YOUR_KEY")

resp = await client.beta.conversations.start_async(
    model="mistral-medium-latest",
    inputs="Il y a 3 millions d'êtres humains sur Terre",
    tools=[{"type": "web_search"}],
)
print(resp)
```

### Expected result

- A normal Conversations/Web Search response
- Or a stable typed error if the request is unsupported or temporarily unavailable

### Actual result

- Intermittent `503` / `code 3000`
- Repeated failures on valid factual queries
- Downstream activity timeouts if we retry too aggressively

### Impact

- Our fact-check workflow cannot reliably fetch sources
- The workflow can remain running while retries/timeouts accumulate
- No fact-check banner can be posted for some clearly false claims

### Additional notes

- This does **not** look like a classic rate-limit case, because we are not getting `429`
- The failures occur on otherwise valid requests with a valid API key
- We checked your public status page and saw multiple `Completion API Degraded` incidents on `2026-03-17`, which may be related:
  - https://status.mistral.ai/
  - https://status.mistral.ai/incidents/page/1

If useful, we can provide:

- full Python stack traces
- exact workflow IDs
- exact request timestamps
- a smaller standalone repro script
