# REQUIREMENTS — Agentic AI News Impact System

## 1. Goal
User apne business se jude kisi topic par sawal puchhe. Agents internet se pichhle 30 din ki
latest news dhoondhein (Tavily), har news ka business par asar nikaalein (AWS Bedrock LLM),
aur Streamlit frontend par source links ke saath ek short summary dikhayein.

## 2. Business Profile
| Field | Value |
|---|---|
| Business | Solar panel (PV module) manufacturing |
| Location | Maharashtra, India (city: _TBD_) |
| Products/Services | Mono-PERC / TOPCon solar modules; rooftop aur utility-scale projects ke liye module supply; EPC/installation support |
| Dependencies | Energy prices (crude oil, coal, power tariff); stock market (Nifty, Sensex, Nifty Energy, solar sector stocks); solar cell/polysilicon import prices; govt policy (ALMM, BCD, PLI, PM Surya Ghar) |
| Competitors (confirmed) | Waaree Energies, Adani Solar, Tata Power Solar, Vikram Solar, Premier Energies |

## 3. Users
- **Business owner / management**: strategy aur risk ke faisle.
- **Procurement / finance team**: raw material aur energy cost par nazar.
- **Sales team**: competitor aur demand ki news.

Users non-technical hain. Sawal Hinglish ya English me aa sakte hain.

## 4. Features
1. **Question input**: Streamlit me free-text sawal, saath me optional topic/competitor filter.
2. **News search agent**: Tavily se search, sirf pichhle 30 din ki news.
3. **Recency ranking**: aaj aur kal ki news sabse upar, uske baad baaki news nayi se purani.
4. **Impact agent**: Bedrock LLM har news ke liye impact card banaye (format Rules me hai).
5. **Overall summary**: 3-5 lines ka nichod, har claim ke saath source link.
6. **Source links**: har card aur har summary point clickable link ke saath.
7. **History**: sawal, news aur impact SQLite me save ho, aur pichhle sawal dobara dekhe ja sakein.
8. **API**: FastAPI backend (jaise `POST /ask`, `GET /history`). Streamlit isi API ko call karega.

## 5. Tech Stack
- Backend: Python + FastAPI
- Agents: AWS Bedrock (LLM) + Tavily (search)
- Agent framework:
  - **LangGraph**: agent workflow ka graph (search → filter/rank → impact → summary), state aur retries
  - **LangChain**: Bedrock chat model, Tavily search tool, prompts aur structured output (impact fields)
- Frontend: Streamlit
- Storage: SQLite
- Config: `.env` (API keys, AWS credentials)
- Deployment: abhi local; AWS baad me

## 6. Rules
1. **Source mandatory**: har claim ke saath source link ho. Jis claim ka source na ho, wo answer me nahi aayega.
2. **30 din limit**: 30 din se purani news drop ho. Jis news ki publish date pata na chale, wo bhi drop ho.
3. **Recency priority**: aaj aur kal ki news ko sabse zyada priority mile.
4. **No made-up facts**: jo baat news me nahi hai, wo answer me nahi aayegi. Koi number, naam ya date khud se nahi banegi. Relevant news na mile to saaf likha jaye: "Is topic par pichhle 30 din me koi relevant news nahi mili."
5. **Impact format**: har news ke saath ye fields hon:
   - `sentiment`: positive / negative / neutral
   - `level`: high / medium / low
   - `reason`: ek line, sirf news ke facts par based
   - `horizon`: short term / long term
6. **Secrets**: API keys sirf `.env` me rahengi. Code, logs aur git me kabhi nahi. `.env` gitignore me rahega aur `.env.example` me sirf key names honge.

## 7. Test Questions + Expected Answer Format

### Common format (har answer me)
```
Summary: 3-5 lines, har line ke end me [source link]

News Cards (aaj/kal wali sabse upar):
  Title    : [headline]
  Source   : [publisher name]
  Date     : [YYYY-MM-DD]
  Link     : [url]
  Summary  : [1-2 line, sirf news se]
  Impact   : [positive|negative|neutral] | Level: [high|medium|low] | [short|long] term
  Reason   : [ek line]
```
Note: neeche ke examples sirf format aur quality dikhane ke liye hain. Ismein koi asli news ya number nahi hai.

---

**Q1. "Crude oil aur coal ke daam badhne se mere module production cost par kya asar padega?"**
- Expected news: 3-6 (energy prices, power tariff, logistics cost)
- Achha jawab: har card me batata ho ki cost upar ja rahi hai ya neeche, aur reason me news ka hi fact ho.
- Example card: `Impact: negative | Level: medium | short term` — Reason: "[news ke mutabik coal/power cost badhne se factory ka bijli kharch badh sakta hai]"

**Q2. "Solar cell / polysilicon import duty ya ALMM policy me koi naya badlaav aaya hai?"**
- Expected news: 2-5 (MNRE/govt notifications, policy news)
- Achha jawab: policy ka naam, kab se lagu hai (news me di gayi date) aur notification ya news ka link ho.
- Example card: `Impact: positive | Level: high | long term` — Reason: "[news ke mutabik domestic manufacturers ko protection milega]"

**Q3. "Waaree aur Adani Solar ki latest news kya hai, aur mere business ke liye iska kya matlab hai?"**
- Expected news: 3-8 (orders, capacity expansion, results, share price)
- Achha jawab: har competitor ki alag cards hon, aur impact mere business ke nazariye se ho (competition badha ya ghata).
- Example card: `Impact: negative | Level: medium | long term` — Reason: "[competitor ki nayi capacity se market me pricing pressure aa sakta hai]"

**Q4. "Maharashtra me power tariff ya MSEDCL rooftop/net-metering rules me koi update?"**
- Expected news: 2-5 (MERC/MSEDCL orders, state news)
- Achha jawab: factory cost par asar aur rooftop demand par asar, dono alag cards me bataye jayein.
- Example card: `Impact: positive | Level: medium | short term` — Reason: "[news ke mutabik rooftop approval aasaan hone se demand badh sakti hai]"

**Q5. "Nifty Energy aur solar stocks ka trend kya hai? Investor sentiment kaisa hai?"**
- Expected news: 3-6 (market reports, sector stock moves)
- Achha jawab: jo numbers diye jayein wo sirf news se hon, saath me link ho, aur koi buy/sell salah na ho.
- Example card: `Impact: neutral | Level: low | short term` — Reason: "[news ke mutabik sector me mixed movement raha]"

**Bura jawab (reject):** bina link ka claim, 30 din se purani news, bina date ki news, khud se banaya number, ya buy/sell advice.

## 8. Out of Scope (abhi nahi banana)
- AWS deployment (abhi sirf local)
- Login / multi-user auth
- Email / WhatsApp alerts, scheduled reports
- Live price tickers aur charts
- Buy/sell ya investment advice
- Ek se zyada business profiles
- Mobile app
- Paid data feeds (Bloomberg, etc.)
