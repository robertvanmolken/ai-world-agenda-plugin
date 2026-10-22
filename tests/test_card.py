import io
import tempfile
import unittest
from pathlib import Path

try:
    import segno
    from PIL import Image
    from scripts import make_card
except ImportError:  # dev-only dependencies (requirements-dev.txt)
    make_card = None


@unittest.skipIf(make_card is None, "card dependencies not installed")
class CardTests(unittest.TestCase):
    def test_files_and_sizes(self):
        with tempfile.TemporaryDirectory() as t:
            make_card.main(Path(t))
            for n in ("card-front.png", "card-back.png"):
                self.assertEqual((1074, 720), Image.open(Path(t) / n).size)
            self.assertTrue((Path(t) / "card-print.pdf").read_bytes().startswith(b"%PDF"))
            self.assertTrue((Path(t) / "qr-aiworld.svg").exists())

    def test_qr_encodes_live_url(self):
        self.assertEqual("https://aiworld.exoblock.it/", make_card.URL)
        img = make_card.qr_image(31)
        self.assertGreaterEqual(img.width, make_card.mm(31) - 40)
        code = segno.make(make_card.URL, error="q")
        self.assertEqual("q", code.error.lower())

    def test_og_image_has_qr(self):
        with tempfile.TemporaryDirectory() as t:
            make_card.main(Path(t))
            self.assertEqual((1200, 630), Image.open(Path(t) / "og-image.png").size)
