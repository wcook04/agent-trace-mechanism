"""Exact-range citation regressions; all values below are synthetic.

Run with: python -m pytest tests/test_citation_queries.py
"""
import unittest


from trace_mechanism import capture_reader as reader

WINDOW = 'a' * 64
TEXT = 'FAIL in A; PASS in B'
ENTRY = {'session_id': 'synthetic-session', 'item_id': 'synthetic-item', 'kind': 'CommandExecution',
         'item': {'aggregated_output': TEXT, 'exit_code': 0}}
CAPTURE = reader.Capture(
    {'windows': [{'session_id': 'synthetic-session', 'window_id': WINDOW}],
     'root_session_id': 'synthetic-session'},
    {WINDOW: {'items': [ENTRY]}})
EXACT = reader.make_cite(WINDOW, 'synthetic-item', '/aggregated_output', 0, 4)


class CitationQueryTests(unittest.TestCase):
    def resolve(self, citation):
        return reader.cite(CAPTURE, [citation])['results'][0]

    def test_valid_range_preserves_exact_text(self):
        result = self.resolve(EXACT)
        self.assertTrue(result['resolved'])
        self.assertEqual(result['text'], 'FAIL')

    def test_intentional_whole_item_still_resolves(self):
        result = self.resolve(reader.make_cite(WINDOW, 'synthetic-item'))
        self.assertTrue(result['resolved'])
        self.assertEqual(result['text'], reader.canonical(ENTRY))

    def test_intentional_whole_field_still_resolves(self):
        result = self.resolve(reader.make_cite(WINDOW, 'synthetic-item', '/aggregated_output'))
        self.assertTrue(result['resolved'])
        self.assertEqual(result['text'], TEXT)

    def test_html_escaping_never_widens_a_range(self):
        result = self.resolve(EXACT.replace('&', '&amp;'))
        self.assertFalse(result['resolved'])
        self.assertIn('HTML-escaped', result['error'])

    def test_unknown_query_parameters_are_refused(self):
        for citation in (EXACT.replace('chars=', 'char='), EXACT + '&unknown=1', EXACT + '&unknown='):
            with self.subTest(citation=citation):
                result = self.resolve(citation)
                self.assertFalse(result['resolved'])
                self.assertIn('Unknown', result['error'])

    def test_duplicate_parameters_are_refused(self):
        for extra in ('&chars=11-15', '&chars=0-4', '&field=/exit_code'):
            with self.subTest(extra=extra):
                result = self.resolve(EXACT + extra)
                self.assertFalse(result['resolved'])
                self.assertIn('Duplicate', result['error'])

    def test_malformed_urls_and_ranges_fail_as_individual_citations(self):
        malformed = (
            'agent-trace://[bad/item',
            EXACT.replace('0-4', '4-0'),
            EXACT.replace('0-4', '²-³'),
            EXACT.replace('0-4', ''),
            EXACT.replace('0-4', '0-400'),
            EXACT + '#ignored-fragment',
            EXACT + '&bare-key',
        )
        for citation in malformed:
            with self.subTest(citation=citation):
                self.assertFalse(self.resolve(citation)['resolved'])

    def test_bad_citation_does_not_abort_batch(self):
        second = reader.make_cite(WINDOW, 'synthetic-item', '/aggregated_output', 11, 15)
        result = reader.cite(CAPTURE, [EXACT, 'agent-trace://[bad/item', second])
        self.assertEqual(result['checked'], 3)
        self.assertEqual(result['resolved'], 2)
        self.assertEqual([r['resolved'] for r in result['results']], [True, False, True])
        self.assertEqual(result['results'][0]['text'], 'FAIL')
        self.assertEqual(result['results'][2]['text'], 'PASS')


if __name__ == '__main__':
    unittest.main()
