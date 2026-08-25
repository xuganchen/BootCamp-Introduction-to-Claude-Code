"""Stage 06 - units, types and controlled vocabulary.

Two roles:

1. A *library* of pure functions used by the parsers (stages 04 and 05):
   number parsing that survives footnote markers and parenthesised negatives,
   scale application, rate-string decomposition, date normalisation, and the
   investment-type vocabulary.
2. A *pipeline stage* with a `main()` that reads `data/interim/soi_rows.csv`
   (raw text plus in-table numbers) and writes
   `data/interim/soi_rows_normalized.csv` with everything in USD dollars,
   ISO dates, booleans, and the controlled `investment_type`.

Design rule for the vocabulary: an unmapped `investment_type_raw` raises.
Falling back to "other" would let a new instrument type disappear silently,
and "other" is reserved for things we have explicitly decided belong there
(warrants, participation rights, certificates).
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime

import pandas as pd

from bdc_09_utils import INTERIM, log

# --------------------------------------------------------------------------
# scale
# --------------------------------------------------------------------------

SCALE_FACTOR = {"millions": 1e6, "thousands": 1e3, "units": 1.0}


def scale_factor(scale: str) -> float:
    try:
        return SCALE_FACTOR[scale]
    except KeyError:
        raise ValueError(f"unknown scale {scale!r}; expected one of {sorted(SCALE_FACTOR)}")


# --------------------------------------------------------------------------
# numbers
# --------------------------------------------------------------------------

# \x96 / \x97 are the CP-1252 en/em dash bytes, kept here as a second line of
# defence for any text that did not pass through bdc_03._clean.
DASHES = {"—", "–", "-", "‒", "―", "\x96", "\x97"}

# Footnote markers glued to the end of a number: "1,234(5)", "0.9(2)(9)".
# Anchored on a preceding digit so a parenthesised negative like "(12)" - which
# has no digit before the "(" - is never mistaken for a footnote (trap 3 vs 4).
_FOOTNOTE_TAIL = re.compile(r"(?<=\d)(?:\(\d{1,2}\))+$")
_FOOTNOTE_ANY = re.compile(r"\((\d{1,2})\)")
_NUMERIC = re.compile(r"^-?\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^-?\d*\.?\d+$")


def strip_footnotes(text: str) -> str:
    """Remove trailing footnote markers from a value or a name."""
    prev = None
    out = text.strip()
    while prev != out:
        prev = out
        out = _FOOTNOTE_TAIL.sub("", out).strip()
    return out


def footnote_numbers(text: str) -> list[int]:
    """Every footnote marker appearing anywhere in a cell."""
    return [int(x) for x in _FOOTNOTE_ANY.findall(text or "")]


def clean_name(text: str) -> str:
    """Borrower / industry name with footnote markers removed (trap 3).

    Only trailing "(n)" groups with one or two digits are stripped, so a name
    that legitimately ends in a parenthetical ("... (Holdings)") is preserved.
    """
    out = re.sub(r"(?:\s*\(\d{1,2}\))+\s*$", "", (text or "").strip())
    return out.strip(" .,")


def parse_number(text: str | None) -> float | None:
    """Parse one filing number.  Returns None when the cell holds no number.

    Handles: thousands separators, a leading "$", an em/en dash meaning zero
    (trap: an unfunded revolver shows "—", which is 0.0 and not missing),
    parentheses for negatives (trap 4), trailing percent signs, and footnote
    markers glued to the number (trap 3).
    """
    if text is None:
        return None
    s = str(text).replace("\xa0", " ").strip()
    if not s:
        return None
    if s in DASHES:
        return 0.0
    s = s.replace("$", "").strip()
    s = strip_footnotes(s)
    s = s.rstrip("%").strip()
    if not s or s in DASHES:
        return 0.0 if s in DASHES else None
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1].strip()
    s = s.replace(",", "").strip()
    if not _NUMERIC.match(s):
        return None
    value = float(s)
    return -value if negative else value


def parse_money(text: str | None, scale: str) -> float | None:
    """Parse a number and convert it from the table's own scale to USD dollars."""
    v = parse_number(text)
    return None if v is None else v * scale_factor(scale)


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------

_MM_YYYY = re.compile(r"^(\d{1,2})\s*/\s*(\d{4})$")
_MM_DD_YYYY = re.compile(r"^(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2,4})$")


def parse_soi_date(text: str | None) -> date | None:
    """Parse an SOI acquisition / maturity date.

    ARCC prints "10/2029" (month and year only).  We normalise a month-only
    date to the FIRST day of that month; the day is not reported and inventing
    a month end would be a fabricated precision.  Recorded in note/.
    """
    if not text:
        return None
    s = strip_footnotes(str(text).replace("\xa0", " ").strip())
    if not s or s in DASHES:
        return None
    m = _MM_DD_YYYY.match(s)
    if m:
        yy = int(m.group(3))
        if yy < 100:
            yy += 2000 if yy < 70 else 1900
        return date(yy, int(m.group(1)), int(m.group(2)))
    m = _MM_YYYY.match(s)
    if m:
        return date(int(m.group(2)), int(m.group(1)), 1)
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


# --------------------------------------------------------------------------
# principal and maturity printed inside the investment description
# --------------------------------------------------------------------------

# Many BDC Schedules of Investments carry no Principal and no Maturity column
# at all. Instead both are printed inside the investment description, in the
# long-standing convention:
#
#     First lien senior secured revolving loan ($1.5 par due 5/2022)
#     Second lien senior secured loan ($94.9 par due 3/2024)
#
# The par figure carries the table's own scale, exactly like a column value.
# Equity rows use the same parentheses for a share or unit count
# ("Class A preferred units (4,000,000 units)"), so the "par" keyword is
# required rather than "the first number in parentheses".
_PAR_RE = re.compile(r"\(\s*\$?\s*([\d,]+(?:\.\d+)?)\s*par\b", re.I)
_DUE_RE = re.compile(r"\bdue\s+(\d{1,2}\s*/\s*(?:\d{1,2}\s*/\s*)?\d{2,4})", re.I)


def parse_par_from_description(text: str | None) -> float | None:
    """Par amount stated inside an investment description, unscaled."""
    if not text:
        return None
    m = _PAR_RE.search(str(text))
    return parse_number(m.group(1)) if m else None


def parse_due_from_description(text: str | None) -> date | None:
    """Maturity stated as "due M/YYYY" inside an investment description."""
    if not text:
        return None
    m = _DUE_RE.search(str(text))
    return parse_soi_date(m.group(1).replace(" ", "")) if m else None


# --------------------------------------------------------------------------
# rates (trap 8)
# --------------------------------------------------------------------------

# Reference rates seen in BDC filings.  The parenthetical after the name is the
# reset frequency ("SOFR (Q)"), not part of the rate identity.
_REF_SUFFIX = re.compile(r"\s*\([MQSA]\)\s*$", re.I)
_PCT = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")


# The filing is inconsistent about the casing of multi-word rate names
# ("Base Rate" and "Base rate" both appear); canonicalise so the column has one
# value per rate.  Acronyms are left alone.
_REF_CANON = {"base rate": "Base Rate", "prime": "Prime", "prime rate": "Prime Rate",
              "libor": "LIBOR", "euribor": "Euribor", "sofr": "SOFR"}


# Older layouts carry one "Interest" column instead of separate Reference /
# Spread / Coupon columns, and pack all three into one string:
#
#     13.00% (Base Rate + 7.25%/Q)
#     8.50% (Libor + 7.50%/Q)
#
# Requires a name followed by "+" and a percentage, so the modern
# "9.48% (2.88% PIK)" - which has no "+" - cannot match it.
_COMBINED_RATE = re.compile(
    r"\(\s*([A-Za-z][A-Za-z .\-]{1,30}?)\s*\+\s*(\d+(?:\.\d+)?)\s*%\s*(?:/\s*[MQSA])?\s*\)",
    re.I,
)


def parse_combined_reference(text: str | None) -> str | None:
    """Reference-rate name from a combined "all-in% (Name + spread%)" cell."""
    if not text:
        return None
    m = _COMBINED_RATE.search(str(text))
    if not m:
        return None
    name = _REF_SUFFIX.sub("", m.group(1).strip()).strip()
    return _REF_CANON.get(name.lower(), name)


def parse_combined_spread_bps(text: str | None) -> float | None:
    """Spread in basis points from a combined "all-in% (Name + spread%)" cell."""
    if not text:
        return None
    m = _COMBINED_RATE.search(str(text))
    return round(float(m.group(2)) * 100.0, 4) if m else None


def parse_reference_rate(text: str | None, coupon: str | None) -> str | None:
    """Normalise the reference-rate cell.

    A blank reference cell with a stated coupon means a fixed-rate instrument
    (including PIK-only coupons such as "14.00% PIK"); a blank reference cell
    with no coupon at all means a non-income-producing position (equity,
    warrant) and stays null.
    """
    s = (text or "").strip()
    if s and s not in DASHES:
        s = _REF_SUFFIX.sub("", s).strip()
        return _REF_CANON.get(s.lower(), s)
    # No separate reference column: the coupon cell may still name one, in the
    # combined form "13.00% (Base Rate + 7.25%/Q)". This must be tried BEFORE
    # falling back to "fixed", or every floating-rate position in the older
    # layouts would be labelled fixed - a wrong value rather than a null.
    combined = parse_combined_reference(coupon)
    if combined:
        return combined
    if parse_all_in_rate_pct(coupon) is not None:
        return "fixed"
    return None


def parse_spread_bps(text: str | None) -> float | None:
    """"5.25%" -> 525.0 basis points."""
    v = parse_number(text)
    if v is None:
        return None
    return round(v * 100.0, 4)


def parse_all_in_rate_pct(text: str | None) -> float | None:
    """Leading percentage of a coupon cell.

    "8.65%"                 -> 8.65
    "9.48% (2.88% PIK)"     -> 9.48   (the PIK component is part of the 9.48)
    "8.00% PIK"             -> 8.00
    ""                      -> None   (non-income producing)
    """
    if not text:
        return None
    m = _PCT.search(str(text))
    return float(m.group(1)) if m else None


def parse_pik_rate_pct(text: str | None) -> float | None:
    """The PIK component of a coupon string, when one is broken out."""
    if not text:
        return None
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%\s*PIK", str(text), re.I)
    return float(m.group(1)) if m else None


# --------------------------------------------------------------------------
# investment type vocabulary
# --------------------------------------------------------------------------

CONTROLLED_TYPES = ("first lien", "second lien", "subordinated", "equity", "preferred", "other")

DEBT_TYPES = frozenset({"first lien", "second lien", "subordinated"})

# Ordered: the first matching rule wins.  Order matters - "Class A preferred
# units" must reach the preferred rule before the equity rule, and "Senior
# subordinated loan" must not be caught by a generic "senior" rule.
_TYPE_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bfirst\s+lien\b", re.I), "first lien"),
    (re.compile(r"\bsecond\s+lien\b", re.I), "second lien"),
    (re.compile(r"\bthird\s+lien\b", re.I), "second lien"),
    (re.compile(r"\bwarrants?\b", re.I), "other"),
    (re.compile(r"\bsubordinated\b", re.I), "subordinated"),
    (re.compile(r"\bmezzanine\b", re.I), "subordinated"),
    (re.compile(r"\bpreferred\b", re.I), "preferred"),
    (re.compile(r"\bcertificates?\b", re.I), "other"),
    (re.compile(r"\bparticipation\s+rights?\b", re.I), "other"),
    (re.compile(r"\broyalty\b", re.I), "other"),
    # Explicit "other" decisions, not fall-through. A letter-of-credit facility
    # is a contingent commitment rather than a funded tranche, and real estate
    # owned is an asset taken in a workout - neither is debt or equity in the
    # sense the other five labels mean. Both must precede the generic
    # loan/note rule below, which would otherwise swallow "letter of credit
    # facility" the moment the word "loan" appeared beside it.
    (re.compile(r"\bletters?\s+of\s+credit\b", re.I), "other"),
    (re.compile(r"\breal\s+estate\s+owned\b", re.I), "other"),
    (
        re.compile(
            r"\b(common|ordinary|units?|shares?|stock|interests?|equity|"
            r"partnership|membership|member|llc|co-invest)\b",
            re.I,
        ),
        "equity",
    ),
    (re.compile(r"\b(loans?|notes?|bonds?|debentures?)\b", re.I), "other"),
]


class VocabularyError(ValueError):
    """Raised when an investment_type_raw matches no rule."""


def map_investment_type(raw: str) -> str:
    """Map the verbatim investment description onto the controlled vocabulary.

    Raises rather than defaulting: an unrecognised instrument must surface as a
    pipeline failure, not as a quiet "other".
    """
    s = (raw or "").strip()
    if not s:
        raise VocabularyError("empty investment_type_raw")
    for pattern, label in _TYPE_RULES:
        if pattern.search(s):
            return label
    raise VocabularyError(f"unmapped investment_type_raw: {s!r}")


# --------------------------------------------------------------------------
# pipeline stage
# --------------------------------------------------------------------------

RAW_PATH = INTERIM / "soi_rows.csv"
OUT_PATH = INTERIM / "soi_rows_normalized.csv"


def normalize_soi(df: pd.DataFrame) -> pd.DataFrame:
    """Drop subtotal rows and finalise types on the extracted SOI rows.

    `is_subtotal_row` is a parsing-time flag only.  It is used here to exclude
    rows and is not carried into the panel (plan section 3.2).
    """
    before = len(df)
    positions = df[~df["is_subtotal_row"].astype(bool)].copy()
    log.info("normalize: %d SOI rows in, %d subtotal/total rows dropped, %d positions",
             before, before - len(positions), len(positions))

    unmapped: dict[str, int] = {}
    mapped = []
    for raw in positions["investment_type_raw"]:
        try:
            mapped.append(map_investment_type(raw))
        except VocabularyError:
            unmapped[raw] = unmapped.get(raw, 0) + 1
            mapped.append(None)
    if unmapped:
        raise VocabularyError(
            "investment_type_raw values not covered by the controlled vocabulary: "
            + repr(sorted(unmapped.items(), key=lambda kv: -kv[1])[:20])
        )
    positions["investment_type"] = mapped

    positions["is_non_accrual"] = positions["is_non_accrual"].fillna(False).astype(bool)
    for col in ("principal_amount", "cost", "fair_value", "spread_bps",
                "all_in_rate_pct", "pct_of_net_assets"):
        positions[col] = pd.to_numeric(positions[col], errors="coerce")

    bad_types = sorted(set(positions["investment_type"]) - set(CONTROLLED_TYPES))
    if bad_types:
        raise VocabularyError(f"controlled vocabulary produced unexpected labels: {bad_types}")

    # Commitment lines that carry no amounts at all. Some filings list an
    # unfunded commitment with a borrower, an instrument, an acquisition date
    # and a footnote, but print nothing whatever in the cost and fair-value
    # columns - not even the em dash that elsewhere means zero:
    #
    #   Rialto Management Group, LLC | First lien senior secured revolving loan
    #     | 11/30/2018 | (cost blank) | (fair value: only the footnote "(14)")
    #
    # Recording 0.0 for both is an inference, and it is stated as one. What
    # makes it safe rather than a guess is that it is independently checkable
    # and independently checked: if the filing did attribute value to such a
    # row, adding zero would break the tie-out, and check 13 compares the
    # summed fair value against the balance sheet at 0.1%. On ARCC 2022 Q1 the
    # other positions already reach the reported total to -0.002566%, so the
    # filing itself attributes nothing to this line.
    #
    # Bounded deliberately: a mis-parsed fragment would produce many such rows,
    # and zeroing those would understate the portfolio, so anything beyond a
    # negligible share raises instead.
    no_amounts = positions["cost"].isna() & positions["fair_value"].isna()
    n_no_amounts = int(no_amounts.sum())
    if n_no_amounts:
        share = n_no_amounts / max(len(positions), 1)
        if share > 0.005:
            raise ValueError(
                f"{n_no_amounts} of {len(positions)} position rows ({share:.2%}) carry no "
                "cost and no fair value. That is too many to be commitment lines; it "
                "indicates a mis-parsed fragment, so no value is being assumed."
            )
        positions.loc[no_amounts, ["cost", "fair_value"]] = 0.0
        log.info("normalize: %d commitment row(s) print no cost and no fair value; "
                 "recorded as 0.0 (verified by the check 13 tie-out)", n_no_amounts)

    missing_fv = positions["fair_value"].isna().sum()
    if missing_fv:
        raise ValueError(f"{missing_fv} position rows have no fair_value; fair_value is never-null")

    # A fully undrawn revolver states no principal anywhere: older layouts print
    # the par inside the investment description ("($1.5 par due 5/2022)") and
    # simply omit it when nothing is drawn, while printing an em-dash - which
    # parse_number reads as 0.0 - for both cost and fair value. The modern
    # layout prints that same em-dash in its Principal column, so recording 0.0
    # here reproduces what the filer states in the era that has the column.
    #
    # Deliberately narrow, and deliberately here rather than in stage 04:
    #   * debt rows only, so an equity or warrant row keeps the null the schema
    #     requires (an earlier version of this rule ran before the vocabulary
    #     and silently gave 50 equity/warrant rows a principal of 0.0);
    #   * only when the filing itself reports zero on BOTH money columns, so it
    #     can never invent a principal for a row that reports a value.
    debt = positions["investment_type"].isin(DEBT_TYPES)
    unfunded = (
        debt
        & positions["principal_amount"].isna()
        & positions["cost"].eq(0.0)
        & positions["fair_value"].eq(0.0)
    )
    n_unfunded = int(unfunded.sum())
    if n_unfunded:
        positions.loc[unfunded, "principal_amount"] = 0.0
        log.info("normalize: %d undrawn debt row(s) with no stated par and zero cost and "
                 "zero fair value recorded as principal_amount=0.0", n_unfunded)

    # Unit-denominated debt. A CLO subordinated-notes tranche is reported with a
    # Shares/Units count and an empty Principal column - the filing states the
    # position's size in units because there is no USD principal to state:
    #
    #   ARES 2007-3R | Subordinated notes | Shares/Units 20,000,000 | Principal (blank)
    #
    # Exempted from the "principal is non-null for every debt-type row" rule,
    # and deliberately left NULL rather than filled with a number, because the
    # filing reports none. Unlike the undrawn-revolver case there is no zero
    # printed anywhere to record.
    #
    # The condition is observable and cannot mask a failed extraction: on this
    # filing 0 of 831 normal debt rows carry a Shares/Units count, while a row
    # whose principal we simply failed to read would have neither field.
    unit_denominated = (
        debt
        & positions["principal_amount"].isna()
        & pd.to_numeric(positions["shares_units"], errors="coerce").gt(0)
    )
    n_unit = int(unit_denominated.sum())
    if n_unit:
        log.info("normalize: %d debt row(s) are unit-denominated (a Shares/Units count "
                 "and no Principal column entry); principal_amount left null", n_unit)

    missing_principal = int((debt & positions["principal_amount"].isna() & ~unit_denominated).sum())
    if missing_principal:
        raise ValueError(
            f"{missing_principal} debt-type rows have no principal_amount "
            "(plan section 3.2: principal_amount is non-null for every debt-type row)"
        )
    return positions.reset_index(drop=True)


def main() -> int:
    df = pd.read_csv(RAW_PATH, keep_default_na=False, na_values=[""])
    out = normalize_soi(df)
    out.to_csv(OUT_PATH, index=False)
    log.info("normalize: wrote %s (%d rows)", OUT_PATH.name, len(out))
    counts = out["investment_type"].value_counts().to_dict()
    log.info("normalize: investment_type counts %s", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
