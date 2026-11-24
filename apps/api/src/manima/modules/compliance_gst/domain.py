"""GST domain rules: state codes, GSTIN checksum, line tax computation (SCHEMA_DESIGN §8). Pure, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from manima.shared.money import ZERO, r2

STATES = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
    "96": "Other Country",
}
UNION_TERRITORIES_UTGST = {"04", "26", "31", "35", "38"}
VALID_RATES = {Decimal(x) for x in ("0", "0.1", "0.25", "1.5", "3", "5", "6", "12", "18", "28", "40")}

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_checksum_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        v = _CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return _CHARS[(36 - total % 36) % 36]


def validate_gstin(gstin: str) -> str | None:
    """Return an error message, or None when valid."""
    g = (gstin or "").strip().upper()
    if len(g) != 15 or any(c not in _CHARS for c in g):
        return "GSTIN must be 15 characters (digits and capital letters)."
    if g[:2] not in STATES:
        return "GSTIN state code is invalid."
    if not (g[2:7].isalpha() and g[7:11].isdigit() and g[11].isalpha()):
        return "GSTIN PAN section is invalid."
    if gstin_checksum_char(g[:14]) != g[14]:
        return "GSTIN checksum does not match."
    return None


SCENARIOS = ("b2b", "b2c", "export_with_tax", "export_lut", "sez_with_tax", "sez_lut", "unregistered")
ZERO_RATED = ("export_lut", "sez_lut")
INTERSTATE_FORCED = ("export_with_tax", "export_lut", "sez_with_tax", "sez_lut")


@dataclass
class LineIn:
    qty: Decimal
    rate: Decimal
    discount_pct: Decimal = ZERO
    gst_rate: Decimal = ZERO
    cess_rate: Decimal = ZERO


@dataclass
class LineTax:
    taxable_value: Decimal
    cgst_rate: Decimal
    cgst: Decimal
    sgst_rate: Decimal
    sgst: Decimal
    igst_rate: Decimal
    igst: Decimal
    cess: Decimal
    total: Decimal
    gross: Decimal
    discount: Decimal


@dataclass
class Totals:
    subtotal: Decimal = ZERO
    discount_total: Decimal = ZERO
    taxable_total: Decimal = ZERO
    cgst_total: Decimal = ZERO
    sgst_total: Decimal = ZERO
    igst_total: Decimal = ZERO
    cess_total: Decimal = ZERO
    tax_total: Decimal = ZERO
    round_off: Decimal = ZERO
    grand_total: Decimal = ZERO
    lines: list[LineTax] = field(default_factory=list)


def is_intra_state(supplier_state: str | None, place_of_supply: str | None, scenario: str = "b2b") -> bool:
    if scenario in INTERSTATE_FORCED:
        return False
    return bool(supplier_state) and supplier_state == place_of_supply


def compute_line(line: LineIn, *, intra: bool, zero_rated: bool = False, no_tax: bool = False) -> LineTax:
    gross = r2(line.qty * line.rate)
    discount = r2(gross * line.discount_pct / Decimal(100))
    taxable = gross - discount
    rate = ZERO if (zero_rated or no_tax) else line.gst_rate
    cess_rate = ZERO if (zero_rated or no_tax) else line.cess_rate
    if intra:
        half = rate / 2
        cgst = sgst = r2(taxable * half / 100)
        igst, cgst_rate, sgst_rate, igst_rate = ZERO, half, half, ZERO
    else:
        igst = r2(taxable * rate / 100)
        cgst = sgst = cgst_rate = sgst_rate = ZERO
        igst_rate = rate
    cess = r2(taxable * cess_rate / 100)
    return LineTax(
        taxable,
        cgst_rate,
        cgst,
        sgst_rate,
        sgst,
        igst_rate,
        igst,
        cess,
        taxable + cgst + sgst + igst + cess,
        gross,
        discount,
    )


def compute_document(
    lines: list[LineIn],
    *,
    supplier_state: str | None,
    place_of_supply: str | None,
    scenario: str = "b2b",
    composition: bool = False,
    round_to_rupee: bool = True,
) -> Totals:
    intra = is_intra_state(supplier_state, place_of_supply, scenario)
    t = Totals()
    for ln in lines:
        lt = compute_line(ln, intra=intra, zero_rated=scenario in ZERO_RATED, no_tax=composition)
        t.lines.append(lt)
        t.subtotal += lt.gross
        t.discount_total += lt.discount
        t.taxable_total += lt.taxable_value
        t.cgst_total += lt.cgst
        t.sgst_total += lt.sgst
        t.igst_total += lt.igst
        t.cess_total += lt.cess
    t.tax_total = t.cgst_total + t.sgst_total + t.igst_total + t.cess_total
    raw = t.taxable_total + t.tax_total
    if round_to_rupee:
        rounded = raw.quantize(Decimal("1"), rounding="ROUND_HALF_UP")
        t.round_off = rounded - raw
        t.grand_total = r2(rounded)
    else:
        t.grand_total = r2(raw)
    return t


def financial_year(d, start_month: int = 4) -> str:
    """'26-27' style FY label (keeps invoice numbers within 16 characters)."""
    y = d.year if d.month >= start_month else d.year - 1
    return f"{y % 100:02d}-{(y + 1) % 100:02d}"
