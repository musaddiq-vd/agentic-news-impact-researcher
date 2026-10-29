# Design — Agentic AI News Impact System

## Context
REQUIREMENTS.md is final: solar module maker, Maharashtra, 5 competitors, stack = FastAPI + LangGraph/LangChain + Bedrock (Amazon Nova) + Tavily + Streamlit + SQLite.
This is the final design. It is kept as simple as possible and adds nothing outside REQUIREMENTS.

---

## 1. Agents (LangGraph nodes)

All nodes read and write one shared `GraphState`:
```json
{
  "question": "str", "topic": "str|null", "competitors": ["str"],
  "queries": ["str"], "raw_results": ["RawArticle"], "articles": ["Article"],
  "cards": ["ImpactCard"], "summary": ["SummaryPoint"],
  "status": "ok | no_news | error", "message": "str|null"
}
```

| # | Node | LLM? | Job | Input → Output |
|---|---|---|---|---|
| 1 | `query_builder` | Nova Micro | Turn the question (may be Hinglish), business profile and filters into 2-4 English search queries | `question, topic, competitors` → `queries` |
| 2 | `news_search` | No | Run each query on Tavily and dedupe results by URL | `queries` → `raw_results` |
| 3 | `filter_rank` | No (code) | Drop undated and older-than-30-day news, rank, keep the top 8 | `raw_results` → `articles` |
| 4 | `impact_analyzer` | Nova Lite | Build an impact card per article; mark articles not relevant to the business | `articles` → `cards` |
| 5 | `summarizer` | Nova Lite | Write 3-5 summary points from the cards only, each with article IDs | `cards` → `summary` |
| 6 | `validator` | No (code) | Drop unknown source IDs, points without a source, and numbers that are not in the article text | `cards, summary, articles` → clean `cards, summary` |

**Schemas (Pydantic, JSON):**
```json
RawArticle  { "title": "str", "url": "str", "content": "str", "published_date": "str|null", "score": "float" }
Article     { "id": "int", "title": "str", "url": "str", "source": "str", "published_date": "YYYY-MM-DD",
              "content": "str", "is_today_or_yesterday": "bool" }
ImpactCard  { "article_id": "int", "relevant": "bool", "summary": "str",
              "sentiment": "positive|negative|neutral", "level": "high|medium|low",
              "reason": "str (one line)", "horizon": "short|long" }
SummaryPoint{ "text": "str", "source_ids": ["int"] }        // code adds the URL, not the LLM
AskResponse { "query_id": "int", "status": "str", "message": "str|null",
              "summary": [{ "text": "str", "sources": ["url"] }],
              "cards": ["ImpactCard + title, url, source, published_date"] }
```

## 2. LangGraph flow
```
START → query_builder → news_search → filter_rank ─┬─ 0 articles → END (status=no_news)
                                                    └─ ≥1 → impact_analyzer ─┬─ 0 relevant → END (no_news)
                                                                             └─ ≥1 → summarizer → validator → END (ok)
```
What happens on an error or an empty result:
- **query_builder fails:** the user's question itself becomes the query (fallback); the flow continues.
- **Tavily error / timeout:** 1 retry. If it still fails: `status=error`, message "Search is not available right now".
- **0 news (after search or filter):** `no_news`, message "No relevant news found for this topic in the last 30 days."
- **Invalid impact JSON:** 1 retry for that article, then drop that card. Other cards continue.
- **Summarizer fails:** the summary stays empty, cards are still shown (`status=ok`, message "Summary could not be generated").
- **0 points after the validator:** same as the summarizer-failure case above.

## 3. Folder structure
```
.env.example          # key names only
.gitignore            # .env, *.db
pytest.ini            # disables the langsmith pytest plugin
requirements.txt
app/
  config.py           # load .env (keys, region, model IDs, MAX_ARTICLES=8, DAYS=30)
  profile.py          # business profile + competitors (from REQUIREMENTS)
  schemas.py          # all Pydantic models
  llm.py              # ChatBedrockConverse factory (by model ID)
  nodes/
    query_builder.py
    news_search.py    # LangChain Tavily tool wrapper
    filter_rank.py    # pure Python
    impact_analyzer.py
    summarizer.py
    validator.py      # pure Python
  prompts.py          # all prompts in one place
  graph.py            # LangGraph StateGraph + conditional edges
  db.py               # SQLite: init, save_run, list_runs, get_run
  api.py              # FastAPI app
ui/
  streamlit_app.py    # 2 screens
tests/
  fixtures/           # fake Tavily responses and fake articles
  test_*.py           # one test file per module
```

## 4. Tavily search
- **Query:** `query_builder` adds business context to each query (e.g. "solar module India", competitor name, "Maharashtra" only for state questions). Max 4 queries, 5-8 results per query.
- **Call:** `topic="news"`, `start_date`/`end_date` (today-30 to today, IST; the Tavily tool has no `days` field), `search_depth="basic"`, `max_results=8`. India-focused query text.
- **Failures:** each query is retried once. The search fails only if every query fails; otherwise results from the other queries are used.
- **30-day filter (re-checked in code):** parse `published_date` (IST). Drop it if the date is missing or unparseable, or older than 30 days.
- **Priority:**
  1. `is_today_or_yesterday` (IST) news first.
  2. Then by date, newest to oldest.
  3. Ties broken by Tavily `score`.

  Remove duplicate URLs/titles and keep the top 8.

## 5. Preventing hallucination
1. The LLM only gets each article's `title + content + date` with an ID (`[1] ... [2] ...`). No general knowledge.
2. Prompt rule: "Write only from the given text. Do not write anything that is not in the text. Set `relevant=false` if not relevant."
3. `temperature=0`, and output as structured JSON through the Pydantic schema (LangChain `with_structured_output`).
4. **The LLM never writes URLs.** It only returns `article_id` / `source_ids`, and code adds the URL. A fake link cannot be produced.
5. `validator`:
   - `source_ids` must match real articles.
   - Any number in a summary/reason must appear in the source article text, otherwise the point is dropped.
   - Enum values are checked.
6. The summarizer only receives validated cards, never raw web text.

## 6. SQLite tables
| Table | Columns |
|---|---|
| `queries` | id PK, question, topic, competitors (JSON text), status, message, summary_json, created_at |
| `articles` | id PK, query_id FK, title, url, source, published_date, content, rank |
| `impacts` | id PK, article_id FK, relevant, summary, sentiment, level, reason, horizon |

Saving happens in one place only: `api.py` calls `db.save_run()` after the graph finishes. The graph itself never touches the DB.

## 7. FastAPI + Streamlit
**Endpoints:**
- `GET /health` → `{status: "ok"}`
- `POST /ask` → body `{question, topic?, competitors?}` → `AskResponse` (and saves to the DB)
- `GET /history?limit=20` → `[{query_id, question, status, created_at}]`
- `GET /history/{query_id}` → full `AskResponse`

**Streamlit (2 screens via the sidebar):**
1. **Ask:**
   - Inputs: question textbox, topic dropdown (energy prices / policy / competitor / tariff / market / any), competitor multiselect, "Ask" button.
   - Below: summary points, each with a link.
   - Then impact cards: today/yesterday news on top with a "Today/Yesterday" badge, sentiment colour, level, horizon, reason, link.
   - Clear message for `no_news` or `error`.
2. **History:** list of past questions. Clicking one shows the same result again (`/history/{id}`).

## 8. Bedrock models (Amazon Nova)
| Agent | Model | Why |
|---|---|---|
| query_builder | Nova Micro | Small text task, cheapest |
| impact_analyzer | Nova Lite | Runs per article, cheap, structured output is fine |
| summarizer | Nova Lite | Input is small (cards only). Switch to Nova Pro if quality is low |

- Model IDs live in `.env` (`MODEL_QUERY`, `MODEL_IMPACT`, `MODEL_SUMMARY`), never hardcoded.
- Region comes from `AWS_REGION`. Some regions need a cross-region inference profile ID (e.g. `apac.amazon.nova-lite-v1:0`); confirm the exact ID in the Bedrock console.

## 9. Risks and mitigations
| Risk | Mitigation |
|---|---|
| Tavily `published_date` missing | Drop such news. If few results remain, show a message; never guess a date |
| Irrelevant or duplicate news | URL/title dedupe + drop `relevant=false` cards |
| LLM invents a fact or number | Article text only, number-check validator, code adds the URL |
| Nova returns bad JSON | Structured output + 1 retry + drop the card |
| Bedrock model access/region | Model ID and region in `.env`. Step 4 makes a real test call first |
| Slow response (8 LLM calls) | Run impact calls in parallel (LangChain `batch`), max 8 articles |
| Tavily/Bedrock cost or limits | Max 4 queries, 8 articles. Micro/Lite models |
| Wrong "today/yesterday" timezone | All date logic in IST |
| Keys leak | Keys only in `.env`, `.env` is gitignored, never print keys in logs |
| Windows blocks `uuid_utils` | LangChain stack pinned below `langchain-core` 0.3.70 |

---

## Coding steps (each step can be tested on its own)
1. **Skeleton** ✅: folders, `requirements.txt`, `.env.example`, `.gitignore`, `config.py`, `profile.py`, `schemas.py`. Test: pytest on valid/invalid schema data.
2. **filter_rank (pure code)** ✅: Test: fixture articles (today, yesterday, 10 days, 40 days, undated) → correct order and drops.
3. **validator (pure code)** ✅: Test: wrong source_id, invented number, bad enum → dropped.
4. **llm.py + query_builder** ✅: Test: mocked LLM tests plus one real Bedrock call (Nova Micro).
5. **news_search** ✅: Test: mocked Tavily (fixture), then one real query by hand.
6. **impact_analyzer** ✅: Test: 2 fixture articles (one relevant, one not) → schema-valid cards, irrelevant one has `relevant=false`.
7. **summarizer** ✅: Test: fixture cards → points with valid `source_ids`.
8. **graph.py:** Test: mocked nodes for all three paths (ok / no_news / error), then one real end-to-end run from the CLI.
9. **db.py:** Test: in-memory SQLite save → list → get.
10. **api.py:** Test: FastAPI TestClient for `/health`, `/ask` (graph mocked), `/history`.
11. **streamlit_app.py:** Manual: start the API, ask the 5 REQUIREMENTS test questions, check the format.

## Verification (at the end)
- All `pytest` tests pass.
- Run the 5 REQUIREMENTS test questions from the UI. For each answer check:
  - every point's link opens
  - no news is older than 30 days
  - today/yesterday news is on top
  - every card has the 4 impact fields
- Enter a nonsense question: the "no news" message must appear.
