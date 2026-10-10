import unittest
from pathlib import Path
from app.catalog_parser import parse_catalog_html

class ParserTest(unittest.TestCase):
    def test_minimal_tile(self):
        p = Path('/tmp/catalog_test.html')
        p.write_text('''<div id="session-123" class="rf-tile-wrapper session-type-learning-session content-area-oracle-ai-data-platform area-of-interest-integration" data-test="rf-tile"><div class="rf-tile"><div class="rf-tile-body"><h4 class="rf-tile-title"><a>Example Integration [LRN9999]</a></h4><div><span class="session-date">Wednesday, Oct 28</span><span class="session-time">1:00 PM - 1:45 PM PDT</span></div><p class="rf-tile-info rf-tile-line-two">Example description.</p></div></div></div>''', encoding='utf-8')
        s = parse_catalog_html(p)
        self.assertEqual(1, len(s))
        self.assertEqual('LRN9999', s[0]['code'])
        self.assertEqual('2026-10-28', s[0]['date'])
        self.assertEqual('13:00', s[0]['startTime'])
        self.assertIn('Integration', s[0]['areasOfInterest'])

if __name__ == '__main__': unittest.main()
