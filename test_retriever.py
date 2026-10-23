import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from retriever import search_properties


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(database, 'DB_PATH', Path(self.temp.name) / 'test.db')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        database.init_db()
        base = dict(property_type='Apartment', location='North Investors', parent_location='New Cairo',
                    price=5_000_000, area_m2=120, bedrooms=2, bathrooms=2, on_sale=True,
                    payment_plans=[dict(currency='EGP', is_cash=False, down_payment=500_000)])
        for record in [dict(base, id=1), dict(base, id=2, max_price=9_000_000),
                       dict(base, id=3, on_sale=False),
                       dict(base, id=4, payment_plans=[dict(currency='EGP', is_cash=True, down_payment=0)]),
                       dict(base, id=5, payment_plans=[dict(currency='USD', is_cash=False, down_payment=100)])]:
            database.save_checkpoint({}, record)

    def test_arabic_location_type_budget_and_same_plan(self):
        result = search_properties(property_type='شقة', location='القاهرة الجديدة', max_price=6_000_000,
                                   bedrooms=2, payment_method='installments', max_down_payment=600_000)
        self.assertEqual([p['id'] for p in result['properties']], [1])
        self.assertEqual(result['total_matches'], 1)

    def test_cash_zero_deposit_not_free(self):
        self.assertEqual(search_properties(payment_method='cash', max_down_payment=600_000)['total_matches'], 0)

    def test_literal_text_and_empty_results(self):
        for location in ["' OR 1=1 --", '%', 'No such location']:
            self.assertEqual(search_properties(location=location)['properties'], [])

    def seed_targets(self):
        for pid, price, area in [(10, 4_000_000, 150), (11, 6_650_000, 135),
                                 (12, 7_000_000, 150), (13, 7_350_000, 165),
                                 (14, 7_350_001, 150), (15, 7_000_000, 166)]:
            database.save_checkpoint({}, dict(id=pid, price=price, area_m2=area, on_sale=True,
                payment_plans=[dict(currency='EGP', is_cash=True)]))

    def test_price_ceiling_and_area_minimum(self):
        self.seed_targets()
        result = search_properties(target_price=7_000_000, target_area_m2=150, limit=20)
        ids = [p['id'] for p in result['properties']]
        self.assertEqual(ids[0], 12)
        self.assertEqual(set(ids), {10, 12, 13, 14, 15})
        self.assertIsNone(result['applied_filters']['min_price'])
        self.assertEqual(result['applied_filters']['max_price'], 7_700_000)
        self.assertEqual(result['applied_filters']['min_area_m2'], 150)
        self.assertIsNone(result['applied_filters']['max_area_m2'])

    def test_minimum_rooms_and_exact_price_boundary(self):
        for pid, price, area, beds, baths in [
            (20, 7700000, 150, 2, 1), (21, 7700000.01, 150, 2, 1),
            (22, 6800000, 200, 3, 2), (23, 6800000, 149, 3, 2),
            (24, 6800000, 150, 1, 2), (25, 6800000, 150, 2, 0),
            (26, 6800000, 150, 2, None)]:
            database.save_checkpoint({}, dict(id=pid, price=price, area_m2=area,
                bedrooms=beds, bathrooms=baths, payment_plans=[dict(currency='EGP', is_cash=True)]))
        result = search_properties(target_price=7000000, target_area_m2=150, bedrooms=2, bathrooms=1)
        self.assertEqual({p['id'] for p in result['properties']}, {20, 22})

    def test_explicit_caps_and_zero_tolerance(self):
        self.seed_targets()
        result = search_properties(target_price=7_000_000, target_area_m2=150,
                                   max_price=7_000_000, max_area_m2=160, limit=20)
        self.assertEqual([p['id'] for p in result['properties']], [12, 10])
        result = search_properties(target_price=7_000_000, target_area_m2=150, price_tolerance=0, limit=20)
        self.assertEqual({p['id'] for p in result['properties']}, {10, 12, 15})
        for filters in [dict(target_price=0), dict(price_tolerance=-0.1), dict(price_tolerance=2),
                        dict(target_area_m2=float('inf')), dict(price_tolerance=None)]:
            with self.assertRaises(ValueError):
                search_properties(**filters)

    def test_invalid_filters(self):
        for filters in [dict(min_price=10, max_price=1), dict(limit=0), dict(max_price=float('nan')),
                        dict(bedrooms=-1), dict(payment_method='invalid')]:
            with self.assertRaises(ValueError):
                search_properties(**filters)


if __name__ == '__main__':
    unittest.main()
