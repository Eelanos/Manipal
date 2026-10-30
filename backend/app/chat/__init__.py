"""
Manipal conversational analytics ("Ask Manipal").

Design in one paragraph
-----------------------
The LLM never sees raw data and never writes code or SQL. It does exactly two
jobs: (1) turn a question into a *structured query plan* (measures, groupings,
filters, period) that is validated against a semantic registry, and (2) write
prose about numbers that OUR code computed. Every figure on screen comes from
the same DataStore, filters and metric definitions the dashboards use, so chat
answers can never disagree with the dashboards.

Modules
-------
settings   - env-driven configuration (.env), nothing else reads os.environ
semantic   - declarative registry of tables, dimensions and measures
catalog    - introspects the live DataStore (value lists, date ranges, FY calendar)
timeparse  - turns symbolic periods into dates, relative to AS_OF_DATE (never now())
spec       - the plan schema the LLM must fill in (built from the registry)
resolver   - maps what the user typed ("pune", "gloves") to real data values
engine     - deterministic pandas executor for a validated query
present    - turns results into the dashboards' own Chart / Table / Kpi shapes
facts      - derives verified facts + signals from a result for the narrator
narrative  - placeholder substitution, numeric verification, safe fallback text
prompts    - planner / narrator prompts, generated from the registry and live catalog
llm        - the only module that talks to OpenAI
util       - TTL cache and rate limiter
service    - orchestration (plan -> validate -> compute -> present -> narrate) + caching
router     - FastAPI endpoints (SSE streaming, health, suggestions)
"""
