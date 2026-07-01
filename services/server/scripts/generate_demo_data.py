"""
Generate realistic synthetic demo data for the CREST platform.

Produces four CSV files in project/data/test_data/:
  - financials_macro_merged.csv   ~185k rows, annual 1990-2026
  - demo_credit_portfolio.csv     1500 clients (~30/segment when segmenting by
                                   subsector, ~15/segment when segmenting by country)
  - demo_macro_forecast.csv       15 rows: portfolio-wide MEV scenario table
                                   (annual 2027-2031 x 3 scenarios, no client_id)
  - demo_financial_portfolio.csv  22500 rows (1500 clients x 5 years x 3 scenarios)

Run from services/server/:
    python scripts/generate_demo_data.py
"""

import hashlib
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _stable_hash(s: str) -> int:
    """Deterministic string hash — Python's builtin hash() is randomized per-process
    (PYTHONHASHSEED), which would make this script non-reproducible despite SEED."""
    return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEED = 42
RNG = np.random.default_rng(SEED)

YEARS = list(range(1990, 2027))  # 37 annual periods
FORECAST_YEARS = list(range(2027, 2032))  # 5-year forecast
SCENARIOS = ["Baseline", "Adverse", "Severely Adverse"]

SECTORS = [
    "Energy",
    "Financials",
    "Technology",
    "Healthcare",
    "ConsumerStaples",
    "ConsumerDiscretionary",
    "Industrials",
    "Materials",
    "Utilities",
    "RealEstate",
]

SUBSECTORS = {
    "Energy": ["Oil & Gas", "Renewables", "Coal", "Natural Gas", "Petrochemicals"],
    "Financials": [
        "Retail Banking",
        "Insurance",
        "Investment Banking",
        "Asset Management",
        "Microfinance",
    ],
    "Technology": [
        "Software",
        "Hardware",
        "Semiconductors",
        "IT Services",
        "Cybersecurity",
    ],
    "Healthcare": [
        "Pharma",
        "Medical Devices",
        "Hospitals",
        "Biotech",
        "Health Insurance",
    ],
    "ConsumerStaples": [
        "Beverages",
        "Food Processing",
        "Tobacco",
        "Household Products",
        "Personal Care",
    ],
    "ConsumerDiscretionary": [
        "Retail",
        "Automotive",
        "Luxury Goods",
        "Travel & Leisure",
        "Media",
    ],
    "Industrials": [
        "Manufacturing",
        "Aerospace",
        "Transportation",
        "Construction",
        "Engineering",
    ],
    "Materials": ["Mining", "Steel", "Chemicals", "Paper & Pulp", "Plastics"],
    "Utilities": [
        "Electric Power",
        "Water",
        "Gas Distribution",
        "Renewable Power",
        "Infrastructure",
    ],
    "RealEstate": [
        "Commercial",
        "Residential",
        "REIT",
        "Industrial Property",
        "Hotels",
    ],
}

COUNTRIES = [
    "USA",
    "UK",
    "Germany",
    "Japan",
    "Canada",
    "Australia",
    "Singapore",
    "France",
    "South Korea",
    "Brazil",
]

# Country ISO2 mapping (used in credit_portfolio country column)
COUNTRY_ISO = {
    "USA": "US",
    "UK": "GB",
    "Germany": "DE",
    "Japan": "JP",
    "Canada": "CA",
    "Australia": "AU",
    "Singapore": "SG",
    "France": "FR",
    "South Korea": "KR",
    "Brazil": "BR",
}

# Country-level macro parameters (1990 starting values and growth rates)
# gdp_1990: USD billions; gdp_growth: annual real growth rate
COUNTRY_MACRO = {
    "USA": {"gdp_1990": 5980, "gdp_growth": 0.025, "infl_mean": 2.5, "unemp_mean": 5.5},
    "UK": {"gdp_1990": 1100, "gdp_growth": 0.020, "infl_mean": 2.8, "unemp_mean": 6.5},
    "Germany": {
        "gdp_1990": 1570,
        "gdp_growth": 0.018,
        "infl_mean": 2.0,
        "unemp_mean": 7.0,
    },
    "Japan": {
        "gdp_1990": 3100,
        "gdp_growth": 0.010,
        "infl_mean": 0.8,
        "unemp_mean": 3.5,
    },
    "Canada": {
        "gdp_1990": 590,
        "gdp_growth": 0.022,
        "infl_mean": 2.2,
        "unemp_mean": 7.0,
    },
    "Australia": {
        "gdp_1990": 320,
        "gdp_growth": 0.028,
        "infl_mean": 3.0,
        "unemp_mean": 6.5,
    },
    "Singapore": {
        "gdp_1990": 47,
        "gdp_growth": 0.052,
        "infl_mean": 1.8,
        "unemp_mean": 2.5,
    },
    "France": {
        "gdp_1990": 1230,
        "gdp_growth": 0.018,
        "infl_mean": 1.8,
        "unemp_mean": 9.0,
    },
    "South Korea": {
        "gdp_1990": 290,
        "gdp_growth": 0.045,
        "infl_mean": 2.8,
        "unemp_mean": 3.8,
    },
    "Brazil": {
        "gdp_1990": 470,
        "gdp_growth": 0.030,
        "infl_mean": 6.5,
        "unemp_mean": 10.0,
    },
}

# Sector-level parameters for generating realistic financial metrics
SECTOR_PARAMS = {
    # asset_gdp_ratio: total_assets as fraction of country GDP (per client, scaled by n_clients)
    # ltd_ratio: long-term debt / total_assets
    # std_ratio: short-term debt / total_assets
    # oil_beta: sensitivity to oil price changes (positive = benefits from high oil)
    # coal_beta: sensitivity to coal price changes
    # revenue_ratio: revenue / total_assets
    # cogs_ratio: COGS / revenue
    "Energy": {
        "asset_gdp_ratio": 0.0040,
        "ltd_ratio": 0.35,
        "std_ratio": 0.10,
        "oil_beta": 0.30,
        "coal_beta": 0.10,
        "revenue_ratio": 0.30,
        "cogs_ratio": 0.65,
    },
    "Financials": {
        "asset_gdp_ratio": 0.0120,
        "ltd_ratio": 0.55,
        "std_ratio": 0.20,
        "oil_beta": -0.05,
        "coal_beta": -0.05,
        "revenue_ratio": 0.08,
        "cogs_ratio": 0.50,
    },
    "Technology": {
        "asset_gdp_ratio": 0.0020,
        "ltd_ratio": 0.15,
        "std_ratio": 0.12,
        "oil_beta": -0.05,
        "coal_beta": -0.02,
        "revenue_ratio": 0.40,
        "cogs_ratio": 0.45,
    },
    "Healthcare": {
        "asset_gdp_ratio": 0.0025,
        "ltd_ratio": 0.20,
        "std_ratio": 0.10,
        "oil_beta": -0.03,
        "coal_beta": -0.01,
        "revenue_ratio": 0.35,
        "cogs_ratio": 0.55,
    },
    "ConsumerStaples": {
        "asset_gdp_ratio": 0.0018,
        "ltd_ratio": 0.25,
        "std_ratio": 0.12,
        "oil_beta": -0.08,
        "coal_beta": -0.03,
        "revenue_ratio": 0.45,
        "cogs_ratio": 0.68,
    },
    "ConsumerDiscretionary": {
        "asset_gdp_ratio": 0.0015,
        "ltd_ratio": 0.28,
        "std_ratio": 0.15,
        "oil_beta": -0.10,
        "coal_beta": -0.03,
        "revenue_ratio": 0.55,
        "cogs_ratio": 0.70,
    },
    "Industrials": {
        "asset_gdp_ratio": 0.0022,
        "ltd_ratio": 0.30,
        "std_ratio": 0.12,
        "oil_beta": -0.12,
        "coal_beta": -0.08,
        "revenue_ratio": 0.38,
        "cogs_ratio": 0.72,
    },
    "Materials": {
        "asset_gdp_ratio": 0.0028,
        "ltd_ratio": 0.32,
        "std_ratio": 0.12,
        "oil_beta": 0.05,
        "coal_beta": 0.20,
        "revenue_ratio": 0.42,
        "cogs_ratio": 0.75,
    },
    "Utilities": {
        "asset_gdp_ratio": 0.0035,
        "ltd_ratio": 0.45,
        "std_ratio": 0.08,
        "oil_beta": -0.15,
        "coal_beta": -0.20,
        "revenue_ratio": 0.18,
        "cogs_ratio": 0.60,
    },
    "RealEstate": {
        "asset_gdp_ratio": 0.0050,
        "ltd_ratio": 0.50,
        "std_ratio": 0.08,
        "oil_beta": -0.05,
        "coal_beta": -0.02,
        "revenue_ratio": 0.10,
        "cogs_ratio": 0.40,
    },
}

# Moody's rating → PD lookup (used for demo_credit_portfolio)
MOODY_RATINGS = [
    ("Aaa1", 0.0001),
    ("Aaa2", 0.0002),
    ("Aaa3", 0.0003),
    ("Aa1", 0.0005),
    ("Aa2", 0.0007),
    ("Aa3", 0.0010),
    ("A1", 0.0015),
    ("A2", 0.0020),
    ("A3", 0.0030),
    ("Baa1", 0.0050),
    ("Baa2", 0.0070),
    ("Baa3", 0.0100),
    ("Ba1", 0.0200),
    ("Ba2", 0.0300),
    ("B1", 0.0500),
    ("B2", 0.0800),
    ("Caa1", 0.1500),
    ("Caa2", 0.2500),
    ("Caa3", 0.4000),
]

CLIENTS_PER_COMBO = 10  # clients per (sector, country, subsector)


# ---------------------------------------------------------------------------
# Macro time-series generation
# ---------------------------------------------------------------------------


def _ar1(n: int, mean: float, phi: float, sigma: float, seed: int) -> np.ndarray:
    """Simulate AR(1) process around `mean`."""
    rng = np.random.default_rng(seed)
    xs = np.empty(n)
    xs[0] = mean
    for t in range(1, n):
        xs[t] = mean + phi * (xs[t - 1] - mean) + rng.normal(0, sigma)
    return xs


def generate_global_commodities() -> dict[int, dict]:
    """Generate oil and coal price series (same for all countries)."""
    n = len(YEARS)
    oil = _ar1(n, mean=65.0, phi=0.85, sigma=8.0, seed=1)
    oil = np.clip(oil, 15, 150)
    coal = _ar1(n, mean=100.0, phi=0.80, sigma=6.0, seed=2)
    coal = np.clip(coal, 40, 200)
    return {
        yr: {
            "oil_price": round(float(oil[i]), 2),
            "coal_price": round(float(coal[i]), 2),
        }
        for i, yr in enumerate(YEARS)
    }


def generate_country_macro(commodities: dict[int, dict]) -> dict[str, dict[int, dict]]:
    """Generate annual macro series per country for training years."""
    macro = {}
    for cidx, country in enumerate(COUNTRIES):
        p = COUNTRY_MACRO[country]
        n = len(YEARS)
        base_seed = 100 + cidx * 10

        gdp = np.empty(n)
        gdp[0] = p["gdp_1990"]
        gdp_growth_noise = _ar1(
            n, mean=p["gdp_growth"], phi=0.70, sigma=0.008, seed=base_seed
        )
        for t in range(1, n):
            gdp[t] = gdp[t - 1] * (1 + gdp_growth_noise[t])

        infl_noise = _ar1(
            n, mean=p["infl_mean"], phi=0.65, sigma=0.8, seed=base_seed + 1
        )
        infl = np.clip(infl_noise, -1.0, 20.0)

        unemp_noise = _ar1(
            n, mean=p["unemp_mean"], phi=0.75, sigma=0.5, seed=base_seed + 2
        )
        # Unemployment rises when GDP growth slows
        gdp_growth_arr = np.diff(gdp, prepend=gdp[0]) / (gdp + 1)
        unemp = unemp_noise - 3.0 * (gdp_growth_arr - p["gdp_growth"])
        unemp = np.clip(unemp, 0.5, 25.0)

        macro[country] = {
            yr: {
                "notional_gdp": round(float(gdp[i]), 3),
                "inflation_rate": round(float(infl[i]), 4),
                "unemployment_rate": round(float(unemp[i]), 4),
                "oil_price": commodities[yr]["oil_price"],
                "coal_price": commodities[yr]["coal_price"],
            }
            for i, yr in enumerate(YEARS)
        }
    return macro


def generate_forecast_macro(
    country_macro: dict[str, dict[int, dict]],
) -> dict[str, dict[int, dict[str, dict]]]:
    """Generate scenario-based macro forecasts for 2027-2031, per country."""
    # Use 2026 as base and project forward
    forecast: dict[str, dict[int, dict[str, dict]]] = {}
    # Global commodity scenario shocks
    oil_2026 = country_macro["USA"][2026]["oil_price"]
    coal_2026 = country_macro["USA"][2026]["coal_price"]
    commodity_scenarios = {
        "Baseline": {"oil_drift": 0.02, "coal_drift": 0.01},
        "Adverse": {"oil_drift": -0.05, "coal_drift": -0.03},
        "Severely Adverse": {"oil_drift": -0.12, "coal_drift": -0.08},
    }

    for country in COUNTRIES:
        p = COUNTRY_MACRO[country]
        base = country_macro[country][2026]
        forecast[country] = {}

        for i, yr in enumerate(FORECAST_YEARS, start=1):
            forecast[country][yr] = {}
            for scen in SCENARIOS:
                if scen == "Baseline":
                    gdp_drift = p["gdp_growth"]
                    infl_shock = 0.0
                    unemp_shock = 0.0
                elif scen == "Adverse":
                    gdp_drift = p["gdp_growth"] * 0.4
                    infl_shock = 1.5
                    unemp_shock = 1.5
                else:  # Severely Adverse
                    gdp_drift = -p["gdp_growth"] * 0.5
                    infl_shock = 3.5
                    unemp_shock = 3.5

                oil = oil_2026 * (1 + commodity_scenarios[scen]["oil_drift"]) ** i
                coal = coal_2026 * (1 + commodity_scenarios[scen]["coal_drift"]) ** i
                gdp = base["notional_gdp"] * (1 + gdp_drift) ** i
                infl = base["inflation_rate"] + infl_shock * (i / len(FORECAST_YEARS))
                unemp = base["unemployment_rate"] + unemp_shock * (
                    i / len(FORECAST_YEARS)
                )

                forecast[country][yr][scen] = {
                    "notional_gdp": round(float(gdp), 3),
                    "inflation_rate": round(float(max(-1.0, infl)), 4),
                    "unemployment_rate": round(float(min(25.0, unemp)), 4),
                    "oil_price": round(float(oil), 2),
                    "coal_price": round(float(coal), 2),
                }

    return forecast


# ---------------------------------------------------------------------------
# Financial data generation
# ---------------------------------------------------------------------------


def _compute_total_assets(
    sector: str,
    gdp: float,
    infl: float,
    unemp: float,
    oil: float,
    coal: float,
    client_mult: float,
    rng: np.random.Generator,
) -> float:
    """
    total_assets is a linear function of macro features.

    Design ensures R² ≈ 70-85% within each (sector, subsector) segment:
      - GDP coefficient dominates (explains ~80% of variance)
      - Inflation, unemployment, oil, coal add secondary effects
      - client_mult (±15%) adds cross-client noise
      - 5% row-level noise
    """
    sp = SECTOR_PARAMS[sector]

    # GDP is the dominant driver — use a generous ratio to create large amplitude
    gdp_component = sp["asset_gdp_ratio"] * gdp

    # Secondary macro effects (standardized around typical values to give ~10-20% amplitude)
    infl_adj = 1.0 - 0.08 * (infl - 2.5)  # higher inflation → lower assets
    unemp_adj = 1.0 - 0.04 * (unemp - 6.0)  # higher unemployment → slightly lower
    oil_adj = 1.0 + sp["oil_beta"] * (oil - 65.0) / 65.0
    coal_adj = 1.0 + sp["coal_beta"] * (coal - 100.0) / 100.0

    adjustment = infl_adj * unemp_adj * oil_adj * coal_adj
    adjustment = max(0.3, min(3.0, adjustment))  # guard rails

    noise = float(rng.normal(0, 0.05))  # 5% row-level noise

    assets = gdp_component * adjustment * client_mult * (1.0 + noise)
    return max(1.0, assets)  # always positive


def generate_financials_macro_merged(
    country_macro: dict[str, dict[int, dict]],
) -> pd.DataFrame:
    """Generate the main calibration training dataset."""
    rows = []
    client_counter = 1

    for sector in SECTORS:
        for country in COUNTRIES:
            for subsector in SUBSECTORS[sector]:
                # Assign client IDs for this (sector, country, subsector) combo
                client_ids = [
                    f"C{client_counter + k:05d}" for k in range(CLIENTS_PER_COMBO)
                ]
                client_counter += CLIENTS_PER_COMBO

                # Per-client multiplier: ±15% variation
                combo_seed = _stable_hash(f"{sector}|{country}|{subsector}") % 100_000
                combo_rng = np.random.default_rng(combo_seed)
                client_mults = combo_rng.uniform(0.85, 1.15, size=CLIENTS_PER_COMBO)

                sp = SECTOR_PARAMS[sector]

                for k, (cid, cmult) in enumerate(zip(client_ids, client_mults)):
                    client_rng = np.random.default_rng(combo_seed + k + 1)

                    for yr in YEARS:
                        m = country_macro[country][yr]
                        gdp = m["notional_gdp"]
                        infl = m["inflation_rate"]
                        unemp = m["unemployment_rate"]
                        oil = m["oil_price"]
                        coal = m["coal_price"]

                        assets = _compute_total_assets(
                            sector, gdp, infl, unemp, oil, coal, cmult, client_rng
                        )
                        ltd_noise = float(client_rng.normal(0, 0.04))
                        std_noise = float(client_rng.normal(0, 0.04))
                        rev_noise = float(client_rng.normal(0, 0.04))

                        ltd = assets * sp["ltd_ratio"] * (1.0 + ltd_noise)
                        std = assets * sp["std_ratio"] * (1.0 + std_noise)
                        revenue = assets * sp["revenue_ratio"] * (1.0 + rev_noise)
                        cogs = (
                            revenue
                            * sp["cogs_ratio"]
                            * float(client_rng.normal(1.0, 0.03))
                        )
                        interest = ltd * 0.05 * float(client_rng.normal(1.0, 0.05))
                        ead = assets * 0.08 * float(client_rng.normal(1.0, 0.04))

                        rows.append(
                            {
                                "date": f"{yr}-01-01",
                                "sector": sector,
                                "country": country,
                                "client_id": cid,
                                "total_revenue": round(max(0.01, revenue), 2),
                                "total_cogs": round(max(0.01, cogs), 2),
                                "interest_expenses": round(max(0.0, interest), 2),
                                "total_assets": round(max(1.0, assets), 2),
                                "total_longterm_debts": round(max(0.0, ltd), 2),
                                "total_shortterm_debts": round(max(0.0, std), 2),
                                "subsector": subsector,
                                "ead": round(max(0.01, ead), 2),
                                "inflation_rate": infl,
                                "notional_gdp": gdp,
                                "unemployment_rate": unemp,
                                "coal_price": coal,
                                "oil_price": oil,
                            }
                        )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Demo portfolio generation
# ---------------------------------------------------------------------------


CLIENTS_PER_SEGMENT_TRIPLE = 3  # per (sector, country, subsector) -> 30/segment when
# segmenting by subsector (10 countries x 3), 15/segment when segmenting by country
# (5 subsectors x 3).


def _pick_demo_clients(
    df: pd.DataFrame, clients_per_triple: int = CLIENTS_PER_SEGMENT_TRIPLE
) -> pd.DataFrame:
    """
    Pick demo clients for demo_credit_portfolio.csv / demo_financial_portfolio.csv:
    `clients_per_triple` clients from every (sector, country, subsector) triple, drawn
    from all 10 countries so each (sector, subsector) *segment* — the unit a segmented
    calibration actually groups by — ends up with clients_per_triple x 10 clients.
    """
    df_2026 = df[df["date"] == "2026-01-01"]
    selected = []
    for (sector, country, subsector), group in df_2026.groupby(
        ["sector", "country", "subsector"], observed=True
    ):
        top = group.sort_values("client_id").head(clients_per_triple)
        for _, row in top.iterrows():
            selected.append(
                {
                    "client_id": row["client_id"],
                    "sector": sector,
                    "subsector": subsector,
                    "country": country,
                    "total_assets_2026": float(row["total_assets"]),
                    "total_longterm_debts_2026": float(row["total_longterm_debts"]),
                    "total_shortterm_debts_2026": float(row["total_shortterm_debts"]),
                }
            )
    return pd.DataFrame(selected)


def generate_credit_portfolio(demo_clients: pd.DataFrame) -> pd.DataFrame:
    """Generate demo_credit_portfolio.csv from selected clients."""
    rng = np.random.default_rng(SEED + 200)
    rows = []

    # Tobin's q multiplier per sector (equity market cap relative to assets)
    tobins_q = {
        "Energy": 0.80,
        "Financials": 0.60,
        "Technology": 2.50,
        "Healthcare": 2.00,
        "ConsumerStaples": 1.80,
        "ConsumerDiscretionary": 1.50,
        "Industrials": 1.20,
        "Materials": 1.00,
        "Utilities": 0.90,
        "RealEstate": 0.75,
    }

    # Country risk-free rate (2026 approximate)
    rfr = {
        "USA": 0.045,
        "UK": 0.040,
        "Germany": 0.030,
        "Japan": 0.008,
        "Canada": 0.042,
        "Australia": 0.043,
        "Singapore": 0.035,
        "France": 0.030,
        "South Korea": 0.032,
        "Brazil": 0.105,
    }

    # Sector leverage → rating
    # Higher leverage → worse rating
    ltd_ratio = {s: SECTOR_PARAMS[s]["ltd_ratio"] for s in SECTORS}

    def _rating_from_leverage(ltd_r: float) -> str:
        # Rough mapping: low leverage → high rating
        if ltd_r < 0.15:
            return "Aa2"
        elif ltd_r < 0.20:
            return "A1"
        elif ltd_r < 0.25:
            return "A2"
        elif ltd_r < 0.30:
            return "A3"
        elif ltd_r < 0.35:
            return "Baa1"
        elif ltd_r < 0.40:
            return "Baa2"
        elif ltd_r < 0.50:
            return "Baa3"
        elif ltd_r < 0.55:
            return "Ba1"
        else:
            return "Ba2"

    for _, row in demo_clients.iterrows():
        sector = row["sector"]
        country = row["country"]
        assets = row["total_assets_2026"]
        sector_q = tobins_q.get(sector, 1.2)
        # market cap ~ equity value approximated via assets - debt
        equity_est = assets * (
            1 - ltd_ratio[sector] - SECTOR_PARAMS[sector]["std_ratio"]
        )
        mc = equity_est * sector_q * float(rng.uniform(0.85, 1.15))
        mc = max(1e6, mc)

        vol = float(rng.uniform(0.20, 0.55))
        # Per-client leverage jitter (deterministic on client_id) so clients within the
        # same sector/segment aren't all assigned the identical rating.
        client_leverage = ltd_ratio[sector] * (
            0.7 + (_stable_hash(row["client_id"]) % 600) / 1000.0
        )  # +/-30% around the sector's base leverage
        rating = _rating_from_leverage(client_leverage)
        base_rfr = rfr.get(country, 0.035)
        r = round(base_rfr + float(rng.normal(0, 0.003)), 4)
        r = max(0.001, min(0.15, r))

        rows.append(
            {
                "client_id": row["client_id"],
                "market_cap": round(mc, 2),
                "vol_equity": round(vol, 4),
                "rating": rating,
                "risk_free_rate": r,
                "sector": sector,
                "country": country,
            }
        )

    return pd.DataFrame(rows)


HOUSE_VIEW_COUNTRY = "USA"  # single macro scenario driver (DFAST/CCAR-style house view)


def generate_macro_forecast(
    forecast_macro: dict[str, dict[int, dict[str, dict]]],
) -> pd.DataFrame:
    """
    Generate demo_macro_forecast.csv: a single portfolio-wide macro scenario table
    (5 years x 3 scenarios = 15 rows). No client_id/sector/country — a forecast run
    only needs the MEV feature columns a calibrated (segment) model requires, and the
    resulting trajectory is applied uniformly to every client in the credit risk run.
    """
    rows = []
    for yr in FORECAST_YEARS:
        for scen in SCENARIOS:
            m = forecast_macro[HOUSE_VIEW_COUNTRY][yr][scen]
            rows.append(
                {
                    "date": f"1/1/{yr - 2000:02d}",
                    "scenario": scen,
                    "inflation_rate": m["inflation_rate"],
                    "notional_gdp": m["notional_gdp"],
                    "unemployment_rate": m["unemployment_rate"],
                    "coal_price": m["coal_price"],
                    "oil_price": m["oil_price"],
                }
            )
    return pd.DataFrame(rows)


def generate_financial_portfolio(
    demo_clients: pd.DataFrame,
    forecast_macro: dict[str, dict[int, dict[str, dict]]],
) -> pd.DataFrame:
    """
    Generate demo_financial_portfolio.csv for every selected demo client.
    Financial values use the same linear model as training data.
    """
    rows = []
    rng = np.random.default_rng(SEED + 300)

    for _, client_row in demo_clients.iterrows():
        cid = client_row["client_id"]
        sector = client_row["sector"]
        country = client_row["country"]
        subsector = client_row["subsector"]
        sp = SECTOR_PARAMS[sector]

        # Use a fixed client multiplier (derived from client_id hash for reproducibility)
        client_mult = 0.95 + (_stable_hash(cid) % 100) / 1000.0  # 0.95 to 1.05

        for yr in FORECAST_YEARS:
            for scen in SCENARIOS:
                m = forecast_macro[country][yr][scen]

                assets = _compute_total_assets(
                    sector,
                    m["notional_gdp"],
                    m["inflation_rate"],
                    m["unemployment_rate"],
                    m["oil_price"],
                    m["coal_price"],
                    client_mult,
                    rng,
                )
                ltd = assets * sp["ltd_ratio"] * float(rng.normal(1.0, 0.03))
                std = assets * sp["std_ratio"] * float(rng.normal(1.0, 0.03))

                rows.append(
                    {
                        "date": f"1/1/{yr - 2000:02d}",
                        "scenario": scen,
                        "client_id": cid,
                        "country": country,
                        "sector": sector,
                        "subsector": subsector,
                        "base_year": 2026,
                        "total_assets": round(max(1.0, assets), 2),
                        "total_longterm_debts": round(max(0.0, ltd), 2),
                        "total_shortterm_debts": round(max(0.0, std), 2),
                    }
                )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    out_dir = os.path.join(
        os.path.dirname(__file__), "..", "project", "data", "test_data"
    )
    os.makedirs(out_dir, exist_ok=True)

    print("Generating global commodity prices...")
    commodities = generate_global_commodities()

    print("Generating country macro series (1990-2026)...")
    country_macro = generate_country_macro(commodities)

    print("Generating forecast macro series (2027-2031)...")
    forecast_macro = generate_forecast_macro(country_macro)

    print("Generating financials_macro_merged.csv (~185k rows)...")
    df_merged = generate_financials_macro_merged(country_macro)
    path_merged = os.path.join(out_dir, "financials_macro_merged.csv")
    df_merged.to_csv(path_merged, index=False)
    print(f"  Wrote {len(df_merged):,} rows → {path_merged}")

    print("Selecting demo clients...")
    demo_clients = _pick_demo_clients(df_merged)
    print(f"  Selected {len(demo_clients)} clients")

    print("Generating demo_credit_portfolio.csv...")
    credit_df = generate_credit_portfolio(demo_clients)
    path_credit = os.path.join(out_dir, "demo_credit_portfolio.csv")
    credit_df.to_csv(path_credit, index=False)
    print(f"  Wrote {len(credit_df)} rows → {path_credit}")

    print("Generating demo_macro_forecast.csv...")
    macro_fc_df = generate_macro_forecast(forecast_macro)
    path_macro_fc = os.path.join(out_dir, "demo_macro_forecast.csv")
    macro_fc_df.to_csv(path_macro_fc, index=False)
    print(f"  Wrote {len(macro_fc_df)} rows → {path_macro_fc}")

    print("Generating demo_financial_portfolio.csv...")
    fin_df = generate_financial_portfolio(demo_clients, forecast_macro)
    path_fin = os.path.join(out_dir, "demo_financial_portfolio.csv")
    fin_df.to_csv(path_fin, index=False)
    print(f"  Wrote {len(fin_df)} rows → {path_fin}")

    # Quick sanity check
    print("\n--- Sanity Checks ---")
    print(f"Sectors: {df_merged['sector'].nunique()}")
    print(f"Countries: {df_merged['country'].nunique()}")
    subsectors_per_sector = df_merged.groupby("sector")["subsector"].nunique()
    print(f"Subsectors per sector:\n{subsectors_per_sector}")
    combo_sizes = df_merged.groupby(["sector", "country", "subsector"]).size()
    print(
        f"Rows per combo: min={combo_sizes.min()}, median={combo_sizes.median():.0f}, max={combo_sizes.max()}"
    )
    print(f"Total clients: {df_merged['client_id'].nunique():,}")
    print(
        f"Demo client set covers all sectors: {set(demo_clients['sector'].unique()) == set(SECTORS)}"
    )
    clients_per_subsector_segment = demo_clients.groupby(["sector", "subsector"]).size()
    clients_per_country_segment = demo_clients.groupby(["sector", "country"]).size()
    print(
        f"Clients per (sector, subsector) segment: min={clients_per_subsector_segment.min()}, "
        f"median={clients_per_subsector_segment.median():.0f}"
    )
    print(
        f"Clients per (sector, country) segment: min={clients_per_country_segment.min()}, "
        f"median={clients_per_country_segment.median():.0f}"
    )


if __name__ == "__main__":
    main()
