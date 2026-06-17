import math

import numpy as np
import pandas as pd


def compute_ecl(
    data: pd.DataFrame,
    exposure: float,
    r: float,
    lifetime_horizon: int = 5,
    drop_tail: bool = False,
) -> pd.DataFrame:
    base_year = min(data["YEAR"].values)
    max_year = max(data["YEAR"].values)
    scenarios = data["SCENARIO"].unique()
    df_list = []

    for scen in scenarios:
        data_filtered = data[data["SCENARIO"] == scen]
        df = pd.DataFrame(
            {
                "YEAR": [base_year - 1] + data_filtered["YEAR"].tolist(),
                "SCENARIO": scen,
                "PD": [0.0] + data_filtered["PD"].tolist(),
                "LGD": [0.0] + data_filtered["LGD"].tolist(),
                "EAD": exposure,
                "PD_prev": [0.0, 0.0] + data_filtered["PD"].tolist()[:-1],
            }
        )

        PD = df["PD"]
        PD_PREV = df["PD_prev"]
        df["Conditional_PD"] = [
            1
            if math.isclose(PD_PREV[i], 1.0)
            else (PD[i] - PD_PREV[i]) / (1 - PD_PREV[i])
            for i in range(len(PD))
        ]

        df["ECL_12M"] = np.append(
            (df.EAD * df.LGD / (1.0 + r) * df.Conditional_PD)[1:], 0.0
        )
        df["ECL_Lifetime"] = [
            _ecl_lifetime(df, r, year, lifetime_horizon) for year in df["YEAR"].tolist()
        ]
        df = df.fillna(0.0)

        if drop_tail:
            df = df[df.YEAR <= max_year - lifetime_horizon]

        df.drop(columns=["PD_prev", "Conditional_PD", "PD", "LGD", "EAD"], inplace=True)
        df_list.append(df)

    return pd.concat(df_list, axis=0)


def _ecl_lifetime(df: pd.DataFrame, r: float, start_year: int, n: int):
    end_year = start_year + n
    ecl_data = df[(df.YEAR >= start_year) & (df.YEAR <= end_year)][
        ["YEAR", "LGD", "EAD", "PD"]
    ]

    if len(ecl_data) < 1:
        return None

    PD0 = ecl_data.PD.values[0]
    ecl_data = ecl_data.copy()
    ecl_data["Disc"] = 1 / ((1 + r) ** (ecl_data["YEAR"] - start_year))
    pd_vals = ecl_data["PD"].tolist()
    ecl_data["Conditional_PD"] = (
        [1.0] * len(pd_vals)
        if math.isclose(PD0, 1.0)
        else [(x - PD0) / (1.0 - PD0) for x in pd_vals]
    )
    ecl_data["Conditional_PD_prev"] = [0.0] + ecl_data.Conditional_PD.tolist()[:-1]
    ecl_data["ECL_t"] = (
        ecl_data.LGD
        * ecl_data.EAD
        * ecl_data.Disc
        * (ecl_data.Conditional_PD - ecl_data.Conditional_PD_prev)
    )
    return sum(ecl_data.ECL_t)
