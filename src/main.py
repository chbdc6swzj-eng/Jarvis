import logging
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from . import graph_auth, graph_mail, tracker_sheet
from .config import load_config
from .ocr import OcrError, ocr_pdf
from .parser import parse_pages
from .store import ProcessedStore

logger = logging.getLogger("eastman_tracker")

_STALE_LOCK_SECONDS = 30 * 60


@contextmanager
def _run_lock(path: str):
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < _STALE_LOCK_SECONDS:
        raise RuntimeError(f"Another run appears to be in progress (lock file {path}); exiting")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(str(os.getpid()))
    try:
        yield
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def run() -> int:
    config = load_config()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tracker_sheet.ensure_tracker_exists(config.tracker_seed_xlsx, config.tracker_xlsx_path)
    store = ProcessedStore(config.state_file)

    token = graph_auth.get_access_token(config)
    since = graph_mail.default_lookback(config.poll_lookback_days)

    processed, flagged, errors = 0, 0, 0

    with _run_lock(config.state_file + ".lock"):
        for message in graph_mail.list_candidate_messages(
            token, config.mailbox_user, config.subject_keyword, since
        ):
            if store.is_processed(message.id):
                continue

            logger.info("New matching email: %s (%s)", message.subject, message.id)
            try:
                attachments = graph_mail.list_pdf_attachments(token, config.mailbox_user, message.id)
                if not attachments:
                    logger.warning("Message %s matched subject but has no PDF attachment", message.id)
                    store.mark_processed(message.id)
                    continue

                any_written = False
                for attachment in attachments:
                    pdf_bytes = graph_mail.download_attachment(
                        token, config.mailbox_user, message.id, attachment.id
                    )
                    pages = ocr_pdf(pdf_bytes)
                    shipment = parse_pages(pages)

                    if not shipment.containers:
                        logger.error(
                            "Could not extract any container data from %s (message %s): %s",
                            attachment.name, message.id, "; ".join(shipment.warnings),
                        )
                        errors += 1
                        continue

                    year = datetime.now(timezone.utc).year
                    sheet_name = config.tracker_sheet_name(year)
                    tracker_sheet.append_shipment(config.tracker_xlsx_path, sheet_name, shipment)
                    any_written = True

                    if shipment.needs_review:
                        flagged += 1
                        logger.warning(
                            "Shipment from %s written with NEEDS REVIEW flags: %s",
                            attachment.name, "; ".join(shipment.warnings) or "see per-row remarks",
                        )
                    else:
                        processed += 1

                if any_written:
                    graph_mail.mark_message_read(token, config.mailbox_user, message.id)
                store.mark_processed(message.id)

            except OcrError as exc:
                logger.error("OCR failed for message %s: %s", message.id, exc)
                errors += 1
            except Exception:
                logger.exception("Unexpected error processing message %s", message.id)
                errors += 1

    logger.info(
        "Run complete: %d shipment(s) written cleanly, %d flagged for review, %d error(s)",
        processed, flagged, errors,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
