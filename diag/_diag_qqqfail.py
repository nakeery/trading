"""
Debug a single known-failing QQQ date to trace where get_historical_iv_snapshot
is dying: reference fetch, no monthly, or no agg data.
"""
import datetime, sys
sys.path.insert(0, '.')
from modules.massive import _fetch_historical_contracts, _fetch_agg_price

ticker = 'QQQ'
date   = datetime.date(2025, 10, 14)
spot   = 596.48

def is_monthly(exp_str):
    d = datetime.date.fromisoformat(exp_str)
    return d.weekday() == 4 and 15 <= d.day <= 21

print(f"--- Diagnosing {ticker} {date} (spot≈{spot}) ---\n")

# Stage A: front calls
front = _fetch_historical_contracts(ticker, date, 23, 44, spot*0.90, spot*1.10, contract_type='call')
print(f"front_calls returned: {len(front)} contracts")
monthlies = [c for c in front if is_monthly(c.get('expiration_date', ''))]
print(f"  monthly subset: {len(monthlies)}")
for c in front[:8]:
    exp = c.get('expiration_date', '')
    flag = ' <-- MONTHLY' if is_monthly(exp) else ''
    print(f"  {c.get('ticker')}  exp={exp}  strike={c.get('strike_price')}{flag}")

print()
# Sort monthlies by ATM proximity (same as get_historical_iv_snapshot does)
monthlies.sort(key=lambda p: abs(float(p.get('strike_price',0)) - spot))
print(f"Checking agg prices for ATM-nearest monthly contracts:")
for c in monthlies[:8]:
    opt    = c.get('ticker')
    exp    = c.get('expiration_date')
    strike = float(c.get('strike_price'))
    price  = _fetch_agg_price(opt, date)
    print(f"  {opt}  exp={exp}  strike={strike}  agg={price}")
