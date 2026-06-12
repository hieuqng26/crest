import numpy as np
from statsmodels.tsa.arima.model import ARIMA as _ARIMA
from pydantic import BaseModel, Field
from project.core.model_registry.base import BaseMLModel


class ARIMAParams(BaseModel):
    p: int = Field(default=1, ge=0)
    d: int = Field(default=1, ge=0)
    q: int = Field(default=1, ge=0)


class ARIMAPlugin(BaseMLModel):
    family = 'timeseries'
    algorithm = 'ARIMA'
    param_schema = ARIMAParams

    def __init__(self):
        self._result = None
        self._order = (1, 1, 1)

    def fit(self, X, y, params: ARIMAParams) -> None:
        self._order = (params.p, params.d, params.q)
        model = _ARIMA(y, order=self._order)
        self._result = model.fit()

    def predict(self, X) -> np.ndarray:
        n = len(X) if hasattr(X, '__len__') else 1
        return self._result.forecast(steps=n)

    def diagnostics(self, X, y) -> dict:
        from statsmodels.stats.diagnostic import acorr_ljungbox
        resid = self._result.resid
        lb = acorr_ljungbox(resid, lags=10, return_df=True)
        fitted = self._result.fittedvalues
        mae  = float(np.mean(np.abs(y - fitted[:len(y)])))
        rmse = float(np.sqrt(np.mean((y - fitted[:len(y)]) ** 2)))
        mape_vals = np.abs((y - fitted[:len(y)]) / np.where(y == 0, 1e-8, y))
        return {
            'mae': mae,
            'rmse': rmse,
            'mape': float(np.mean(mape_vals) * 100),
            'aic': float(self._result.aic),
            'bic': float(self._result.bic),
            'ljung_box_p': float(lb['lb_pvalue'].iloc[-1]),
            'residuals': resid.tolist(),
            'order': self._order
        }
