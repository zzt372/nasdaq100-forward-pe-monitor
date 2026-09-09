import unittest
from datetime import date, timedelta

from fetch import parse_search_index, validate


GOOD = '''
<html><body>
1. Nasdaq 100 Forward PE Ratio - trendonify.com
The current rating for Nasdaq 100 Forward PE Ratio is "Undervalued", based on 10-year historical data.
How does the current P/E Ratio compare historically for Nasdaq 100 Forward PE Ratio ?
The current P/E Ratio of 20.7 ranks in the 21.7th percentile over the past decade, placing it in the Undervalued zone by historical standards.
trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio 2026-09-08T00:00:00.0000000
</body></html>
'''


class ParserTests(unittest.TestCase):
    def test_good_dedicated_result(self):
        self.assertEqual(parse_search_index(GOOD), (20.7, 21.7, "2026-09-08"))

    def test_bot_challenge_rejected(self):
        raw = "Unfortunately, bots use DuckDuckGo too. Select all squares containing a duck."
        with self.assertRaises(RuntimeError):
            parse_search_index(raw)

    def test_other_provider_rejected(self):
        raw = GOOD.replace("Nasdaq 100 Forward PE Ratio - trendonify.com", "Nasdaq 100 Forward PE Ratio - example.com")
        with self.assertRaises(ValueError):
            parse_search_index(raw)

    def test_wrong_trendonify_url_rejected(self):
        raw = GOOD.replace(
            "trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio",
            "trendonify.com/united-states/stock-market/nasdaq-100/pe-ratio",
        )
        with self.assertRaises(ValueError):
            parse_search_index(raw)

    def test_invalid_percentile(self):
        with self.assertRaises(ValueError):
            validate(20.0, 101.0, date.today().isoformat())

    def test_date_rollback(self):
        today = date.today()
        with self.assertRaises(ValueError):
            validate(20.0, 20.0, today.isoformat(), today + timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
