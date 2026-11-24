from datetime import date
from decimal import Decimal as D

import pytest

from manima.core.entitlements import verb_of
from manima.core.provisioning import topo_order
from manima.modules.compliance_gst.domain import (
    LineIn,
    compute_document,
    financial_year,
    gstin_checksum_char,
    validate_gstin,
)
from manima.modules.invoicing.module import derive_payment_status


def test_intra_state_splits_cgst_sgst():
    t = compute_document(
        [LineIn(D("2"), D("1000"), D("0"), D("18"))], supplier_state="36", place_of_supply="36"
    )
    ln = t.lines[0]
    assert (ln.taxable_value, ln.cgst, ln.sgst, ln.igst) == (D("2000.00"), D("180.00"), D("180.00"), D("0"))
    assert ln.cgst_rate == D("9") and t.grand_total == D("2360.00")


def test_inter_state_igst():
    t = compute_document(
        [LineIn(D("1"), D("1000"), D("0"), D("18"))], supplier_state="36", place_of_supply="27"
    )
    assert t.igst_total == D("180.00") and t.cgst_total == 0 and t.grand_total == D("1180.00")


def test_discount_and_per_line_rounding_then_round_off():
    t = compute_document(
        [LineIn(D("3"), D("333.33"), D("10"), D("18")), LineIn(D("1"), D("99.99"), D("0"), D("5"))],
        supplier_state="36",
        place_of_supply="36",
    )
    # line1 gross 999.99, discount 100.00, taxable 899.99, cgst=sgst=81.00 (rounded per line)
    assert t.lines[0].discount == D("100.00") and t.lines[0].taxable_value == D("899.99")
    assert t.lines[0].cgst == D("81.00")
    raw = t.taxable_total + t.tax_total
    assert t.grand_total == raw.quantize(D("1"), rounding="ROUND_HALF_UP")
    assert t.round_off == t.grand_total - raw


@pytest.mark.parametrize("scenario", ["export_lut", "sez_lut"])
def test_zero_rated_scenarios(scenario):
    t = compute_document(
        [LineIn(D("1"), D("1000"), D("0"), D("18"))],
        supplier_state="36",
        place_of_supply="96",
        scenario=scenario,
    )
    assert t.tax_total == 0 and t.grand_total == D("1000.00")


def test_export_with_tax_is_igst_even_if_states_match():
    t = compute_document(
        [LineIn(D("1"), D("100"), D("0"), D("18"))],
        supplier_state="36",
        place_of_supply="36",
        scenario="export_with_tax",
    )
    assert t.igst_total == D("18.00")


def test_composition_no_tax():
    t = compute_document(
        [LineIn(D("1"), D("100"), D("0"), D("18"))],
        supplier_state="36",
        place_of_supply="36",
        composition=True,
    )
    assert t.tax_total == 0


def test_gstin_validation():
    base = "36AABCS1429B1Z"
    good = base + gstin_checksum_char(base)
    assert validate_gstin(good) is None
    bad = base + ("A" if good[-1] != "A" else "B")
    assert "checksum" in validate_gstin(bad)
    assert validate_gstin("99AABCS1429B1Z5") is not None
    assert validate_gstin("short") is not None
    assert validate_gstin("27AAPFU0939F1ZV") is None  # published example GSTIN


def test_financial_year_label():
    assert financial_year(date(2026, 4, 1)) == "26-27"
    assert financial_year(date(2027, 3, 31)) == "26-27"
    assert financial_year(date(2026, 1, 15), start_month=1) == "26-27"


@pytest.mark.parametrize(
    "net,paid,expected",
    [
        (D("100"), D("0"), "unpaid"),
        (D("100"), D("40"), "partially_paid"),
        (D("100"), D("100"), "paid"),
        (D("100"), D("120"), "overpaid"),
        (D("0"), D("0"), "paid"),
    ],
)
def test_payment_status_derivation(net, paid, expected):
    assert derive_payment_status(net, paid) == expected


def test_verbs():
    assert verb_of("crm.lead.read_own") == "read"
    assert verb_of("crm.lead.create") == "create"
    assert verb_of("invoicing.invoice.issue") == "invoke"
    assert verb_of("invoicing.invoice.cancel") == "cancel"


def test_module_topological_order():
    order = topo_order(["payments", "invoicing", "sales", "crm", "catalog", "compliance_gst"])
    assert order.index("crm") < order.index("sales") and order.index("invoicing") < order.index("payments")
