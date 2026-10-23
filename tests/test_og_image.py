import tempfile
import unittest
from pathlib import Path

try:
    import cv2
    from PIL import Image
    from scripts import make_og_image
except ImportError:  # dev-only dependencies (requirements-dev.txt)
    make_og_image = None


@unittest.skipIf(make_og_image is None, "share image dependencies not installed")
class OgImageTests(unittest.TestCase):
    def test_size_and_qr(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "og.png"
            make_og_image.main(out)
            self.assertEqual((1200, 630), Image.open(out).size)
            self.assertEqual("https://aiworld.exoblock.it/", cv2.QRCodeDetector().detectAndDecode(cv2.imread(str(out)))[0])
