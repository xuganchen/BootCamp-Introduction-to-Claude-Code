"""Stage 07 - assemble the two panels into data/interim/.

Writes exactly the columns named in plan sections 3.1 and 3.2, in that order,
in USD dollars.  Nothing is written to `output/`: only the verification gate
(`bdc_08_checks.py`) promotes a passing run.

`is_subtotal_row` is a parsing-time flag and is deliberately absent from the
investment panel; the rows it marked were dropped in stage 06.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter

import pandas as pd

from bdc_09_utils import INTERIM, log

QUARTER_PATH = INTERIM / "bdc_quarter.csv"
INVESTMENT_PATH = INTERIM / "bdc_quarter_investment.csv"

QUARTER_COLUMNS = [
    "bdc_name", "ticker", "cik", "period_end", "filing_date", "form_type",
    "accession", "source_scale", "source_url",
    "total_investments_fv", "total_assets", "total_liabilities", "net_assets",
    "nav_per_share", "shares_outstanding", "total_debt_outstanding",
    "period_end_prior", "period_end_prior_kind",
    "total_investments_fv_prior", "total_assets_prior", "total_liabilities_prior",
    "net_assets_prior", "nav_per_share_prior", "shares_outstanding_prior",
    "total_debt_outstanding_prior",
]

INVESTMENT_COLUMNS = [
    "cik", "bdc_name", "period_end", "accession", "position_id",
    "borrower", "industry", "investment_type", "investment_type_raw",
    "reference_rate", "spread_bps", "all_in_rate_pct", "maturity_date",
    "principal_amount", "shares_units", "cost", "fair_value", "pct_of_net_assets",
    "is_non_accrual", "source_scale", "source_url",
]
# `shares_units` extends plan v1 section 3.2. It is here because some debt is
# unit-denominated (CLO subordinated notes: a Shares/Units count and no
# Principal), and without it the panel carries no stated size for those rows and
# the gate has no evidence with which to check the principal rule independently.


def make_position_ids(df: pd.DataFrame, cik: int, period_end: str) -> list[str]:
    """Deterministic, content-derived position ids.

    The key is the identifying content of the position, not its row number, so
    the id is stable when the parser changes.  A trailing occurrence counter
    disambiguates positions that are identical in every reported field (which
    does happen: two identical unfunded revolver tranches to one borrower).
    """
    seen: Counter[str] = Counter()
    ids: list[str] = []
    for r in df.itertuples():
        base = "|".join(
            str(x) for x in (
                cik, period_end, r.borrower, r.investment_type_raw,
                r.maturity_date, r.principal_amount, r.cost, r.fair_value,
            )
        )
        seen[base] += 1
        key = f"{base}|{seen[base]}"
        ids.append(hashlib.sha256(key.encode()).hexdigest()[:16])
    return ids


def build_quarter_panel(manifest: dict, bs: dict, scale: str) -> pd.DataFrame:
    row = {
        "bdc_name": manifest["bdc_name"],
        "ticker": manifest.get("ticker"),
        "cik": int(manifest["cik"]),
        "period_end": manifest["period_end"],
        "filing_date": manifest["filing_date"],
        "form_type": manifest["form_type"],
        "accession": manifest["accession"],
        "source_scale": scale,
        "source_url": manifest["doc_url"],
    }
    for field in (
        "total_investments_fv", "total_assets", "total_liabilities", "net_assets",
        "nav_per_share", "shares_outstanding", "total_debt_outstanding",
        "period_end_prior", "period_end_prior_kind",
        "total_investments_fv_prior", "total_assets_prior", "total_liabilities_prior",
        "net_assets_prior", "nav_per_share_prior", "shares_outstanding_prior",
        "total_debt_outstanding_prior",
    ):
        row[field] = bs.get(field)
    return pd.DataFrame([row], columns=QUARTER_COLUMNS)


def build_investment_panel(soi: pd.DataFrame, manifest: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=soi.index)
    out["cik"] = int(manifest["cik"])
    out["bdc_name"] = manifest["bdc_name"]
    out["period_end"] = manifest["period_end"]
    out["accession"] = manifest["accession"]
    out["position_id"] = make_position_ids(soi, int(manifest["cik"]), manifest["period_end"])
    for col in ("borrower", "industry", "investment_type", "investment_type_raw",
                "reference_rate", "spread_bps", "all_in_rate_pct", "maturity_date",
                "principal_amount", "shares_units", "cost", "fair_value",
                "pct_of_net_assets", "is_non_accrual", "source_scale"):
        out[col] = soi[col].values
    out["source_url"] = manifest["doc_url"]
    out["is_non_accrual"] = out["is_non_accrual"].astype(bool)
    return out[INVESTMENT_COLUMNS]


def _write_parquet(df: pd.DataFrame, csv_path) -> None:
    """Parquet twin, best effort: pyarrow is optional."""
    try:
        df.to_parquet(csv_path.with_suffix(".parquet"), index=False)
    except Exception as exc:  # pragma: no cover - environment dependent
        log.info("parquet twin for %s skipped (%s)", csv_path.name, exc)


def main() -> int:
    manifest = json.loads((INTERIM / "manifest.json").read_text())
    bs = json.loads((INTERIM / "balance_sheet.json").read_text())
    soi = pd.read_csv(INTERIM / "soi_rows_normalized.csv", keep_default_na=False, na_values=[""])

    quarter = build_quarter_panel(manifest, bs, bs["source_scale"])
    investment = build_investment_panel(soi, manifest)

    dupes = investment["position_id"].duplicated().sum()
    if dupes:
        raise RuntimeError(f"{dupes} duplicate position_id values")

    quarter.to_csv(QUARTER_PATH, index=False)
    investment.to_csv(INVESTMENT_PATH, index=False)
    _write_parquet(quarter, QUARTER_PATH)
    _write_parquet(investment, INVESTMENT_PATH)

    fv_sum = investment["fair_value"].sum()
    reported = float(quarter["total_investments_fv"].iloc[0])
    delta = fv_sum - reported
    log.info("panels: bdc_quarter %d row(s), bdc_quarter_investment %d rows, %d unique borrowers",
             len(quarter), len(investment), investment["borrower"].nunique())
    log.info("panels: tie-out sum(fair_value)=%.2f vs total_investments_fv=%.2f -> delta %.2f USD (%.6f%%)",
             fv_sum, reported, delta, 100.0 * delta / reported)
    return 0


if __name__ == "__main__":
    sys.exit(main())
