import glob
import logging
import os
import subprocess
import tempfile

import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)


class OcrError(RuntimeError):
    pass


def ocr_pdf(pdf_bytes: bytes, dpi: int = 300) -> list[tuple[int, str]]:
    """Render each page of a (scanned) PDF to an image and OCR it.

    Returns a list of (page_number, text), 1-indexed, in page order.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "input.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        prefix = os.path.join(tmpdir, "page")
        try:
            subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), pdf_path, prefix],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError as exc:
            raise OcrError(
                "pdftoppm not found. Install poppler-utils (apt-get install poppler-utils)."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise OcrError(f"pdftoppm failed: {exc.stderr.decode(errors='replace')}") from exc

        image_paths = sorted(glob.glob(prefix + "-*.png"))
        if not image_paths:
            raise OcrError("pdftoppm produced no page images")

        pages = []
        for path in image_paths:
            page_num = int(path.rsplit("-", 1)[-1].split(".")[0])
            with Image.open(path) as img:
                text = pytesseract.image_to_string(img, config="--psm 6")
            pages.append((page_num, text))
        pages.sort(key=lambda p: p[0])
        return pages
