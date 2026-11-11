"""Resource fallback for the same compositor on desktop and Linux CI."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'motion'))
import engine


class MotionFonts(unittest.TestCase):
    def setUp(self):
        engine.font.cache_clear()
        self.addCleanup(engine.font.cache_clear)

    def test_preferred_desktop_font_keeps_priority(self):
        with patch.object(engine.ImageFont, 'truetype', return_value='preferred') as load:
            self.assertEqual(engine.font(24, 'heavy'), 'preferred')
        self.assertEqual(load.call_args.args, (str(engine.FONTS / 'Arial Black.ttf'), 24))
        self.assertEqual(load.call_count, 1)

    def test_missing_desktop_font_uses_installed_free_font(self):
        with patch.object(engine.ImageFont, 'truetype', side_effect=[OSError('absent'), 'fallback']) as load:
            self.assertEqual(engine.font(24, 'condensed'), 'fallback')
        self.assertEqual(load.call_args.args, ('/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf', 24))

    def test_missing_both_fonts_reports_required_resource(self):
        with patch.object(engine.ImageFont, 'truetype', side_effect=OSError('absent')):
            with self.assertRaisesRegex(OSError, 'FRAME_FONT_DIR.*fonts-dejavu-core'):
                engine.font(24)


if __name__ == '__main__':
    unittest.main()
