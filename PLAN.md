# Design — Agentic AI News Impact System

## Context
REQUIREMENTS.md final hai: solar module maker, Maharashtra, 5 competitors, stack = FastAPI + LangGraph/LangChain + Bedrock (Amazon Nova) + Tavily + Streamlit + SQLite.
Ye final design hai. Sabse simple design rakha hai, REQUIREMENTS ke bahar ka kuch nahi joda.

---

## 1. Agents (LangGraph nodes)

Sab nodes ek shared `GraphState` padhte aur likhte hain:
```json
{
  "question": "str", "topic": "str|null", "competitors": ["str"],
  "queries": ["str"], "raw_results": ["RawArticle"], "articles": ["Article"],
  "cards": ["ImpactCard"], "summary": ["SummaryPoint"],
  "status": "ok | no_news | error", "message": "str|null"
}
```

| # | Node | LLM? | Kaam | Input → Output |
|---|---|---|---|---|
| 1 | `query_builder` | Nova Micro | Sawal (Hinglish ho sakta hai), business profile aur filter se 2-4 English search queries banana | `question, topic, competitors` → `queries` |
| 2 | `news_search` | Nahi | Har query Tavily par chalana aur URL ke hisaab se duplicates hatana | `queries` → `raw_results` |
| 3 | `filter_rank` | Nahi (code) | Bina date wali aur 30 din se purani news hatana, ranking karna, top 8 rakhna | `raw_results` → `articles` |
| 4 | `impact_analyzer` | Nova Lite | Har article ka impact card banana. Jo article business se relevant nahi, use mark karna | `articles` → `cards` |
| 5 | `summarizer` | Nova Lite | Sirf cards se 3-5 summary points banana, har point ke saath article id | `cards` → `summary` |
| 6 | `validator` | Nahi (code) | Galat source id, bina source wale points aur aise numbers jo article text me nahi hain, unhe hatana | `cards, summary, articles` → saaf `cards, summary` |

**Schemas (Pydantic, JSON):**
```json
RawArticle  { "title": "str", "url": "str", "content": "str", "published_date": "str|null", "score": "float" }
Article     { "id": "int", "title": "str", "url": "str", "source": "str", "published_date": "YYYY-MM-DD",
              "content": "str", "is_today_or_yesterday": "bool" }
ImpactCard  { "article_id": "int", "relevant": "bool", "summary": "str",
              "sentiment": "positive|negative|neutral", "level": "high|medium|low",
              "reason": "str (ek line)", "horizon": "short|long" }
SummaryPoint{ "text": "str", "source_ids": ["int"] }        // URL code jodega, LLM nahi
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
Error ya khali result par kya hoga:
- **query_builder fail:** user ka sawal hi query ban jayega (fallback), flow rukega nahi.
- **Tavily error / timeout:** 1 retry. Phir bhi fail ho to `status=error`, message "Search abhi available nahi".
- **0 news (search ya filter ke baad):** `no_news`, message "Is topic par pichhle 30 din me koi relevant news nahi mili."
- **Impact JSON invalid:** us article ke liye 1 retry, phir wo card drop. Baaki cards chalte rahenge.
- **Summarizer fail:** summary khali rahegi, cards phir bhi dikhenge (`status=ok`, message "Summary nahi ban payi").
- **Validator ke baad 0 points:** wahi upar wala summary-fail case.

## 3. Folder structure
```
.env.example          # sirf key names
.gitignore            # .env, *.db
requirements.txt
app/
  config.py           # .env load (keys, region, model IDs, MAX_ARTICLES=8, DAYS=30)
  profile.py          # business profile + competitors (REQUIREMENTS se)
  schemas.py          # saare Pydantic models
  llm.py              # ChatBedrockConverse factory (model ID ke hisaab se)
  nodes/
    query_builder.py
    news_search.py    # LangChain Tavily tool wrapper
    filter_rank.py    # pure Python
    impact_analyzer.py
    summarizer.py
    validator.py      # pure Python
  prompts.py          # saare prompts ek jagah
  graph.py            # LangGraph StateGraph + conditional edges
  db.py               # SQLite: init, save_run, list_runs, get_run
  api.py              # FastAPI app
ui/
  streamlit_app.py    # 2 screens
tests/
  fixtures/           # nakli Tavily response, nakli articles (test ke liye)
  test_filter_rank.py, test_validator.py, test_nodes.py, test_graph.py, test_db.py, test_api.py
```

## 4. Tavily search
- **Query:** `query_builder` har query me business context jodta hai (jaise "solar module India", competitor ka naam, "Maharashtra"). Max 4 queries, har query se 5-8 results.
- **Call:** `topic="news"`, `days=30`, `search_depth="basic"`, `max_results=8`. India-focused query text.
- **30 din ka filter (code me dobara):** `published_date` parse karo (IST). Date na mile ya parse na ho to drop. Aaj se 30 din se purani ho to drop.
- **Priority:**
  1. `is_today_or_yesterday` (IST) wali news sabse pehle.
  2. Phir date ke hisaab se, nayi se purani.
  3. Barabar ho to Tavily `score` se.

  Duplicate URL/title hatao, top 8 rakho.

## 5. Hallucination rokna
1. LLM ko sirf article ka `title + content + date` milega, ID ke saath (`[1] ... [2] ...`). Uske alawa koi general knowledge nahi.
2. Prompt rule: "Sirf diye gaye text se likho. Jo text me nahi hai, wo mat likho. Relevant na ho to `relevant=false`."
3. `temperature=0`, aur output Pydantic schema ke through structured JSON me (LangChain `with_structured_output`).
4. **LLM URL nahi likhega.** Wo sirf `article_id` / `source_ids` dega, URL code apne aap jodega. Isse fake link ban hi nahi sakta.
5. `validator`:
   - `source_ids` asli articles se match karne chahiye.
   - Summary/reason me jo number hai wo source article ke text me hona chahiye, warna point drop.
   - Enum values check hongi.
6. Summarizer ko sirf validated cards milenge, raw web nahi.

## 6. SQLite tables
| Table | Columns |
|---|---|
| `queries` | id PK, question, topic, competitors (JSON text), status, message, summary_json, created_at |
| `articles` | id PK, query_id FK, title, url, source, published_date, content, rank |
| `impacts` | id PK, article_id FK, relevant, summary, sentiment, level, reason, horizon |

Save ek hi jagah hoga: `api.py`, graph khatam hone ke baad `db.save_run()`. Graph khud DB ko nahi chhuega.

## 7. FastAPI + Streamlit
**Endpoints:**
- `GET /health` → `{status: "ok"}`
- `POST /ask` → body `{question, topic?, competitors?}` → `AskResponse` (aur DB save)
- `GET /history?limit=20` → `[{query_id, question, status, created_at}]`
- `GET /history/{query_id}` → pura `AskResponse`

**Streamlit (sidebar se 2 screens):**
1. **Ask:**
   - Inputs: sawal ka textbox, topic dropdown (energy prices / policy / competitor / tariff / market / any), competitor multiselect, "Pucho" button.
   - Neeche summary points, har point ke saath link.
   - Phir impact cards: aaj/kal wale "Today/Yesterday" badge ke saath upar, sentiment ka rang, level, horizon, reason, link.
   - `no_news` ya `error` par saaf message.
2. **History:** pichhle sawalon ki list. Kisi pe click karo to wahi result dobara dikhe (`/history/{id}`).

## 8. Bedrock models (Amazon Nova)
| Agent | Model | Kyun |
|---|---|---|
| query_builder | Nova Micro | Chhota text kaam, sabse sasta |
| impact_analyzer | Nova Lite | Har article par chalega, sasta + structured output theek |
| summarizer | Nova Lite | Input chhota hai (sirf cards). Quality kam lage to Nova Pro par switch |

- Model IDs `.env` me rahenge (`MODEL_QUERY`, `MODEL_IMPACT`, `MODEL_SUMMARY`), code me hardcode nahi honge.
- Region `AWS_REGION` se aayega (jaise `ap-south-1`). Mumbai region me shayad cross-region inference profile ID (jaise `apac.amazon.nova-lite-v1:0`) chahiye ho. Exact ID Bedrock console me confirm karna.

## 9. Risks aur hal
| Risk | Hal |
|---|---|
| Tavily me `published_date` missing | Aisi news drop. Kam results aaye to message dikhao, date guess nahi karenge |
| Irrelevant ya duplicate news | URL/title dedupe + `relevant=false` wale cards drop |
| LLM fact ya number banaye | Sirf article text, number-check validator, URL code jodega |
| Nova galat JSON de | Structured output + 1 retry + card drop |
| Bedrock model access/region | Model ID aur region `.env` me. Step 4 me pehle ek test call |
| Slow response (8 LLM calls) | Impact calls parallel (LangChain `batch`), max 8 articles |
| Tavily/Bedrock cost ya limits | Max 4 queries, 8 articles. Micro/Lite models |
| "Aaj/kal" timezone galat | Saari date logic IST (`Asia/Kolkata`) me |
| Keys leak | Sirf `.env`, `.gitignore` me `.env`, logs me keys print nahi |

---

## Coding steps (har step alag se test ho sake)
1. **Skeleton:** folders, `requirements.txt`, `.env.example`, `.gitignore`, `config.py`, `profile.py`, `schemas.py`. Test: schemas valid/invalid data par pytest.
2. **filter_rank (pure code):** Test: fixture articles (aaj, kal, 10 din, 40 din, bina date) → sahi order aur drops.
3. **validator (pure code):** Test: galat source_id, banaya hua number, galat enum → drop hote hain.
4. **llm.py + query_builder:** Test: ek asli Bedrock call (Nova Micro). Fail ho to model ya region issue pakad me aa jayega.
5. **news_search:** Test: mocked Tavily (fixture), phir ek asli query manually.
6. **impact_analyzer:** Test: 2 fixture articles (ek relevant, ek nahi) → schema-valid cards, irrelevant `relevant=false`.
7. **summarizer:** Test: fixture cards → points jinke `source_ids` valid hon.
8. **graph.py:** Test: mocked nodes ke saath teeno raste (ok / no_news / error), phir ek asli end-to-end run CLI se.
9. **db.py:** Test: in-memory SQLite me save → list → get.
10. **api.py:** Test: FastAPI TestClient se `/health`, `/ask` (graph mocked), `/history`.
11. **streamlit_app.py:** Manual: API chalao, REQUIREMENTS ke 5 test sawal pucho, format check karo.

## Verification (end me)
- `pytest` sab pass.
- REQUIREMENTS ke 5 test sawal UI se chalao. Har jawab me check:
  - har point ka link khulta ho
  - koi news 30 din se purani na ho
  - aaj/kal wali news upar ho
  - har card me 4 impact fields hon
- Galat ya bekaar sawal dalo, to "no news" message aaye.
