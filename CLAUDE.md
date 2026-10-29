# CLAUDE.md — Agentic AI News Impact System

## Project
Solar module manufacturer (Maharashtra) ke sawal par agents pichhle 30 din ki news Tavily se laate hain,
Bedrock (Amazon Nova) se har news ka business impact nikaalte hain, aur Streamlit par source links ke saath dikhate hain.

- Requirements: [REQUIREMENTS.md](REQUIREMENTS.md)
- Design + numbered coding steps: [PLAN.md](PLAN.md). Code likhne se pehle ise padho aur steps ke order me chalo.

## Stack
Python, FastAPI, LangGraph + LangChain, AWS Bedrock (Nova Micro/Lite), Tavily, Streamlit, SQLite. Abhi sirf local.

## Structure
```
app/
  config.py        # .env se settings
  profile.py       # business profile + competitors
  schemas.py       # Pydantic models (RawArticle, Article, ImpactCard, SummaryPoint, AskResponse)
  llm.py           # Bedrock chat model factory
  prompts.py       # saare prompts
  nodes/           # query_builder, news_search, filter_rank, impact_analyzer, summarizer, validator
  graph.py         # LangGraph flow
  db.py            # SQLite (queries, articles, impacts)
  api.py           # FastAPI
ui/streamlit_app.py
tests/             # pytest + fixtures/
```

## Commands (Windows, project root se)
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # phir .env me keys bharo
pytest                          # saare tests
pytest tests/test_filter_rank.py   # ek step ka test
uvicorn app.api:app --reload    # API: http://127.0.0.1:8000
streamlit run ui/streamlit_app.py
```

## Rules
**Requirements se:**
1. Har claim ke saath source link ho. Jis claim ka source nahi, wo hata do.
2. 30 din se purani ya bina date wali news drop karo.
3. Aaj/kal ki news sabse upar dikhao.
4. Koi fact, number, naam ya date khud se mat banao. News na mile to "koi relevant news nahi mili" likho.
5. Har impact card me ye 4 fields hon: sentiment (positive/negative/neutral), level (high/medium/low), ek-line reason, horizon (short/long).
6. API keys sirf `.env` me. Code, logs aur git me kabhi nahi. `.env.example` me sirf key names.

**Design se:**
- LLM ko sirf article ka text milega. LLM sirf article IDs dega, URL hamesha code jodega.
- Saari date logic IST (`Asia/Kolkata`) me hogi.
- Model IDs, region aur limits (`MAX_ARTICLES=8`, `DAYS=30`) `.env`/`config.py` se aayenge, hardcode nahi.
- LLM calls me `temperature=0` aur structured output (Pydantic) use karo.
- Graph DB ko nahi chhuega. Save sirf `api.py` me hoga.
- REQUIREMENTS.md ke bahar koi feature mat jodo (Out of Scope dekho).

**Git and safety:**
- Never run `git commit`, `git push`, or any other risky command (force push, reset --hard, deleting files or branches) without the user's explicit permission first.

**Language:**
- Code comments, docstrings, commit messages and anything pushed to git/GitHub (PR titles, descriptions) must be in English, short and to the point.

**Kaam karne ka tarika:**
- PLAN.md ka ek step = ek chhota change + uska test. Agla step tab shuru karo jab pichhle step ka test pass ho.
- Unit tests me Tavily/Bedrock mock karo. Asli calls sirf manual check ke liye.
