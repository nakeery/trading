import pandas as pd

df = pd.read_csv('data/qqq_indicators.csv', index_col=0, parse_dates=True)
cutoff = pd.Timestamp('2024-05-12')
w = df[df.index >= cutoff]
print(w[w['atm_iv_30d'].isna()].index.tolist())

amd = pd.read_csv('data/amd_indicators.csv', index_col=0, parse_dates=True)
qqq = pd.read_csv('data/qqq_indicators.csv', index_col=0, parse_dates=True)
amd_fail = set(amd[amd['atm_iv_30d'].isna() & (amd.index >= cutoff)].index)
qqq_fail = set(qqq[qqq['atm_iv_30d'].isna() & (qqq.index >= cutoff)].index)
print("Shared:", len(amd_fail & qqq_fail), "QQQ-only:", len(qqq_fail - amd_fail))