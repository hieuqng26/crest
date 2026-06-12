"""
Run this once to generate test CSV files for the MST platform.
  python generate_test_data.py
"""
import csv, math, random
from pathlib import Path

random.seed(42)

# ── 1. PD Corporate  (classification — target: default_flag) ─────────────────
def pd_corporate():
    rows = []
    sectors = ['Manufacturing', 'Retail', 'Finance', 'Energy', 'Technology', 'Healthcare']
    ratings = ['AAA', 'AA', 'A', 'BBB', 'BB', 'B', 'CCC']
    rating_pd = {'AAA': 0.001, 'AA': 0.003, 'A': 0.008, 'BBB': 0.020,
                 'BB': 0.055, 'B': 0.110, 'CCC': 0.280}

    for i in range(300):
        rating   = random.choices(ratings, weights=[5, 10, 20, 30, 20, 10, 5])[0]
        base_pd  = rating_pd[rating]
        leverage = round(random.gauss(3.5, 1.2), 2)
        icr      = round(max(0.5, random.gauss(6.0, 2.5)), 2)   # interest coverage ratio
        cr       = round(max(0.5, random.gauss(1.8, 0.5)), 2)   # current ratio
        dte      = round(max(0.1, random.gauss(1.2, 0.6)), 2)   # debt-to-equity
        roe      = round(random.gauss(0.12, 0.06), 4)
        roa      = round(random.gauss(0.05, 0.03), 4)
        ead      = round(random.uniform(200_000, 5_000_000), 0)
        sector   = random.choice(sectors)
        year     = random.choice([2021, 2022, 2023, 2024])

        # Synthesise default probability from financials
        stress   = (leverage / 5) + (1 / max(icr, 0.1)) + (dte / 3) - (roe * 2)
        adj_pd   = min(0.95, max(0.001, base_pd * (1 + stress * 0.3)))
        default_flag = 1 if random.random() < adj_pd else 0

        rows.append({
            'obligor_id':        f'CORP{i+1:04d}',
            'year':              year,
            'rating':            rating,
            'sector':            sector,
            'leverage_ratio':    leverage,
            'interest_coverage': icr,
            'current_ratio':     cr,
            'debt_to_equity':    dte,
            'roe':               roe,
            'roa':               roa,
            'ead':               int(ead),
            'default_flag':      default_flag,
        })
    return rows

# ── 2. PD Retail Mortgage  (classification — target: default_flag) ────────────
def pd_retail():
    rows = []
    regions = ['North', 'South', 'East', 'West', 'Central']
    for i in range(250):
        ltv         = round(random.uniform(0.30, 0.95), 3)
        dti         = round(random.uniform(0.10, 0.55), 3)  # debt-to-income
        credit_score = int(random.gauss(680, 80))
        credit_score = max(300, min(850, credit_score))
        loan_age    = round(random.uniform(0.5, 15.0), 1)
        balance     = round(random.uniform(50_000, 800_000), 0)
        region      = random.choice(regions)
        employed    = 1 if random.random() > 0.08 else 0

        base_pd = 0.04 + ltv * 0.12 + dti * 0.15 - (credit_score - 500) / 3000
        base_pd = min(0.90, max(0.002, base_pd))
        default_flag = 1 if random.random() < base_pd else 0

        rows.append({
            'loan_id':      f'MORT{i+1:04d}',
            'region':       region,
            'ltv_ratio':    ltv,
            'dti_ratio':    dti,
            'credit_score': credit_score,
            'loan_age_yrs': loan_age,
            'balance':      int(balance),
            'employed':     employed,
            'default_flag': default_flag,
        })
    return rows

# ── 3. LGD  (regression — target: lgd) ───────────────────────────────────────
def lgd_dataset():
    rows = []
    collateral_types = ['Real Estate', 'Equipment', 'Receivables', 'Inventory', 'Unsecured']
    collateral_haircut = {'Real Estate': 0.25, 'Equipment': 0.40,
                          'Receivables': 0.50, 'Inventory': 0.60, 'Unsecured': 0.80}
    for i in range(200):
        col_type    = random.choices(
            collateral_types, weights=[40, 20, 15, 10, 15])[0]
        base_lgd    = collateral_haircut[col_type]
        ltv         = round(random.uniform(0.20, 1.10), 3)
        time_in_default = round(random.uniform(0.5, 4.0), 1)  # years
        outstanding = round(random.uniform(50_000, 3_000_000), 0)
        recovery    = round(random.uniform(0, outstanding * (1 - base_lgd * 0.8)), 0)
        lgd         = round(min(1.0, max(0.0, base_lgd + random.gauss(0, 0.08)
                               + ltv * 0.05 + time_in_default * 0.02)), 4)

        rows.append({
            'loan_id':            f'LGD{i+1:04d}',
            'collateral_type':    col_type,
            'ltv_ratio':          ltv,
            'outstanding_balance': int(outstanding),
            'recovery_amount':    int(recovery),
            'time_in_default_yrs': time_in_default,
            'lgd':                lgd,
        })
    return rows

# ── 4. Macro quarterly time-series (for ARIMA / Ridge — target: pd_rate) ─────
def macro_ts():
    rows = []
    # Start 2010-Q1, 48 quarters to 2021-Q4
    pd_rate = 0.018
    gdp     = 2.5
    unemp   = 6.5
    infl    = 2.1
    spread  = 1.20

    quarters = []
    for year in range(2010, 2022):
        for q in range(1, 5):
            quarters.append(f'{year}-Q{q}')

    for period in quarters:
        gdp    += random.gauss(0, 0.4)
        unemp  += random.gauss(0, 0.2)
        infl   += random.gauss(0, 0.15)
        spread += random.gauss(0, 0.08)
        vix     = round(max(10, random.gauss(18, 6)), 1)

        # PD rate loosely correlated with macro
        shock   = -gdp * 0.003 + unemp * 0.002 + spread * 0.005
        pd_rate = max(0.002, min(0.12, pd_rate + shock + random.gauss(0, 0.001)))

        rows.append({
            'period':           period,
            'gdp_growth':       round(gdp, 2),
            'unemployment_rate': round(max(3.0, min(15.0, unemp)), 2),
            'inflation_rate':   round(max(0.0, min(8.0, infl)), 2),
            'credit_spread':    round(max(0.3, spread), 3),
            'vix':              vix,
            'pd_rate':          round(pd_rate, 5),
        })
    return rows

# ── Write CSVs ────────────────────────────────────────────────────────────────
def write(name, rows):
    path = Path(name)
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f'  {path}  ({len(rows)} rows)')

if __name__ == '__main__':
    print('Generating test datasets…')
    write('pd_corporate_2024.csv',   pd_corporate())
    write('pd_retail_mortgage.csv',  pd_retail())
    write('lgd_dataset.csv',         lgd_dataset())
    write('macro_quarterly.csv',     macro_ts())
    print('Done.')
