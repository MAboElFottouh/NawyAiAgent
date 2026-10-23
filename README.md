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
The Streamlit UI in `app.py` keeps that state in each user's `st.session_state`
and passes `dict(st.secrets)` into `create_graph(settings=...)` on deployment.
There is no globally shared customer history.

Implemented: typed LangChain search tool, LangGraph model/tool loop, clarifying
questions, local SQLite search, budget ceilings with +10% allowance, minimum area/bedrooms/bathrooms, explicit hard
caps, Gemini/OpenAI failover, bounded request timeouts and graph steps.
Fallback retries the same current context and remains selected for that session.
A missing Gemini key allows OpenAI-only operation. No keys gives a clear setup error.

Not yet integrated into the agent: live Nawy search. Persistent conversation history is not implemented.
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

## Streamlit session memory

Run `.venv/bin/python -m streamlit run app.py` from the project directory.
Each browser session keeps its own graph, internal agent state, and visible messages.
Successful turns preserve previous context across Streamlit reruns. Failed turns
leave previous history untouched. The New conversation button clears only the
current session and resets provider selection. No conversation is written to SQLite.
Reloading the page or restarting the server may end the session; there is no
permanent conversation history.

Test session isolation and resets with `.venv/bin/python -m unittest -v test_app.py`.

## Conversation and search policy

The English system prompt follows the customer's latest language and asks one combined
completion question. Unanswered optional preferences are omitted after the reply.
Explicit requests to search immediately skip that question. Changed/cancelled filters
must be reflected in a fresh search.

Search returns five results by default or the requested count, limited by available
inventory. Finishing and latest delivery date are supported when explicitly supplied.
Rooms and area remain minimum requirements. Exact results respect final budget caps.
If no exact results exist, the tool returns ranked, clearly labelled alternatives with
per-property differences; those alternatives may cross location or budget constraints.
They never replace the original requirements. No web-search tool is enabled or offered.

Run the policy regressions with `.venv/bin/python -m unittest -v test_search_policy.py`.
Model phrasing and clarification behavior are prompt-guided; deterministic filter and
alternative behavior are covered by local tests.
