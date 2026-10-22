"""Ensure saved listings never cause detail-page requests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import inspect_nawy as scraper


class SkipTests(unittest.TestCase):
    def test_saved_and_newly_added_ids_are_skipped_before_fetch(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(database, 'DB_PATH', Path(folder) / 'test.db'):
            database.init_db()
            database.save_checkpoint({}, {'id': 1, 'description': 'Large description'})
            state = scraper.load_state()
            self.assertEqual(state['properties'], [{'id': 1}])
            # Simulate another tool saving a unit after the scraper loaded its state.
            database.save_checkpoint({}, {'id': 2})
            urls = []

            class Fetcher:
                def get(self, url):
                    urls.append(url)
                    if '/property/' in url:
                        if '/property/3-' not in url:
                            raise AssertionError('Requested an existing property')
                        props = {'property': {'id': 3, 'name': 'New unit'}}
                    else:
                        props = {'loadedSearchResultsSSR': {'page': 1, 'total': 3, 'results': [
                            {'id': i, 'shareLink': f'https://www.nawy.com/property/{i}-test'}
                            for i in (1, 2, 3, 3)]}}
                    return '<script id="__NEXT_DATA__">' + json.dumps({'props': {'pageProps': props}}) + '</script>'

            with patch.object(scraper, 'LIMIT', 3), patch('builtins.print'):
                self.assertEqual(scraper.collect(state, Fetcher()), 0)
                self.assertEqual(scraper.collect(scraper.load_state(), Fetcher()), 0)
            self.assertEqual(len(urls), 2)  # One listing page and one new detail page.
            self.assertEqual(database.get_property_ids(), {'1', '2', '3'})
            self.assertEqual(len(database.load_checkpoint()['properties']), 3)


if __name__ == '__main__':
    unittest.main()
