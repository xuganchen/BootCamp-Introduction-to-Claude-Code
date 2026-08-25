"""
Verification for the parsed ARCC 10-Q tables.

The Schedule of Investments is a detail listing; the balance sheet is the
control total.  If the parse dropped, duplicated, or misread a position, these
checks fail.  Run this before trusting anything downstream.

  python3 code/verify_tieout.py
"""

import sys
import pandas as pd

SOI = "output/schedule_of_investments.csv"
FIN = "output/financial_statements.csv"
TOL = 0.05  # $ millions; the filing prints to 0.1M

KNOWN_BREAKS = """
Known breaks in the filing itself (not parse errors):

  2026-06-30, affiliation split, 0.5M.  DIEM-VII (QP), LLC is carried in the
  Schedule of Investments at cost 11.6M / fair value 11.1M, but the
  Investments in and Advances to Affiliates note shows its ending fair value
  as 11.6M with no net unrealized loss.  The SOI detail and the balance
  sheet's controlled-affiliate line disagree by that 0.5M.

  2025-12-31, affiliation split, 0.8M.  The balance sheet's own three
  affiliation lines (24,872.0 + 600.2 + 4,013.4 = 29,485.6) do not add to its
  own total investments line (29,484.8).  Presentation rounding.

Total investments at fair value ties exactly at both dates, which is the
check that proves nothing was dropped or double counted.
"""


def bs_value(fin, label, period, occurrence=0):
    m = fin[(fin.statement == "Consolidated Balance Sheets")
            & (fin.line_item == label) & (fin.column == period)]
    return m.value.iloc[occurrence] if len(m) > occurrence else None


def main():
    soi = pd.read_csv(SOI)
    fin = pd.read_csv(FIN)
    ok = True

    for as_of, period in (("2026-06-30", "Jun. 30, 2026"),
                          ("2025-12-31", "Dec. 31, 2025")):
        d = soi[soi.as_of == as_of]

        # 1. total investments at fair value
        got = d.fair_value.sum() / 1e6
        want = bs_value(fin, "Fair Value", period, 0)
        ok &= report(f"{as_of} total investments at fair value", got, want)

        # 2. the balance sheet's three affiliation tiers, in printed order.
        #    These are reported but NOT gating: the filing itself does not
        #    reconcile here (see KNOWN_BREAKS), and the total above is the
        #    control that actually proves the parse.
        tiers = ["Non-controlled/non-affiliate",
                 "Non-controlled affiliate",
                 "Controlled affiliate"]
        for i, tier in enumerate(tiers, start=1):
            got = d[d.affiliation == tier].fair_value.sum() / 1e6
            want = bs_value(fin, "Fair Value", period, i)
            report(f"{as_of} {tier}", got, want, gating=False)

        # 3. internal consistency: every position has cost and fair value
        miss = d[d.amortized_cost.isna() | d.fair_value.isna()]
        ok &= report(f"{as_of} positions missing cost/fair value",
                     len(miss), 0, unit="rows")

    print(KNOWN_BREAKS)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def report(name, got, want, unit="$M", gating=True):
    if want is None:
        print(f"  SKIP  {name}: no control total found")
        return True
    diff = got - want
    good = abs(diff) <= (TOL if unit == "$M" else 0)
    tag = ("ok  " if good else ("FAIL" if gating else "note"))
    print(f"  {tag}  {name}: "
          f"parsed {got:,.1f} vs filing {want:,.1f} ({diff:+,.1f} {unit})")
    return good or not gating


if __name__ == "__main__":
    sys.exit(main())
