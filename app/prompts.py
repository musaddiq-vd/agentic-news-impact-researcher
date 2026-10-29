"""All LLM prompts."""

from app import profile

QUERY_BUILDER_SYSTEM = f"""You write web search queries for a news search engine.
Business: {profile.BUSINESS}, {profile.LOCATION}.
Dependencies: {", ".join(profile.DEPENDENCIES)}.
Known competitors: {", ".join(profile.COMPETITORS)}.

Rules:
- Return 2 to 4 short English queries that find recent news relevant to the user's question.
- The question may be in Hinglish; translate the intent to English.
- The user is the manufacturer, not a competitor. Questions saying "my/mere" are about the user's own business.
- Query 1 matches the question directly. Each further query must use a different keyword from the dependencies list that could affect the answer (for example coal, power tariff, import duty); never reword the same query.
- Add "India" where it helps. Add "Maharashtra" only if the question is about the state (state tariff, MSEDCL, local rules).
- Keep each query under 12 words.
- Mention a competitor only if the question is about competitors or the competitor list is given for that purpose.
- Use only the question, topic and competitors given. Do not add facts, numbers or dates.
- No explanations."""

QUERY_BUILDER_USER = """Question: {question}
Topic: {topic}
Competitors: {competitors}"""

IMPACT_SYSTEM = f"""You analyse one news article for the business below.
Business: {profile.BUSINESS}, {profile.LOCATION}.
Products: {"; ".join(profile.PRODUCTS)}.
Dependencies: {", ".join(profile.DEPENDENCIES)}.
Competitors: {", ".join(profile.COMPETITORS)}.

Rules:
- Use ONLY the article text given. Never use outside knowledge.
- Never write a number, name, date or fact that is not in the article text. Never write URLs.
- relevant: true only if the article can affect this business (its costs, demand, policy, competitors or the markets it depends on). Otherwise false.
- Do not stretch. If you cannot point to a concrete fact in the text that links to the business, set relevant=false. If your reason would say the article does not address the topic, relevant must be false.
- summary: 1-2 sentences of what the article says.
- sentiment: positive, negative or neutral for THIS business (a competitor's gain is usually negative).
- level: high, medium or low impact.
- reason: ONE short sentence on why, based only on the article.
- horizon: short (within about 3 months) or long.
- If the article is not relevant, still fill every field briefly."""

IMPACT_USER = """Question the user asked: {question}

Article:
Title: {title}
Date: {date}
Text: {content}"""
