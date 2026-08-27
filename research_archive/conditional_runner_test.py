import pandas as pd, numpy as np
from pathlib import Path
root=Path('/mnt/data/atlas_flag_runner/work')
f=pd.read_csv(root/'flag_runner_full46_v0225.csv')
f['time']=pd.to_datetime(f.time,utc=True)
# load raw candles
cdfs={}
for sym in ['EURUSD','GBPUSD']:
 c=pd.read_csv(root/f'{sym}_M15.csv',header=None,names=['time','open','high','low','close','volume'])
 c.time=pd.to_datetime(c.time,utc=True); c=c.sort_values('time').reset_index(drop=True); cdfs[sym]=c

def trail_after_2r(row,horizon=480):
    # losses that never win stay -1 baseline; baseline winners use first 2R bar then dynamic 1R trail from next bar
    if row.outcome!='WIN': return -1.0
    c=cdfs[row.symbol]; t=row.time; idx=int(c.time.searchsorted(t,'left'))
    entry=float(row.entry); stop=float(row.stop); risk=abs(entry-stop); d=row.direction.upper()
    first2=None
    for j in range(idx,min(len(c),idx+horizon+1)):
        bar=c.iloc[j]
        fav=(bar.high-entry)/risk if d=='LONG' else (entry-bar.low)/risk
        if fav>=2: first2=j; break
    if first2 is None: return 2.0 # data mismatch fallback baseline
    best=2.0; trail=1.0
    # Use trail from previous completed bar, then update after current bar to avoid same-bar lookahead
    for k in range(first2+1,min(len(c),idx+horizon+1)):
        bar=c.iloc[k]
        adv=(bar.low-entry)/risk if d=='LONG' else (entry-bar.high)/risk
        if adv<=trail: return float(trail)
        fav=(bar.high-entry)/risk if d=='LONG' else (entry-bar.low)/risk
        best=max(best,fav); trail=max(1.0,best-1.0)
    # close at last close research horizon
    bar=c.iloc[min(len(c)-1,idx+horizon)]
    r=(bar.close-entry)/risk if d=='LONG' else (entry-bar.close)/risk
    return float(max(r,trail)) if r>=trail else float(trail)

f['trail2R_R']=f.apply(trail_after_2r,axis=1)
# baseline 2R wins/-1 losses
f['baseline_R']=np.where(f.outcome.eq('WIN'),2.0,-1.0)
# features available by 2R / entry
# Use calc ATR from prior study where present; for added rows compute approximate stored stop_atr if available
if 'stop_atr_calc' not in f.columns: f['stop_atr_calc']=np.nan
f['hour_utc']=f.time.dt.hour+f.time.dt.minute/60
f['year']=f.time.dt.year
# define predeclared simple rules
rules={
 'ALL_2R_WINNERS': f.outcome.eq('WIN'),
 'BULL_FLAG_ONLY': f.outcome.eq('WIN') & f.direction.eq('LONG') & f.pattern.eq('BULL_FLAG'),
 'SHALLOW_ONLY': f.outcome.eq('WIN') & f.fib_state.eq('ACTIVE_SHALLOW'),
 'FAST_TO_2R_LE30': f.outcome.eq('WIN') & (f.bars_to_resolution<=30),
 'BULL_AND_SHALLOW': f.outcome.eq('WIN') & f.direction.eq('LONG') & f.fib_state.eq('ACTIVE_SHALLOW'),
}
print('baseline total',f.baseline_R.sum())
rows=[]
for name,mask in rules.items():
    rr=f.baseline_R.copy(); rr.loc[mask]=f.loc[mask,'trail2R_R']
    for period,pmask in [('ALL',pd.Series(True,index=f.index)),('DEV_2013_2017',f.year<=2017),('HOLDOUT_2018_2021',f.year>=2018)]:
        sub=rr[pmask]
        base=f.loc[pmask,'baseline_R']
        rows.append((name,period,len(sub),round(base.sum(),3),round(sub.sum(),3),round(sub.sum()-base.sum(),3),int(mask[pmask].sum())))
print('rule period N baseline challenger delta managed')
for x in rows: print(*x)
print('\nWinner trail outcomes')
print(f[f.outcome.eq('WIN')][['symbol','time','pattern','direction','year','baseline_R','trail2R_R','bars_to_resolution']].to_string(index=False))
f.to_csv(root/'flag_conditional_runner_v0225.csv',index=False)
