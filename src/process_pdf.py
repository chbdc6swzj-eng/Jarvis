"""Process one or more Eastman shipment PDFs directly into the tracker
workbook, without needing the Outlook/Microsoft Graph mail integration.

Use this while the Azure AD app registration isn't set up yet (or forever,
if you'd rather just hand over PDFs than automate mailbox polling): run it
by hand against a downloaded attachment, or have it run against a file
someone hands you.

    python -m src.process_pdf path/to/document.pdf [more.pdf ...]
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from .ocr import OcrError, ocr_pdf
from .parser import ShipmentRecord, parse_pages
from .tracker_sheet import TrackerError, append_shipment, ensure_tracker_exists

load_dotenv()
logger = logging.getLogger("process_pdf")


def process_one(pdf_path: str, tracker_seed: str, tracker_path: str, sheet_name_template: str) -> tuple[ShipmentRecord, list[int]]:
    ensure_tracker_exists(tracker_seed, tracker_path)

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    pages = ocr_pdf(pdf_bytes)
    shipment = parse_pages(pages)

    if not shipment.containers:
        raise RuntimeError(
            f"Could not extract any container data from {pdf_path}: "
            + ("; ".join(shipment.warnings) or "no specific warnings")
        )

    sheet_name = sheet_name_template.format(year=datetime.now(timezone.utc).year)
    rows = append_shipment(tracker_path, sheet_name, shipment)
    return shipment, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", help="Path(s) to the scanned Eastman document PDF(s)")
    parser.add_argument(
        "--tracker-seed",
        default=os.environ.get("TRACKER_SEED_XLSX", "./data/EASTMAN_ORDER_STATUS_seed.xlsx"),
        help="One-time seed copy of the shared workbook (only read if the tracker doesn't exist yet)",
    )
    parser.add_argument(
        "--tracker-path",
        default=os.environ.get("TRACKER_XLSX_PATH", "./data/EASTMAN_ORDER_STATUS_tracker.xlsx"),
        help="The private working copy this script owns and appends to",
    )
    parser.add_argument(
        "--sheet-name",
        default=os.environ.get("TRACKER_SHEET_NAME", "Incoming vessels-{year}"),
        help="Sheet name template inside the tracker workbook ({year} is substituted)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    exit_code = 0
    for pdf_path in args.pdfs:
        try:
            shipment, rows = process_one(pdf_path, args.tracker_seed, args.tracker_path, args.sheet_name)
            status = "NEEDS REVIEW" if shipment.needs_review else "OK"
            logger.info(
                "[%s] %s: order#=%s vessel=%s containers=%d -> rows %s%s",
                status, pdf_path, shipment.order_number, shipment.vessel_name,
                len(shipment.containers), rows,
                (" | " + "; ".join(shipment.warnings)) if shipment.warnings else "",
            )
        except (OcrError, TrackerError, RuntimeError) as exc:
            logger.error("%s: %s", pdf_path, exc)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
