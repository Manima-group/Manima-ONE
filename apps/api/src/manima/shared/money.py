from decimal import ROUND_HALF_UP, Decimal

TWO = Decimal("0.01")
THREE = Decimal("0.001")
ZERO = Decimal("0")


def r2(v: Decimal | int | str) -> Decimal:
    return Decimal(str(v)).quantize(TWO, rounding=ROUND_HALF_UP)


def r3(v: Decimal | int | str) -> Decimal:
    return Decimal(str(v)).quantize(THREE, rounding=ROUND_HALF_UP)
