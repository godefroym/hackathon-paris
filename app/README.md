# hackathon-paris API quick checks

This project exposes a fact-check streaming endpoint:

- `POST /api/stream/fact-check`
- `GET /api/stream/fact-check/latest`
- Base URL: `http://localhost:8000`

Overlay routes for OBS:

- `http://localhost:8000/overlays/fact-check` -> new stacked persistent overlay (default)
- `http://localhost:8000/overlays/fact-check-2` -> same new stacked overlay
- `http://localhost:8000/overlays/fact-check-classic` -> previous single-card overlay

## HTTPie examples

### 1) Send a valid fact-check payload

```bash
http POST http://localhost:8000/api/stream/fact-check \
  claim:='{"text":"Les affirmations sur l’intelligence et le QI moyen ne peuvent être vérifiées sans données supplémentaires. Elles relèvent davantage de l’opinion personnelle."}' \
  analysis:='{"summary":"La population française est d’environ 67,4 millions, donc 66 millions est une approximation raisonnable. Le chiffre est légèrement inférieur à la réalité mais reste proche.","sources":[{"organization":"INSEE","url":"https://www.insee.fr/fr/statistiques/2381474"}]}' \
  overall_verdict="partially_accurate"
```

### 2) Trigger validation errors (422)

```bash
http POST http://localhost:8000/api/stream/fact-check \
  claim:='{}' \
  analysis:='{"summary":123,"sources":[{"organization":[],"url":"not-a-url"}]}' \
  overall_verdict:=123
```

### 3) Minimal payload template you can tweak

```bash
http POST http://localhost:8000/api/stream/fact-check \
  claim:='{"text":"<claim text>"}' \
  analysis:='{"summary":"<analysis summary>","sources":[{"organization":"<organization>","url":"https://example.com/source"}]}' \
  overall_verdict="partially_accurate"
```

## Notes

- The endpoint expects JSON and returns JSON.
- If OBS scene switching fails, the API responds with `502` and `code: "obs_switch_failed"`.
- By default, the OBS fact-check scene now stays active (`OBS_PERSIST_FACT_CHECK_SCENE=true`).
- Run the app first (for example via your usual local dev command) before running these checks.
