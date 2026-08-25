"""Shared pytest fixtures for the verification gate.

The clean fixtures below are SYNTHETIC. They are built from the independently
derived ground truth in tests/expected_values.json, not from the parser's
output, so a unit test that passes here proves the check logic works and says
nothing about whether the parser is correct. That is the integration suite's
job.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code"))

EXPECTED_PATH = Path(__file__).resolve().parent / "expected_values.json"
INTERIM = ROOT / "data" / "interim"


@pytest.fixture(scope="session")
def expected() -> dict:
    return json.loads(EXPECTED_PATH.read_text())


@pytest.fixture(scope="session")
def filing_meta(expected) -> dict:
    return expected["_about"]["filing"]


@pytest.fixture(scope="session")
def manifest() -> dict:
    p = INTERIM / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else {}


# ---------------------------------------------------------------------------
# Synthetic clean panels
# ---------------------------------------------------------------------------

SRC_URL = ("https://www.sec.gov/Archives/edgar/data/1287750/"
           "000162828026050307/arcc-20260630.htm")


def _clean_quarter_dict(expected: dict) -> dict:
    cur, pri = expected["current"], expected["prior"]
    return {
        "bdc_name": "ARES CAPITAL CORP",
        "ticker": "ARCC",
        "cik": 1287750,
        "period_end": date(2026, 6, 30),
        "filing_date": date(2026, 7, 29),
        "form_type": "10-Q",
        "accession": "0001628280-26-050307",
        "source_scale": "millions",
        "source_url": SRC_URL,
        "total_investments_fv": cur["total_investments_fv"]["value"],
        "total_assets": cur["total_assets"]["value"],
        "total_liabilities": cur["total_liabilities"]["value"],
        "net_assets": cur["net_assets"]["value"],
        "nav_per_share": cur["nav_per_share"]["value"],
        "shares_outstanding": cur["shares_outstanding"]["value"],
        "total_debt_outstanding": cur["total_debt_outstanding"]["value"],
        "period_end_prior": date(2025, 12, 31),
        "period_end_prior_kind": "prior_fiscal_year_end",
        "total_investments_fv_prior": pri["total_investments_fv"]["value"],
        "total_assets_prior": pri["total_assets"]["value"],
        "total_liabilities_prior": pri["total_liabilities"]["value"],
        "net_assets_prior": pri["net_assets"]["value"],
        "nav_per_share_prior": pri["nav_per_share"]["value"],
        "shares_outstanding_prior": pri["shares_outstanding"]["value"],
        "total_debt_outstanding_prior": pri["total_debt_outstanding"]["value"],
    }


def _clean_investment_rows(expected: dict) -> list[dict]:
    """Four synthetic positions that sum exactly to the reported totals.

    Two tranches of the same borrower (so rows > unique borrowers), one equity
    row with no principal, and one preferred row.
    """
    total_fv = expected["current"]["total_investments_fv"]["value"]
    total_cost = expected["current"]["total_investments_cost"]["value"]
    base = dict(
        cik=1287750,
        bdc_name="ARES CAPITAL CORP",
        period_end=date(2026, 6, 30),
        accession="0001628280-26-050307",
        source_scale="millions",
        source_url=SRC_URL,
        is_non_accrual=False,
    )
    fv = [total_fv - 3 * 1_000_000_000.0, 1_000_000_000.0, 1_000_000_000.0, 1_000_000_000.0]
    cost = [total_cost - 3 * 1_000_000_000.0, 1_000_000_000.0, 1_000_000_000.0, 1_000_000_000.0]
    specs = [
        ("pos-0001", "Acme Software Holdings", "Software", "first lien",
         "First lien senior secured loan", "SOFR", 525.0, 9.85,
         date(2030, 3, 15), 4_000_000_000.0),
        ("pos-0002", "Acme Software Holdings", "Software", "second lien",
         "Second lien senior secured loan", "SOFR", 800.0, 12.6,
         date(2031, 3, 15), 1_100_000_000.0),
        ("pos-0003", "Beta Health Services", "Healthcare", "equity",
         "Class A common units", None, None, None, None, None),
        ("pos-0004", "Gamma Logistics", "Transportation", "preferred",
         "Preferred equity", None, None, 11.0, None, None),
    ]
    rows = []
    for i, (pid, borrower, industry, itype, iraw, rate, spread, allin, mat, prin) in enumerate(specs):
        r = dict(base)
        r.update(
            position_id=pid, borrower=borrower, industry=industry,
            investment_type=itype, investment_type_raw=iraw,
            reference_rate=rate, spread_bps=spread, all_in_rate_pct=allin,
            maturity_date=mat, principal_amount=prin,
            cost=cost[i], fair_value=fv[i],
            pct_of_net_assets=round(100 * fv[i] / expected["current"]["net_assets"]["value"], 4),
        )
        rows.append(r)
    return rows


@pytest.fixture
def clean_quarter(expected) -> pd.DataFrame:
    return pd.DataFrame([_clean_quarter_dict(expected)])


@pytest.fixture
def clean_investment(expected) -> pd.DataFrame:
    return pd.DataFrame(_clean_investment_rows(expected))


@pytest.fixture
def clean_context(expected, manifest) -> dict:
    """Context wired to the real filing so checks 5, 14 and 15 can evaluate."""
    return {
        "cik": 1287750,
        "form_type": "10-Q",
        "period_end": date(2026, 6, 30),
        "fiscal_year_end": "1231",
        "doc_path": manifest.get("doc_path"),
        "facts_path": manifest.get("facts_path"),
        "bs_column_dates": [date(2026, 6, 30), date(2025, 12, 31)],
        "reported_total_cost": expected["current"]["total_investments_cost"]["value"],
        "unmapped_investment_types": None,
    }


@pytest.fixture
def offline_context(clean_context) -> dict:
    """Same, but with the filing detached, to exercise the context-only paths."""
    ctx = dict(clean_context)
    ctx["doc_path"] = None
    return ctx
