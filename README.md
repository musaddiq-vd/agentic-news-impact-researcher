# Agentic AI News Impact System

Ask a question about a solar module business. Agents fetch the last 30 days of news, explain each story's business impact, and show a short summary with source links.

## Stack
- Python, FastAPI, Streamlit
- LangGraph + LangChain
- AWS Bedrock (Amazon Nova), Tavily search
- SQLite

## Setup (Windows)
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
Fill in `.env`: AWS keys and region, `TAVILY_API_KEY`, and the Bedrock model IDs (`MODEL_QUERY`, `MODEL_IMPACT`, `MODEL_SUMMARY`).

## Run
Start the API, then the UI in a second terminal:
```bash
uvicorn app.api:app --host 127.0.0.1 --port 8000
streamlit run ui/streamlit_app.py
```
Open http://localhost:8501.

## Test
```bash
pytest
```

## Docs
- [REQUIREMENTS.md](REQUIREMENTS.md): goals and rules
- [PLAN.md](PLAN.md): design and build steps
