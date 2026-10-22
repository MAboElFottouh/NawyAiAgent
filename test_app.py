"""Session memory checks without external model calls."""
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from streamlit.testing.v1 import AppTest

from graph import AgentUnavailable


class SessionTests(unittest.TestCase):
    def test_history_reruns_isolation_and_reset(self):
        calls = []

        def fake_turn(graph, text, state=None):
            calls.append(state)
            return {'messages': [*(state or {}).get('messages', []),
                                 HumanMessage(content=text), AIMessage(content='Test answer')],
                    'provider': 'google_genai', 'fallback_used': False}

        with patch('graph.create_graph', return_value=object()), patch('graph.chat_turn', side_effect=fake_turn):
            first = AppTest.from_file('app.py').run()
            first.chat_input[0].set_value('I want an apartment').run()
            self.assertFalse(first.exception)
            first.run()
            self.assertEqual(len(calls), 1)
            first.chat_input[0].set_value('My budget is 7 million').run()
            self.assertEqual(len(calls[1]['messages']), 2)
            self.assertEqual(len(first.session_state['agent_state']['messages']), 4)
            self.assertEqual(len(first.chat_message), 4)
            second = AppTest.from_file('app.py').run()
            self.assertIsNone(second.session_state['agent_state'])
            second.chat_input[0].set_value('I want a villa').run()
            self.assertIsNone(calls[-1])
            first.button[0].click().run()
            self.assertIsNone(first.session_state['agent_state'])
            self.assertEqual(len(first.chat_message), 0)
            self.assertEqual(len(second.session_state['agent_state']['messages']), 2)

    def test_failed_turn_preserves_previous_history(self):
        def success(graph, text, state):
            return {'messages': [HumanMessage(content=text), AIMessage(content='Hello')]}

        with patch('graph.create_graph', return_value=object()), patch('graph.chat_turn', side_effect=success):
            app = AppTest.from_file('app.py').run()
            app.chat_input[0].set_value('Hello').run()
        with patch('graph.chat_turn', side_effect=AgentUnavailable('Model unavailable')):
            app.chat_input[0].set_value('Next message').run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.session_state['agent_state']['messages']), 2)
            self.assertEqual(len(app.session_state['chat_messages']), 2)
            self.assertEqual(app.error[0].value, 'Model unavailable')


if __name__ == '__main__':
    unittest.main()
