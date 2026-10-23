"""Inventory coverage, currency bounds and refresh checks."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from graph import build_graph, chat_turn
from langchain_core.messages import AIMessage
from test_graph import FakeModel


class InventoryTests(unittest.TestCase):
    def test_coverage_ranges_and_refresh_in_existing_graph(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(database, 'DB_PATH', Path(folder) / 'test.db'):
            database.init_db()
            def save(pid, **fields):
                base = dict(id=pid, location='New Cairo', parent_location='New Cairo',
                            property_type='Apartment', price=5000000, on_sale=True,
                            payment_plans=[{'currency': 'EGP'}])
                database.save_checkpoint({}, {**base, **fields})
            save(1, min_price=4000000, max_price=6000000)
            save(2, location='North Investors', property_type='Villa', price=20000000)
            save(3, price=1, payment_plans=[{'currency': 'USD'}])
            save(4, price=999999999, on_sale=False)
            summary = database.inventory_summary()
            self.assertEqual(summary['overall']['listing_count'], 3)
            self.assertEqual(summary['overall']['min_price_egp'], 4000000)
            self.assertEqual(summary['overall']['max_price_egp'], 20000000)
            area = summary['locations']['New Cairo']
            self.assertEqual(area['listing_count'], 3)
            self.assertEqual(area['property_types']['Apartment']['max_price_egp'], 6000000)
            model = FakeModel([AIMessage(content='Ready'), AIMessage(content='Updated')])
            graph = build_graph([('google_genai', model)])
            state = chat_turn(graph, 'Hello')
            save(5, location='New Test Area', parent_location=None, price=3000000)
            chat_turn(graph, 'What is available now?', state)
            self.assertNotIn('New Test Area', model.calls[0][0].content)
            self.assertIn('New Test Area', model.calls[1][0].content)
            self.assertEqual(database.inventory_summary()['overall']['min_price_egp'], 3000000)

    def test_empty_inventory(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(database, 'DB_PATH', Path(folder) / 'test.db'):
            database.init_db()
            summary = database.inventory_summary()
            self.assertEqual(summary['locations'], {})
            self.assertIsNone(summary['overall']['min_price_egp'])


if __name__ == '__main__':
    unittest.main()
