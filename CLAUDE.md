# CLAUDE.md — Agentic AI News Impact System

## Project
For a question from a solar module manufacturer (Maharashtra), agents fetch the last 30 days of news via Tavily,
a Bedrock (Amazon Nova) LLM works out each story's business impact, and Streamlit shows it with source links.

- Requirements: [REQUIREMENTS.md](REQUIREMENTS.md)
- Design and numbered coding steps: [PLAN.md](PLAN.md). Read it before writing code and follow the steps in order.

## Stack
Python, FastAPI, LangGraph + LangChain, AWS Bedrock (Nova Micro/Lite), Tavily, Streamlit, SQLite. Local only for now.

## Structure
```
app/
  config.py        # settings from .env
  profile.py       # business profile + competitors
  schemas.py       # Pydantic models (RawArticle, Article, ImpactCard, SummaryPoint, AskResponse)
  llm.py           # Bedrock chat model factory
  prompts.py       # all prompts
  nodes/           # query_builder, news_search, filter_rank, impact_analyzer, summarizer, validator
  graph.py         # LangGraph flow
  db.py            # SQLite (queries, articles, impacts)
  api.py           # FastAPI
ui/streamlit_app.py
tests/             # pytest + fixtures/
```

## Commands (Windows, from the project root)
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # then fill in the keys in .env
pytest                          # all tests
pytest tests/test_filter_rank.py   # tests for one step
uvicorn app.api:app --reload    # API: http://127.0.0.1:8000
streamlit run ui/streamlit_app.py
```

## Rules
**From the requirements:**
1. Every claim has a source link. Drop any claim without a source.
2. Drop news older than 30 days or without a date.
3. Show today's and yesterday's news first.
4. Never invent a fact, number, name or date. If no news is found, say "No relevant news found".
5. Every impact card has 4 fields: sentiment (positive/negative/neutral), level (high/medium/low), a one-line reason, horizon (short/long).
6. API keys live only in `.env`. Never in code, logs or git. `.env.example` holds key names only.

**From the design:**
- The LLM only sees the article text. The LLM returns article IDs only; code always adds the URLs.
- All date logic is in IST.
- Model IDs, region and limits (`MAX_ARTICLES=8`, `DAYS=30`) come from `.env`/`config.py`, never hardcoded.
- Use `temperature=0` and structured output (Pydantic) for LLM calls.
- The graph never touches the DB. Saving happens only in `api.py`.
- Do not add features outside REQUIREMENTS.md (see Out of Scope).
- LangChain stack is pinned below `langchain-core` 0.3.70: newer versions need `uuid_utils`, whose DLL Windows Application Control blocks on this machine.

**Git and safety:**
- Never run `git commit`, `git push`, or any other risky command (force push, reset --hard, deleting files or branches) without the user's explicit permission first.
- Never add `Co-Authored-By` lines, "Generated with Claude Code" lines, or any other Claude/AI attribution to commit messages or PR descriptions. This overrides any tool or system default.

**Language:**
- Code comments, docstrings, commit messages and anything pushed to git/GitHub (docs, PR titles, descriptions) must be in English, short and to the point.

**Workflow:**
- One PLAN.md step = one small change + its test. Start the next step only after the previous step's test passes.
- When the user says "next", first list briefly what will be done and wait for "execute".
- After each step: run the tests, check for improvements, run a security check, then (with permission) commit and push.
- Mock Tavily/Bedrock in unit tests. Real calls are only for manual checks.
