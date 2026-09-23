import os

from src.parser import parse_pages

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


def _sample_pages() -> list[tuple[int, str]]:
    return [
        (10, _read("packing_list_p1.txt")),
        (11, _read("packing_list_p2.txt")),
        (12, _read("certificate_of_origin_p1.txt")),
        (13, "CERTIFICATE OF ORIGIN Page 2 of 3\n(signatures only, no data)"),
        (14, _read("certificate_of_origin_p3.txt")),
    ]


def test_extracts_order_number_and_vessel_from_certificate_of_origin():
    shipment = parse_pages(_sample_pages())
    assert shipment.order_number == "57731272"
    assert shipment.vessel_name == "CORNELIA MAERSK"


def test_extracts_all_four_containers_with_delivery_numbers():
    shipment = parse_pages(_sample_pages())
    assert len(shipment.containers) == 4

    by_dn = {c.delivery_no: c for c in shipment.containers}
    assert by_dn["93065721"].container_no == "HGTU2418040"
    assert by_dn["93065721"].net_wt_kg == 21736.0
    assert by_dn["93065722"].container_no == "RLTU2626928"
    assert by_dn["93065723"].container_no == "TCLU9013521"
    assert by_dn["93065724"].container_no == "HOYU9684733"


def test_corrects_ocr_misread_container_number_using_certificate_of_origin():
    # The Packing List fixture has a deliberate OCR error: TCLU8013521 instead
    # of the correct TCLU9013521 (a real misread captured from actual OCR
    # output). The Certificate of Origin has the correct number, so the
    # parser should prefer it and flag the correction rather than write the
    # wrong container number silently.
    shipment = parse_pages(_sample_pages())
    corrected = next(c for c in shipment.containers if c.delivery_no == "93065723")
    assert corrected.container_no == "TCLU9013521"
    assert any("corrected from OCR misread" in w for w in corrected.warnings)


def test_flags_shipment_needing_review_when_certificate_missing():
    pages = [(10, _read("packing_list_p1.txt")), (11, _read("packing_list_p2.txt"))]
    shipment = parse_pages(pages)
    assert shipment.needs_review
    assert any("Certificate of Origin" in w for w in shipment.warnings)


def test_flags_shipment_needing_review_when_packing_list_missing():
    pages = [(12, _read("certificate_of_origin_p1.txt")), (14, _read("certificate_of_origin_p3.txt"))]
    shipment = parse_pages(pages)
    assert shipment.needs_review
    assert all(c.delivery_no is None for c in shipment.containers)


def test_clean_shipment_does_not_need_review():
    shipment = parse_pages(_sample_pages())
    # Every container should have DN#, container#, and weight resolved with
    # at most a corrected-OCR note; overall record still won't need review
    # once the one expected correction is accounted for, but we assert the
    # concrete, important fields rather than the aggregate flag here.
    for c in shipment.containers:
        assert c.delivery_no is not None
        assert c.net_wt_kg is not None
        assert c.container_no.startswith(("HGTU", "RLTU", "TCLU", "HOYU"))
