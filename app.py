"""Minimal Streamlit chat with isolated, temporary session memory."""
from copy import deepcopy

import streamlit as st

from graph import AgentUnavailable, chat_turn, create_graph


def reset_chat():
    """Clear only this session's conversation and provider selection."""
    st.session_state.agent_state = None
    st.session_state.chat_messages = []
    st.session_state.pop('agent_graph', None)


def main():
    st.set_page_config(page_title='Nawy AI Assistant', page_icon='🏠')
    st.title('Nawy AI Assistant')
    st.caption('Tell me what you are looking for. You can chat in Arabic or English.')
    if 'agent_state' not in st.session_state:
        reset_chat()
    st.button('New conversation', on_click=reset_chat)
    st.caption('Conversation memory lasts only for this session. Reloading may reset it.')

    for message in st.session_state.chat_messages:
        with st.chat_message(message['role']):
            st.markdown(message['content'])

    text = st.chat_input('Describe your ideal property', key='customer_message')
    if not text or not text.strip():
        return
    with st.chat_message('user'):
        st.markdown(text)
    try:
        with st.spinner('Looking into your request...'):
            if 'agent_graph' not in st.session_state:
                try:
                    settings = dict(st.secrets)
                except FileNotFoundError:
                    settings = {}
                # Keep the graph session-local; never globally cache customer state.
                st.session_state.agent_graph = create_graph(settings=settings)
            next_state = chat_turn(st.session_state.agent_graph, text,
                                   deepcopy(st.session_state.agent_state))
            answer = next_state['messages'][-1].text
            if not answer:
                raise AgentUnavailable('No response was returned. Please try again.')
        # Commit the history only after a successful turn, including internal tool context.
        st.session_state.agent_state = next_state
        st.session_state.chat_messages.extend([
            {'role': 'user', 'content': text}, {'role': 'assistant', 'content': answer},
        ])
        with st.chat_message('assistant'):
            st.markdown(answer)
    except AgentUnavailable as exc:
        st.error(str(exc))
        st.info('Your previous conversation is preserved. Please send your message again.')
    except Exception:
        # Do not expose SDK errors, credentials, or internal stack traces in the UI.
        st.error('Unable to complete this request. Check the configuration and try again.')
        st.info('Your previous conversation is preserved.')


if __name__ == '__main__':
    main()
