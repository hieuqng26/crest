import numpy as np
import pandas as pd

_SECTORS = [
    "Energy",
    "Financials",
    "Industrials",
    "Materials",
    "Technology",
    "Healthcare",
    "ConsumerStaples",
    "Utilities",
]
_COUNTRIES = ["US", "UK", "DE", "FR", "JP", "AU", "CA", "SG", "HK", "CH"]
_RATINGS = [
    "Aaa1",
    "Aaa2",
    "Aaa3",
    "Aa1",
    "Aa2",
    "Aa3",
    "A1",
    "A2",
    "A3",
    "Baa1",
    "Baa2",
    "Baa3",
    "Ba1",
    "Ba2",
    "B1",
    "B2",
    "Caa1",
    "Caa2",
    "Caa3",
]


def mock_credit_data(n_clients: int = 50, seed: int = 42) -> pd.DataFrame:
    client_ids = [f"C{i:04d}" for i in range(1, n_clients + 1)]
    rows = []
    for cid in client_ids:
        client_rng = np.random.default_rng(seed + hash(cid) % 10_000)
        rows.append(
            {
                "client_id": cid,
                "market_cap": float(client_rng.uniform(50e6, 50e9)),
                "vol_equity": float(client_rng.uniform(0.10, 0.55)),
                "rating": _RATINGS[int(client_rng.integers(0, len(_RATINGS)))],
                "risk_free_rate": float(client_rng.uniform(0.01, 0.05)),
                "sector": _SECTORS[int(client_rng.integers(0, len(_SECTORS)))],
                "country": _COUNTRIES[int(client_rng.integers(0, len(_COUNTRIES)))],
            }
        )
    return pd.DataFrame(rows)


def mock_kmv_forecast(
    client_id: str,
    base_year: int = 2024,
    n_years: int = 10,
    scenarios: list[str] | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    if scenarios is None:
        scenarios = ["Baseline", "Upside", "Downside"]

    client_seed = seed + hash(client_id) % 10_000
    rng = np.random.default_rng(client_seed)

    base_assets = rng.uniform(1e9, 100e9)
    base_cl = base_assets * rng.uniform(0.10, 0.25)
    base_ll = base_assets * rng.uniform(0.15, 0.35)

    years = list(range(base_year, base_year + n_years))
    rows = []
    for scen in scenarios:
        scen_rng = np.random.default_rng(client_seed + hash(scen) % 1_000)
        if scen == "Upside":
            asset_drift = scen_rng.uniform(0.03, 0.07)
            debt_drift = scen_rng.uniform(-0.01, 0.02)
        elif scen == "Downside":
            asset_drift = scen_rng.uniform(-0.03, 0.01)
            debt_drift = scen_rng.uniform(0.01, 0.04)
        else:
            asset_drift = scen_rng.uniform(0.01, 0.04)
            debt_drift = scen_rng.uniform(0.00, 0.02)

        for i, yr in enumerate(years):
            shock = float(scen_rng.normal(0, 0.02))
            rows.append(
                {
                    "YEAR": yr,
                    "SCENARIO": scen,
                    "Total_Asset": base_assets * (1 + asset_drift + shock) ** i,
                    "CL": base_cl * (1 + debt_drift) ** i,
                    "NonCL": base_ll * (1 + debt_drift * 0.8) ** i,
                }
            )

    return pd.DataFrame(rows)
