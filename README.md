# Nawy AI Agent — local conversation stage

Setup:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Fill `GOOGLE_API_KEY` and `OPENAI_API_KEY` in `.env`. Gemini is primary;
OpenAI is used if Gemini is unavailable. Model IDs can be changed through
`GEMINI_MODEL` and `OPENAI_MODEL`. Existing environment variables override `.env`.
No credentials are committed or included in the system prompt.

Start a terminal conversation:

```bash
.venv/bin/python graph.py
```

Type `exit` to end. History lives only in this conversation process; restarting
starts a new conversation. `chat_turn(graph, text, state)` returns the next state.
For the upcoming Streamlit UI, keep that state in each user's `st.session_state`
and pass `dict(st.secrets)` into `create_graph(settings=...)` on deployment.
There is no globally shared customer history.

Implemented: typed LangChain search tool, LangGraph model/tool loop, clarifying
questions, local SQLite search, budget ceilings with +10% allowance, minimum area/bedrooms/bathrooms, explicit hard
caps, Gemini/OpenAI failover, bounded request timeouts and graph steps.
Fallback retries the same current context and remains selected for that session.
A missing Gemini key allows OpenAI-only operation. No keys gives a clear setup error.

Not yet implemented: live Nawy search, Streamlit UI, persistent conversation history.
The agent must disclose no local matches instead of claiming a web search.

Run offline checks:

```bash
.venv/bin/python -m unittest -v test_graph.py test_retriever.py
```

References:
- https://docs.langchain.com/oss/python/langchain/agents
- https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai
- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- https://developers.openai.com/api/docs/models/gpt-4.1-mini
