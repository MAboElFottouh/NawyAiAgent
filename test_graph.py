import json
import unittest
from unittest.mock import patch
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from graph import AgentUnavailable, build_graph, chat_turn, is_provider_unavailable
from google.genai.errors import ClientError


class FakeModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


class GraphTests(unittest.TestCase):
    def test_tools_fallback_and_history(self):
        call = AIMessage(content='', tool_calls=[{'name': 'search_properties',
            'args': {'target_price': 7000000, 'target_area_m2': 150}, 'id': 'call1', 'type': 'tool_call'}])
        primary = FakeModel([call, TimeoutError('secret body must never be shown')])
        backup = FakeModel([AIMessage(content='نتائج'), AIMessage(content='تمام')])
        app = build_graph([('google_genai', primary), ('openai', backup)])
        with patch('graph.search_properties', return_value={'total_matches': 1, 'properties': []}) as search:
            state = chat_turn(app, 'عايز شقة بحوالي ٧ مليون ومساحة ١٥٠')
        self.assertEqual(search.call_args.kwargs['target_price'], 7000000)
        self.assertEqual(state['provider'], 'openai')
        self.assertTrue(any(isinstance(m, ToolMessage) for m in backup.calls[0]))
        next_state = chat_turn(app, 'خليها فيلا', state)
        self.assertEqual(len([m for m in next_state['messages'] if isinstance(m, HumanMessage)]), 2)
        self.assertEqual(len(primary.calls), 2)
        self.assertEqual(len(state['messages']), 4)  # previous session snapshot untouched

    def test_wrapped_google_rate_limit(self):
        wrapped = RuntimeError('provider body')
        wrapped.__cause__ = ClientError(429, {'error': {'message': 'rate limit', 'status': 'RESOURCE_EXHAUSTED'}})
        self.assertTrue(is_provider_unavailable(wrapped))

    def test_sessions_are_separate(self):
        model = FakeModel([AIMessage(content='أهلا'), AIMessage(content='أهلا')])
        app = build_graph([('google_genai', model)])
        chat_turn(app, 'العميل الأول')
        chat_turn(app, 'العميل الثاني')
        self.assertNotIn('العميل الأول', str(model.calls[1]))

    def test_both_unavailable_safe_error(self):
        app = build_graph([('google_genai', FakeModel([TimeoutError('secret')])),
                           ('openai', FakeModel([TimeoutError('secret')]))])
        with self.assertRaises(AgentUnavailable) as caught:
            chat_turn(app, 'مرحبا')
        self.assertNotIn('secret', str(caught.exception))

    def test_programming_error_does_not_trigger_fallback(self):
        backup = FakeModel([])
        app = build_graph([('google_genai', FakeModel([ValueError('bad input')])), ('openai', backup)])
        with self.assertRaises(AgentUnavailable):
            chat_turn(app, 'مرحبا')
        self.assertEqual(backup.calls, [])


if __name__ == '__main__':
    unittest.main()
