"""Extract shipment data (vessel, order#, per-container delivery#/qty) from the
OCR'd text of an Eastman shipping document bundle (Bill of Lading + Waybill +
Commercial Invoice + Packing List + Certificate of Origin + Certificates of
Analysis, all scanned into one PDF).

The Certificate of Origin's summary table and header block are the cleanest,
most consistently OCR'd source for vessel name, order number, container
numbers and net weights. The Packing List is the only source for the Eastman
"Delivery No" (DN#) per container, so it is still required, but its container
numbers are cross-checked against the Certificate of Origin and corrected /
flagged when OCR has clearly garbled a digit, rather than trusted blindly.

Only Texanol / this document layout is handled today. If Eastman changes the
document layout, or another product's paperwork looks different, this module
needs new patterns -- it will flag `needs_review` rather than silently write
wrong numbers when it can't confidently parse something.
"""
import re
from dataclasses import dataclass, field

_CERT_ORDER_RE = re.compile(r"ADTL\.?\s*REFERENCE\s*NO\.?\s*1\s*:?\s*0*(\d{5,10})", re.I)
_CERT_VESSEL_RE = re.compile(r"SHIPPED\s*VIA\s*:?\s*([A-Z0-9][A-Z0-9 .'\-]*?)\s+VOY", re.I)

# Certificate of Origin container/weight table, one line per container, e.g.:
#   "HGTU24 18040 1 BLK 21736.0000 KG 21736.0000 KG 5752541, 5752546, 5754055."
# OCR sometimes injects a stray space inside the container number. The digit
# group is pinned to exactly 7 digits (ISO 6346 container numbers are always
# 4 letters + 7 digits) -- an open-ended range here would also swallow the
# "1" from the following "1 BLK" packages column.
_CERT_CONTAINER_LINE_RE = re.compile(
    r"([A-Z]{3}\s?U)\s?((?:\d\s?){6}\d).*?([\d,]+\.\d{2,4})\s*KG.*?([\d,]+\.\d{2,4})\s*KG",
    re.I,
)

# Packing List per-container block, e.g.:
#   Delivery No : 93065721
#   ...
#   Container No : HGTU2418040
#   ...
#   ***Product Total H 21736.000 0.000 21736.000 KG
_PACKING_LIST_BLOCK_RE = re.compile(
    r"Delivery\s*No\s*[:>]?\s*(\d{5,10}).*?"
    r"Container\s*No\s*:?\s*([A-Z]{3}\s?U\s?(?:\d\s?){6}\d).*?"
    # The "colon" after "Product Total" is often OCR-garbled into a stray
    # digit or letter (e.g. "Product Total 4 21745..."), not just punctuation
    # -- so we skip up to a few non-space characters rather than [^\d], which
    # would otherwise fail here and let the lazy match above run on into the
    # next container's block entirely.
    r"Product\s*Total\s*\S{0,3}\s+([\d,]+\.\d{2,4})\s+([\d,]+\.\d{2,4})\s+([\d,]+\.\d{2,4})\s*KG",
    re.I | re.S,
)


def _clean_container_no(raw: str) -> str:
    raw = raw.upper()
    letters = re.match(r"[A-Z]{3}\s?U", raw)
    prefix = letters.group(0).replace(" ", "") if letters else raw[:4]
    digits = re.sub(r"\D", "", raw[len(letters.group(0)) if letters else 4:])
    return prefix + digits


def _digit_distance(a: str, b: str) -> int:
    if len(a) != len(b):
        return max(len(a), len(b))
    return sum(1 for x, y in zip(a, b) if x != y)


@dataclass
class ContainerLine:
    container_no: str
    delivery_no: str | None = None
    net_wt_kg: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ShipmentRecord:
    order_number: str | None = None
    vessel_name: str | None = None
    containers: list[ContainerLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        if not self.order_number or not self.vessel_name or not self.containers:
            return True
        if self.warnings:
            return True
        return any(c.warnings for c in self.containers)


def _select_pages(pages: list[tuple[int, str]], keywords: tuple[str, ...]) -> str:
    """Concatenate pages whose text matches any of the given keywords.

    Multiple keywords, not just the document's printed title, because a
    stylised header (e.g. a title wrapped in asterisks) is exactly the kind
    of text OCR mangles first -- "*****PACKING LIST*****" was read back as
    "sees*D ACKING LIST*****" on a real sample, dropping "PACKING LIST"
    entirely even though the rest of that page OCR'd cleanly. A second,
    plainer marker from the same page template is used as a fallback.
    """
    matched = [text for _, text in sorted(pages) if any(k in text.upper() for k in keywords)]
    return "\n".join(matched)


def _parse_certificate_of_origin(text: str) -> tuple[str | None, str | None, list[tuple[str, float]]]:
    order_match = _CERT_ORDER_RE.search(text)
    vessel_match = _CERT_VESSEL_RE.search(text)
    order_number = order_match.group(1) if order_match else None
    vessel_name = vessel_match.group(1).strip() if vessel_match else None

    containers = []
    for m in _CERT_CONTAINER_LINE_RE.finditer(text):
        container_no = _clean_container_no(m.group(1) + m.group(2))
        net_wt = float(m.group(4).replace(",", ""))
        containers.append((container_no, net_wt))
    return order_number, vessel_name, containers


def _parse_packing_list(text: str) -> list[ContainerLine]:
    lines = []
    for m in _PACKING_LIST_BLOCK_RE.finditer(text):
        delivery_no = m.group(1)
        container_no = _clean_container_no(m.group(2))
        net_wt = float(m.group(5).replace(",", ""))
        lines.append(ContainerLine(container_no=container_no, delivery_no=delivery_no, net_wt_kg=net_wt))
    return lines


def _reconcile(
    order_number: str | None,
    vessel_name: str | None,
    cert_containers: list[tuple[str, float]],
    pl_containers: list[ContainerLine],
) -> ShipmentRecord:
    record = ShipmentRecord(order_number=order_number, vessel_name=vessel_name)

    if not cert_containers and not pl_containers:
        record.warnings.append("No container data found in either the Packing List or Certificate of Origin")
        return record

    cert_by_no = {no: wt for no, wt in cert_containers}

    if not pl_containers:
        record.warnings.append("Delivery No unavailable (no Packing List match) for all containers")
        for no, wt in cert_containers:
            record.containers.append(
                ContainerLine(container_no=no, net_wt_kg=wt, warnings=["DN# missing: check Packing List manually"])
            )
        return record

    for line in pl_containers:
        if line.container_no in cert_by_no:
            # Exact match against the Certificate of Origin: high confidence.
            line.net_wt_kg = cert_by_no[line.container_no]
        else:
            # Try a fuzzy match to catch a single OCR digit/letter misread.
            best = min(
                cert_by_no,
                key=lambda c: _digit_distance(c, line.container_no),
                default=None,
            )
            if best is not None and _digit_distance(best, line.container_no) <= 1:
                line.warnings.append(
                    f"Container # corrected from OCR misread ({line.container_no} -> {best})"
                )
                line.container_no = best
                line.net_wt_kg = cert_by_no[best]
            else:
                line.warnings.append(
                    "Container # not confirmed against Certificate of Origin -- verify manually"
                )
        record.containers.append(line)

    if len(cert_containers) not in (0, len(pl_containers)):
        record.warnings.append(
            f"Packing List has {len(pl_containers)} containers but Certificate of Origin lists {len(cert_containers)}"
        )

    return record


def parse_pages(pages: list[tuple[int, str]]) -> ShipmentRecord:
    cert_text = _select_pages(pages, ("CERTIFICATE OF ORIGIN",))
    pl_text = _select_pages(pages, ("PACKING LIST", "SYS ID: PRD", "PRODUCT TOTAL"))

    order_number, vessel_name, cert_containers = (
        _parse_certificate_of_origin(cert_text) if cert_text else (None, None, [])
    )
    pl_containers = _parse_packing_list(pl_text) if pl_text else []

    record = _reconcile(order_number, vessel_name, cert_containers, pl_containers)

    if not cert_text:
        record.warnings.append("No Certificate of Origin page found (vessel/order# unverifiable)")
    if not pl_text:
        record.warnings.append("No Packing List page found (DN# unavailable)")

    return record
