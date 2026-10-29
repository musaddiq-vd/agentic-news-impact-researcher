# REQUIREMENTS — Agentic AI News Impact System

## 1. Goal
The user asks a question about a topic related to their business. Agents find the latest news
from the last 30 days (Tavily), a Bedrock LLM works out each story's impact on the business,
and a Streamlit frontend shows a short summary with source links.

## 2. Business Profile
| Field | Value |
|---|---|
| Business | Solar panel (PV module) manufacturing |
| Location | Maharashtra, India (city: _TBD_) |
| Products/Services | Mono-PERC / TOPCon solar modules; module supply for rooftop and utility-scale projects; EPC/installation support |
| Dependencies | Energy prices (crude oil, coal, power tariff); stock market (Nifty, Sensex, Nifty Energy, solar sector stocks); solar cell and polysilicon import prices; government policy (ALMM, BCD, PLI, PM Surya Ghar) |
| Competitors (confirmed) | Waaree Energies, Adani Solar, Tata Power Solar, Vikram Solar, Premier Energies |

## 3. Users
- **Business owner / management**: strategy and risk decisions.
- **Procurement / finance team**: tracking raw material and energy costs.
- **Sales team**: competitor and demand news.

Users are non-technical. Questions can be in Hinglish or English.

## 4. Features
1. **Question input**: free-text question in Streamlit, with an optional topic/competitor filter.
2. **News search agent**: Tavily search, last 30 days only.
3. **Recency ranking**: today's and yesterday's news first, then the rest from newest to oldest.
4. **Impact agent**: a Bedrock LLM builds an impact card for each story (format in Rules).
5. **Overall summary**: a 3-5 line summary, with a source link for every claim.
6. **Source links**: every card and every summary point has a clickable link.
7. **History**: questions, news and impacts are saved in SQLite and past questions can be reopened.
8. **API**: FastAPI backend (e.g. `POST /ask`, `GET /history`). Streamlit calls this API.

## 5. Tech Stack
- Backend: Python + FastAPI
- Agents: AWS Bedrock (LLM) + Tavily (search)
- Agent framework:
  - **LangGraph**: agent workflow graph (search → filter/rank → impact → summary), state and retries
  - **LangChain**: Bedrock chat model, Tavily search tool, prompts and structured output (impact fields)
- Frontend: Streamlit
- Storage: SQLite
- Config: `.env` (API keys, AWS credentials)
- Deployment: local for now; AWS later

## 6. Rules
1. **Source is mandatory**: every claim has a source link. A claim without a source is dropped from the answer.
2. **30-day limit**: news older than 30 days is dropped. News with an unknown publish date is dropped too.
3. **Recency priority**: today's and yesterday's news get the highest priority.
4. **No made-up facts**: anything that is not in the news does not appear in the answer. No number, name or date is invented. If no relevant news is found, say so clearly: "No relevant news found for this topic in the last 30 days."
5. **Impact format**: every story has these fields:
   - `sentiment`: positive / negative / neutral
   - `level`: high / medium / low
   - `reason`: one line, based only on facts from the news
   - `horizon`: short term / long term
6. **Secrets**: API keys live only in `.env`. Never in code, logs or git. `.env` is gitignored and `.env.example` holds key names only.

## 7. Test Questions + Expected Answer Format

### Common format (every answer)
```
Summary: 3-5 lines, each ending with [source link]

News Cards (today/yesterday first):
  Title    : [headline]
  Source   : [publisher name]
  Date     : [YYYY-MM-DD]
  Link     : [url]
  Summary  : [1-2 lines, from the news only]
  Impact   : [positive|negative|neutral] | Level: [high|medium|low] | [short|long] term
  Reason   : [one line]
```
Note: the examples below only show format and quality. They contain no real news or numbers.

---

**Q1. "How will rising crude oil and coal prices affect my module production cost?"**
- Expected news: 3-6 (energy prices, power tariff, logistics cost)
- Good answer: each card says whether cost is going up or down, and the reason uses only a fact from the news.
- Example card: `Impact: negative | Level: medium | short term` — Reason: "[per the news, higher coal/power cost can raise the factory's electricity bill]"

**Q2. "Has there been any change in solar cell / polysilicon import duty or ALMM policy?"**
- Expected news: 2-5 (MNRE/government notifications, policy news)
- Good answer: policy name, effective date (as given in the news) and a link to the notification or news.
- Example card: `Impact: positive | Level: high | long term` — Reason: "[per the news, domestic manufacturers get protection]"

**Q3. "What is the latest news on Waaree and Adani Solar, and what does it mean for my business?"**
- Expected news: 3-8 (orders, capacity expansion, results, share price)
- Good answer: separate cards per competitor, with impact from my business's point of view (competition up or down).
- Example card: `Impact: negative | Level: medium | long term` — Reason: "[the competitor's new capacity may put pricing pressure on the market]"

**Q4. "Any update on Maharashtra power tariff or MSEDCL rooftop/net-metering rules?"**
- Expected news: 2-5 (MERC/MSEDCL orders, state news)
- Good answer: impact on factory cost and impact on rooftop demand, in separate cards.
- Example card: `Impact: positive | Level: medium | short term` — Reason: "[per the news, easier rooftop approvals may raise demand]"

**Q5. "What is the trend in Nifty Energy and solar stocks? How is investor sentiment?"**
- Expected news: 3-6 (market reports, sector stock moves)
- Good answer: any numbers come only from the news, with a link, and no buy/sell advice.
- Example card: `Impact: neutral | Level: low | short term` — Reason: "[per the news, the sector moved mixed]"

**Bad answer (reject):** a claim without a link, news older than 30 days, news without a date, a made-up number, or buy/sell advice.

## 8. Out of Scope (not building now)
- AWS deployment (local only for now)
- Login / multi-user auth
- Email / WhatsApp alerts, scheduled reports
- Live price tickers and charts
- Buy/sell or investment advice
- More than one business profile
- Mobile app
- Paid data feeds (Bloomberg, etc.)
