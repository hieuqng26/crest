import numpy as np
import pandas as pd
from scipy.optimize import root_scalar
from scipy.stats import norm

from project.logger import get_logger

logger = get_logger(__name__)


def run_kmv(
    com_info: dict,
    forecast: pd.DataFrame,
    pd_rating_df: pd.DataFrame,
    equity_financing_ratio: float = 0.0,
) -> pd.DataFrame:
    E0 = com_info["E0"]
    r = com_info["r"]
    volE = com_info["volE"]
    rating = com_info["rating"]

    if E0 <= 0:
        raise ValueError(f"Invalid market capitalisation (E0={E0}). Must be positive.")
    if volE <= 0:
        raise ValueError(f"Invalid equity volatility (volE={volE}). Must be positive.")
    if len(forecast["YEAR"].unique()) < 2:
        raise ValueError("Forecast must contain at least 2 distinct years.")
    if rating not in pd_rating_df["Rating"].values:
        raise ValueError(f"Rating '{rating}' not found in pd_rating_df.")

    scenarios = forecast["SCENARIO"].unique()
    year_sets = {
        scen: set(forecast.loc[forecast["SCENARIO"] == scen, "YEAR"])
        for scen in scenarios
    }
    ref_years = next(iter(year_sets.values()))
    for scen, yrs in year_sets.items():
        if yrs != ref_years:
            raise ValueError(
                f"Scenario '{scen}' has different year coverage than the first scenario. "
                "All scenarios must share the same year range."
            )

    df_list = []
    for scen in scenarios:
        f = (
            forecast[forecast["SCENARIO"] == scen]
            .copy()
            .sort_values("YEAR")
            .reset_index(drop=True)
        )
        AT = np.array(f["Total_Asset"])
        CLT = np.array(f["CL"])
        LLT = np.array(f["NonCL"])
        CL0, LL0 = CLT[0], LLT[0]
        CLT = CL0 + (1 - equity_financing_ratio) * (CLT - CL0)
        LLT = LL0 + (1 - equity_financing_ratio) * (LLT - LL0)
        D0 = CL0 + LL0 / 2
        DT = CLT + LLT / 2
        # Tenor is ordinal [1, 2, ..., N] — use len(AT) so non-contiguous calendar
        # years (where some clients are missing from certain time steps) don't cause
        # array length mismatches inside _kmv_step.
        Tenor = np.arange(1, len(AT) + 1)

        PD0 = pd_rating_df.loc[pd_rating_df["Rating"] == rating, "PD"].values.astype(
            float
        )
        calibrate = _kmv_calibrate(E0, D0, r, volE)
        V0 = calibrate["V0"]
        volV0 = calibrate["volV0"]
        cr_result = _kmv_step(PD0, AT, DT, D0, V0, volV0, Tenor, r, pd_rating_df)

        out = pd.DataFrame(
            {
                "YEAR": f["YEAR"].values,
                "SCENARIO": scen,
                "TOTAL_ASSET_T": AT,
                "CURRENT_LIAB_T": CLT,
                "LONG_TERM_LIAB_T": LLT,
                "Tenor": Tenor,
                "MARKET_CAP_0": E0,
                "REFERENCE_RATE": r,
                "EQUITY_VOLATILITY": volE,
                "DTD": cr_result["DTD"],
                "PD": cr_result["PD"],
                "LGD": cr_result["LGD"],
                "Rating": cr_result["Rating"],
                "Marginal PD": cr_result["Marginal PD"],
            }
        )
        df_list.append(out)

    return pd.concat(df_list, axis=0)


def _kmv_calibrate(E0, D0, r, volE, tau=1, dmMin=-10, dmMax=10, iter=100, tol=1e-5):
    D0 = D0 + 1e-10

    def volV(x):
        return E0 * volE / (E0 + D0 * np.exp(-r * tau) * norm.cdf(x))

    def V(x):
        return D0 * np.exp(-(r - volV(x) ** 2 / 2) * tau + volV(x) * np.sqrt(tau) * x)

    def Np(x):
        return norm.cdf(x + volV(x) * np.sqrt(tau))

    def E(x):
        return V(x) * Np(x) - D0 * np.exp(-r * tau) * norm.cdf(x)

    def f(x):
        return E(x) - E0

    bracket_found = False
    for i in range(1, iter + 1):
        xOffset = i
        try:
            f_min = f(dmMin - xOffset)
            f_max = f(dmMax + xOffset)
            if f_min * f_max < 0:
                dmMin = dmMin - xOffset
                dmMax = dmMax + xOffset
                bracket_found = True
                break
        except (ValueError, OverflowError) as e:
            logger.warning(f"Error computing bracket at offset {xOffset}: {e}")
            continue

    if not bracket_found:
        raise ValueError(
            f"Failed to find valid bracket for KMV calibration. "
            f"E0={E0}, D0={D0}, r={r}, volE={volE}."
        )

    try:
        result = root_scalar(f, bracket=[dmMin, dmMax], xtol=tol)
        if not result.converged:
            raise ValueError(
                f"KMV calibration failed to converge. E0={E0}, D0={D0}, r={r}, volE={volE}. "
                f"iterations={result.iterations}, flag={result.flag}"
            )
        dm0 = result.root
    except Exception as e:
        raise ValueError(
            f"KMV calibration root finding failed. E0={E0}, D0={D0}, r={r}, volE={volE}. "
            f"Error: {e}"
        )

    V0 = V(dm0)
    volV0 = volV(dm0)

    if not np.isfinite(V0) or not np.isfinite(volV0):
        raise ValueError(
            f"KMV calibration produced NaN/Inf. E0={E0}, D0={D0}, r={r}, volE={volE}. "
            f"V0={V0}, volV0={volV0}"
        )
    if V0 <= 0 or volV0 <= 0:
        raise ValueError(
            f"KMV calibration produced non-positive values. E0={E0}, D0={D0}, r={r}, volE={volE}. "
            f"V0={V0}, volV0={volV0}"
        )

    return {"V0": V0, "volV0": volV0}


def _kmv_step(PD0, AT, DT, D0, V0, volV0, Tenor, r, pd_rating_df):
    dt = 1
    t = np.arange(dt, Tenor[-2] + dt, dt)

    eps = 1e-10
    AT = np.where(AT <= 0, eps, AT)
    DT = np.where(DT <= 0, eps, DT)
    D0 = D0 + eps
    V0 = V0 + eps

    mu_A = np.log(AT[1:] / AT[0:-1])
    mu_D = np.log(DT[1:] / DT[0:-1])
    mu = mu_A - mu_D
    mu = np.where(np.isfinite(mu), mu, 0.0)
    mu_cumul = np.cumsum(mu) * dt

    std = volV0 * np.sqrt(t)

    g2 = 1 / std * (np.log(D0 / V0) - mu_cumul - std**2 / 2)
    g1 = g2 + std

    dtd_roll_1Y = 1 / volV0 * (np.log(V0 / D0) + mu_cumul + r - volV0**2 / 2)
    base_dtd = (np.log(V0 / D0) + (r - volV0**2 / 2)) / volV0
    marginal_dtd = np.append(base_dtd, dtd_roll_1Y)

    g1 = np.clip(g1, -10, 10)
    g2 = np.clip(g2, -10, 10)
    mu_cumul = np.clip(mu_cumul, -50, 50)
    lgd = np.maximum(
        0, 1 - V0 / (D0 + eps) * norm.cdf(g2) / (norm.cdf(g1) + eps) * np.exp(mu_cumul)
    )
    lgd = np.append(lgd, 0)

    implied_dtd_baseyear = norm.ppf(1 - PD0)
    scaler = marginal_dtd / marginal_dtd[0]
    implied_dtd = scaler * implied_dtd_baseyear
    marginal_pd = 1 - norm.cdf(implied_dtd)
    cum_pd = 1 - np.cumprod(1 - marginal_pd)

    cum_pd = np.array(cum_pd, dtype=float)
    master_pds = np.array(pd_rating_df["PD"].values, dtype=float)
    indices = np.abs(cum_pd[:, np.newaxis] - master_pds).argmin(axis=1)
    ratings = pd_rating_df["Rating"].iloc[indices].tolist()

    return pd.DataFrame(
        {
            "DTD": marginal_dtd,
            "PD": cum_pd,
            "Rating": ratings,
            "LGD": lgd,
            "Marginal PD": marginal_pd,
        }
    )
