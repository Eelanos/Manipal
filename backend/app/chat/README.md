# Ask Manipal - conversational layer

A chat panel on the dashboards. The user asks a question; the answer comes back as a
written summary plus KPI cards, charts and a table, all computed from the same parquet
data the dashboards use.

## Run it

```bash
cd backend
pip install -r requirements.txt            # adds the openai package
cp .env.example .env                        # then put your key in .env:  OPENAI_API_KEY=sk-...
uvicorn app.main:app --reload               # http://127.0.0.1:8000
# in another terminal
cd frontend && npm run dev                  # http://localhost:3000  -> "Ask Manipal" tab on the right edge
```

Check it: `GET /api/chat/health` (add `?deep=true` to ping each configured model), then run
`python tests/live_smoke.py` once to see 13 real questions go through the real models.

## How an answer is made

| Step | What | Where |
|------|------|-------|
| 1 Plan | Model turns the question into a structured plan. It can only pick measure/dimension ids from the registry. | `prompts.py`, `spec.py`, `llm.py` |
| 2 Validate | Plan is checked; names ("pune", "cardiolgy") are matched to real values; periods become exact dates relative to `AS_OF_DATE`. Bad plans go back to the model once with the exact error. | `resolver.py`, `timeparse.py` |
| 3 Compute | pandas computes every figure from the DataStore. | `engine.py` |
| 4 Present | KPIs, charts, table built by rules, in the dashboards' own shapes. | `present.py` |
| 5 Narrate | Model writes prose using `{fN}` placeholders; we insert the exact figures and reject any typed number. | `facts.py`, `narrative.py` |

The model never writes code or SQL and never types a number. If the narrator fails, a
deterministic summary is shown instead - still correct, just plainer.

## Changing what it knows

Everything it can talk about lives in `semantic.py`. Add a `Measure` or `Dimension` entry and
it appears in the prompt, the schema, the suggestions and the tests automatically.
Run `pytest` - `test_chat_registry.py` validates the registry against the live data and
`test_chat_parity.py` proves the chat figures equal the dashboards'.

## Configuration (env / `.env`)

See `backend/.env.example`. Models, timeouts, rate limit, cache size and limits are all
environment variables; nothing is hardcoded in the code paths.

## Known data caveats (not bugs in the chat)

* Two "in transit" figures exist: inventory-side (stock) and purchase-order-side. They are
  separate measures with different definitions.
* Molecule names are placeholders (`Molecule_1` ...).
* Stock exists only as month-end snapshots. A stock question for a period uses the latest
  snapshot inside it; stock is never summed across months.
* Cost and revenue columns are synthetic.
