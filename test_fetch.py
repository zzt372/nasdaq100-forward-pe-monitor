import unittest
from datetime import date, timedelta

from fetch import Candidate, parse_table, parse_page, validate, MAIN, DEDICATED


class ParserTests(unittest.TestCase):
    def test_table_row(self):
        html = '''
        <table>
          <tr><th>Index</th><th>Forward P/E Ratio</th><th>Percentile Rank (10Y)</th><th>Valuation (10Y)</th><th>Last Update</th></tr>
          <tr><td>Nasdaq 100</td><td>20.78</td><td>24.2%</td><td>Undervalued</td><td>Sep 8, 2026</td></tr>
        </table>
        '''
        c = parse_table(html, 'test')
        self.assertEqual((c.forward_pe, c.percentile_10y, c.data_date), (20.78, 24.2, '2026-09-08'))

    def test_table_text_fallback(self):
        c = parse_table('<div>Nasdaq 100 20.78 24.2% Undervalued Sep 8, 2026</div>', 'test')
        self.assertEqual((c.forward_pe, c.percentile_10y), (20.78, 24.2))

    def test_search_index_snippet(self):
        html = '<div>Forward PE Ratio — Nasdaq 100 | 20.78 | 24.2% | Undervalued | Sep 8, 2026</div>'
        c = parse_table(html, 'bing-search-index/test', 'search-index-bing')
        self.assertEqual((c.forward_pe, c.percentile_10y, c.data_date), (20.78, 24.2, '2026-09-08'))
        self.assertTrue(c.source_kind.startswith('search-index-bing'))

    def test_main_page(self):
        html = '''
        <p>The Nasdaq 100 currently trades at a forward P/E ratio of 20.7 as of September 08, 2026.</p>
        <div>Valuation Percentile Rank</div><div>21.7%</div>
        '''
        c = parse_page(html, 'test', MAIN, 'nasdaq-100-main-page')
        self.assertEqual((c.forward_pe, c.percentile_10y, c.data_date), (20.7, 21.7, '2026-09-08'))

    def test_dedicated_page(self):
        html = '''
        <p>The Nasdaq 100 currently trades at a forward P/E ratio of 20.75 as of September 04, 2026.</p>
        <div>Valuation Percentile Rank</div><div>24.2%</div>
        '''
        c = parse_page(html, 'test', DEDICATED, 'dedicated-forward-pe-page')
        self.assertEqual((c.forward_pe, c.percentile_10y, c.data_date), (20.75, 24.2, '2026-09-04'))

    def test_invalid_percentile(self):
        c = Candidate(20.0, 101.0, date.today().isoformat(), 'x', 'x', 'test')
        with self.assertRaises(ValueError):
            validate(c)

    def test_date_rollback(self):
        today = date.today()
        c = Candidate(20.0, 20.0, today.isoformat(), 'x', 'x', 'test')
        with self.assertRaises(ValueError):
            validate(c, today + timedelta(days=1))


if __name__ == '__main__':
    unittest.main()
