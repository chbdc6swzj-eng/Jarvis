"""Owns the automation's own private copy of the vessels workbook.

The shared team workbook is never opened or written by this code. On first
run, TRACKER_SEED_XLSX (a one-time copy of the current shared file, provided
by the user) is copied to TRACKER_XLSX_PATH; every later run only touches
that private copy.
"""
import logging
import os
import shutil

import openpyxl

from .parser import ShipmentRecord

logger = logging.getLogger(__name__)

_COL_VESSEL = 2
_COL_UNIT_COUNT = 7
_COL_QTY_MT = 8
_COL_ORDER = 11
_COL_DN = 12
_COL_ISOT = 13
_COL_REMARKS = 14

_HEADER_ROW = 4
_FIRST_DATA_ROW = 5


class TrackerError(RuntimeError):
    pass


def ensure_tracker_exists(seed_path: str, tracker_path: str) -> None:
    if os.path.exists(tracker_path):
        return
    if not os.path.exists(seed_path):
        raise TrackerError(
            f"Tracker workbook {tracker_path} does not exist and no seed file was found at "
            f"{seed_path}. Place a one-time copy of the current shared workbook there first."
        )
    os.makedirs(os.path.dirname(tracker_path) or ".", exist_ok=True)
    shutil.copyfile(seed_path, tracker_path)
    logger.info("Seeded tracker workbook %s from %s", tracker_path, seed_path)


def _is_blank_row(ws, row: int) -> bool:
    for col in (_COL_VESSEL, _COL_QTY_MT, _COL_ORDER, _COL_DN, _COL_ISOT):
        if ws.cell(row=row, column=col).value is not None:
            return False
    return True


def _find_blank_rows(ws, count: int, max_scan: int = 5000) -> list[int]:
    rows = []
    row = _FIRST_DATA_ROW
    scanned = 0
    while len(rows) < count and scanned < max_scan:
        if _is_blank_row(ws, row):
            rows.append(row)
        row += 1
        scanned += 1
    if len(rows) < count:
        raise TrackerError(
            "Ran out of pre-numbered template rows in the tracker sheet. "
            "Extend the sheet's S.No/Unit template rows manually, then re-run."
        )
    return rows


def append_shipment(tracker_path: str, sheet_name: str, shipment: ShipmentRecord) -> list[int]:
    if sheet_name not in openpyxl.load_workbook(tracker_path, read_only=True).sheetnames:
        raise TrackerError(
            f"Sheet '{sheet_name}' not found in {tracker_path}. "
            "Add a sheet for this year (matching the existing layout) before running."
        )

    wb = openpyxl.load_workbook(tracker_path)
    ws = wb[sheet_name]

    rows = _find_blank_rows(ws, len(shipment.containers))

    for i, (row, container) in enumerate(zip(rows, shipment.containers)):
        if i == 0:
            ws.cell(row=row, column=_COL_VESSEL, value=shipment.vessel_name)
            ws.cell(row=row, column=_COL_UNIT_COUNT, value=len(shipment.containers))

        if container.net_wt_kg is not None:
            ws.cell(row=row, column=_COL_QTY_MT, value=round(container.net_wt_kg / 1000, 3))
        if shipment.order_number:
            ws.cell(row=row, column=_COL_ORDER, value=int(shipment.order_number))
        if container.delivery_no:
            ws.cell(row=row, column=_COL_DN, value=int(container.delivery_no))
        ws.cell(row=row, column=_COL_ISOT, value=container.container_no)

        remarks = list(container.warnings) + (list(shipment.warnings) if i == 0 else [])
        if remarks:
            ws.cell(row=row, column=_COL_REMARKS, value="NEEDS REVIEW: " + "; ".join(remarks))

    wb.save(tracker_path)
    logger.info(
        "Appended shipment (order %s, vessel %s) to rows %s in %s",
        shipment.order_number, shipment.vessel_name, rows, sheet_name,
    )
    return rows
