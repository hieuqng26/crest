import numpy as np
from pydantic import BaseModel, Field
from scipy.stats import jarque_bera as sp_jarque_bera
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.arima.model import ARIMA as _ARIMA
from statsmodels.tsa.stattools import adfuller

from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.diagnostics import _finite, _test


class ARIMAParams(BaseModel):
    p: int = Field(default=1, ge=0)
    d: int = Field(default=1, ge=0)
    q: int = Field(default=1, ge=0)


class ARIMAPlugin(BaseMLModel):
    family = "timeseries"
    algorithm = "ARIMA"
    param_schema = ARIMAParams

    def __init__(self):
        self._result = None
        self._order = (1, 1, 1)
        self._y_train = None

    def fit(self, X, y, params: ARIMAParams) -> None:
        self._order = (params.p, params.d, params.q)
        self._y_train = np.asarray(y, dtype=float).ravel()
        model = _ARIMA(y, order=self._order)
        self._result = model.fit()

    def predict(self, X) -> np.ndarray:
        n = len(X) if hasattr(X, "__len__") else 1
        return self._result.forecast(steps=n)

    def _coef_table(self):
        """Per-term inference (AR/MA/const/sigma²) from the fitted ARIMAResults."""
        res = self._result
        try:
            names = list(res.param_names)
            params = np.asarray(res.params, dtype=float)
            bse = np.asarray(res.bse, dtype=float)
            pvals = np.asarray(res.pvalues, dtype=float)
            tvals = np.asarray(res.tvalues, dtype=float)
            ci = np.asarray(res.conf_int(), dtype=float)
            table = []
            for i, name in enumerate(names):
                if name == "sigma2":  # error-variance term isn't a coefficient
                    continue
                table.append(
                    {
                        "feature": str(name),
                        "coef": _finite(params[i]),
                        "std_err": _finite(bse[i]),
                        "z": _finite(tvals[i]),
                        "p_value": _finite(pvals[i]),
                        "ci_lower": _finite(ci[i, 0]),
                        "ci_upper": _finite(ci[i, 1]),
                    }
                )
            return table
        except Exception:
            return []

    def diagnostics(self, X, y) -> dict:
        res = self._result
        resid = np.asarray(res.resid, dtype=float)
        fitted = np.asarray(res.fittedvalues, dtype=float)
        y = np.asarray(y, dtype=float).ravel()
        m = min(len(y), len(fitted))
        err = y[:m] - fitted[:m]
        mae = float(np.mean(np.abs(err)))
        rmse = float(np.sqrt(np.mean(err**2)))
        mape = float(np.mean(np.abs(err / np.where(y[:m] == 0, 1e-8, y[:m]))) * 100)

        # Ljung–Box: residual autocorrelation up to lag 10 (report the last lag).
        try:
            lb = acorr_ljungbox(resid, lags=10, return_df=True)
            lb_stat = float(lb["lb_stat"].iloc[-1])
            lb_p = float(lb["lb_pvalue"].iloc[-1])
            ljung_box = {
                "stat": _finite(lb_stat),
                "p_value": _finite(lb_p),
                "passed": bool(lb_p > 0.05),  # pass = no leftover autocorrelation
                "lags": 10,
            }
            ljung_box_p = _finite(lb_p)
        except Exception:
            ljung_box, ljung_box_p = None, None

        # Residual normality.
        try:
            jb_stat, jb_p = sp_jarque_bera(resid)
            jarque_bera = _test(jb_stat, jb_p, passed=jb_p > 0.05)
        except Exception:
            jarque_bera = None

        # Residual heteroskedasticity (statsmodels break-variance test).
        try:
            het_stat, het_p = res.test_heteroskedasticity("breakvar")[0]
            heteroskedasticity = _test(het_stat, het_p, passed=het_p > 0.05)
        except Exception:
            heteroskedasticity = None

        # Augmented Dickey–Fuller stationarity of the input series (pass = the
        # series is already stationary → indicates whether the chosen d differences
        # enough).
        try:
            adf_stat, adf_p = adfuller(self._y_train)[:2]
            adf_test = {
                "stat": _finite(adf_stat),
                "p_value": _finite(adf_p),
                "passed": bool(adf_p < 0.05),
                "n_diff": int(self._order[1]),
            }
        except Exception:
            adf_test = None

        try:
            hqic = float(res.hqic)
        except Exception:
            hqic = None

        arima_stats = {
            "order": list(self._order),
            "n_obs": int(res.nobs),
            "aic": _finite(res.aic),
            "bic": _finite(res.bic),
            "hqic": _finite(hqic),
            "log_likelihood": _finite(res.llf),
            "ljung_box": ljung_box,
            "jarque_bera": jarque_bera,
            "heteroskedasticity": heteroskedasticity,
            "adf_test": adf_test,
        }

        return {
            "mae": mae,
            "rmse": rmse,
            "mape": mape,
            "aic": float(res.aic),
            "bic": float(res.bic),
            "ljung_box_p": ljung_box_p,
            "residuals": resid.tolist(),
            "order": self._order,
            "coef_table": self._coef_table(),
            "arima_stats": arima_stats,
        }
