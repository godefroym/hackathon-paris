# Facts API

## Send data to the API with HTTPie

Endpoint:

- `http://localhost:8000/api/facts`

### 1) Full payload (matching your schema)

```bash
http POST http://localhost:8000/api/facts \
  claim:='{"text":"Les affirmations sur lintelligence et le QI moyen ne peuvent être vérifiées sans données supplémentaires. Elles relèvent davantage de lopinion personnelle."}' \
  analysis:='{"summary":"La population française est denviron 67,4 millions, donc 66 millions est une approximation raisonnable. Le chiffre est légèrement inférieur à la réalité mais reste proche.","sources":[{"organization":"INSEE","url":"https://www.insee.fr/fr/statistiques/2381474"}]}' \
  overall_verdict="partially_accurate"
```

### 2) Minimal valid payload (sources optional)

```bash
http POST http://localhost:8000/api/facts \
  claim:='{"text":"Un exemple de claim sans sources."}' \
  analysis:='{"summary":"Résumé sans sources."}' \
  overall_verdict="unverified"
```

### 3) Invalid payload example (to test validation)

```bash
http POST http://localhost:8000/api/facts \
  claim:='{}' \
  analysis:='{}'
```

You should get a `422 Unprocessable Entity` with validation errors.
