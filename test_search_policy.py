"""Regression checks for result counts, optional filters and labelled alternatives."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from graph import SearchFilters, _search
from retriever import search_properties


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db_patch = patch.object(database, 'DB_PATH', Path(self.folder.name) / 'test.db')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        database.init_db()
        for i in range(1, 31):
            database.save_checkpoint({}, {'id': i, 'property_type': 'Apartment', 'location': 'New Cairo',
                'price': 8000000, 'area_m2': 150, 'bedrooms': 3, 'bathrooms': 2, 'on_sale': True,
                'finishing': 'Fully Finished', 'delivery_date': '2028-06-30',
                'payment_plans': [{'currency': 'EGP', 'is_cash': False, 'down_payment': 1000000}]})

    def test_requested_count_and_default(self):
        self.assertEqual(len(_search()['properties']), 5)
        args = SearchFilters(limit=25).model_dump(exclude_none=True)
        result = _search(**args)
        self.assertEqual(result['match_type'], 'exact')
        self.assertEqual(len(result['properties']), 25)
        self.assertEqual(len(_search(limit=100)['properties']), 30)

    def test_finishing_delivery_and_minima(self):
        result = search_properties(finishing='Fully Finished', delivery_by='2028-12-31',
                                   bedrooms=2, bathrooms=1, target_area_m2=90)
        self.assertEqual(result['total_matches'], 30)
        self.assertEqual(search_properties(delivery_by='2027-12-31')['total_matches'], 0)
        self.assertEqual(search_properties(finishing='Semi Finished')['total_matches'], 0)
        with self.assertRaises(ValueError):
            search_properties(delivery_by='not a date')

    def test_alternatives_disclose_hard_cap_and_location(self):
        result = _search(location='El Sheikh Zayed', max_price=7000000, limit=8)
        self.assertEqual(result['total_matches'], 0)
        self.assertEqual(result['match_type'], 'alternative')
        self.assertEqual(len(result['properties']), 8)
        for prop in result['properties']:
            self.assertEqual({d['field'] for d in prop['differences']}, {'location', 'price'})
        self.assertEqual(result['requested_filters']['max_price'], 7000000)

    def test_exact_results_do_not_get_padded_with_alternatives(self):
        database.save_checkpoint({}, {'id': 100, 'property_type': 'Villa', 'price': 10000000})
        result = _search(property_type='Villa', limit=10)
        self.assertEqual(result['match_type'], 'exact')
        self.assertEqual(len(result['properties']), 1)

    def test_error_is_not_zero_matches(self):
        result = _search(min_price=10, max_price=1)
        self.assertEqual(result['status'], 'invalid_filters')
        self.assertNotIn('properties', result)


if __name__ == '__main__':
    unittest.main()
