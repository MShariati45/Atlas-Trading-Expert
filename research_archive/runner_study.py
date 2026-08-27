import pandas as pd, numpy as np
from pathlib import Path
root=Path('/mnt/data/atlas_flag_runner/work')
df=pd.read_csv(root/'challenger_enriched_events_v0223.csv')
f=df[df.agent.eq('M15_FLAG_PENNANT')].copy().drop_duplicates('event_id').reset_index(drop=True)
cdfs={}
for sym in ['EURUSD','GBPUSD']:
    c=pd.read_csv(root/f'{sym}_M15.csv', header=None, names=['time','open','high','low','close','volume'])
    tc='time'
    c[tc]=pd.to_datetime(c[tc], utc=True)
    c=c.sort_values(tc).reset_index(drop=True)
    cdfs[sym]=(c,tc)

def path_metrics(row,horizon=480):
    c,tc=cdfs[row.symbol]
    t=pd.to_datetime(row.time,utc=True)
    idx=int(c[tc].searchsorted(t,side='left'))
    if idx>=len(c): return pd.Series(dtype=float)
    entry=float(row.entry); stop=float(row.stop); risk=abs(entry-stop); d=row.direction.upper()
    w=c.iloc[idx:idx+horizon+1]
    maxr=-999.0; minr=999.0; first2=None; post2_min=np.nan; post2_max=np.nan; stop_hit=False
    milestones={m:False for m in [1,1.5,2,2.5,3,4,5]}
    for j,bar in enumerate(w.to_dict('records')):
        high=float(bar.get('high',bar.get('High'))); low=float(bar.get('low',bar.get('Low')))
        if d=='LONG':
            fav=(high-entry)/risk; adv=(low-entry)/risk; hitstop=low<=stop
        else:
            fav=(entry-low)/risk; adv=(entry-high)/risk; hitstop=high>=stop
        maxr=max(maxr,fav); minr=min(minr,adv)
        for m in milestones: milestones[m]=milestones[m] or fav>=m
        if first2 is None and fav>=2: first2=j
        if first2 is not None:
            post2_min=adv if np.isnan(post2_min) else min(post2_min,adv)
            post2_max=fav if np.isnan(post2_max) else max(post2_max,fav)
        if hitstop:
            stop_hit=True
            break
    out={'cf_maxR_before_stop':maxr,'cf_minR_before_stop':minr,'cf_stop_hit':stop_hit,
         'first2_bar':np.nan if first2 is None else first2,'post2_minR_before_stop':post2_min,
         'post2_maxR_before_stop':post2_max,'hour_utc':t.hour+t.minute/60.0}
    out.update({f'reach_{str(m).replace(".","p")}R':v for m,v in milestones.items()})
    return pd.Series(out)

pm=f.apply(path_metrics,axis=1)
f=pd.concat([f,pm],axis=1)
for x in [2.5,3,4,5]: f[f'runner_{str(x).replace(".","p")}']=f.cf_maxR_before_stop>=x
f.to_csv(root/'flag_runner_features_v0225.csv',index=False)
print('N',len(f),'baseline wins',int((f.R==2).sum()),'losses',int((f.R==-1).sum()))
print('milestones',{m:int(f[f'reach_{str(m).replace(".","p")}R'].sum()) for m in [1,1.5,2,2.5,3,4,5]})
r2=f[f.reach_2R].copy(); r2['runner3']=r2.cf_maxR_before_stop>=3
print('reach2 N',len(r2),'runner3',int(r2.runner3.sum()),'nonrunner',int((~r2.runner3).sum()))
cols=['stop_pips','atr_pips','stop_atr','fib_pct','hour_utc','mae_R']
for col in cols:
    a=r2[r2.runner3][col].dropna(); b=r2[~r2.runner3][col].dropna()
    print(col,'runner_mean',round(a.mean(),3),'runner_med',round(a.median(),3),'non_mean',round(b.mean(),3),'non_med',round(b.median(),3))
print('PATTERN')
print(pd.crosstab(r2.pattern,r2.runner3,margins=True))
print('DIRECTION')
print(pd.crosstab(r2.direction,r2.runner3,margins=True))
print('FIB')
print(pd.crosstab(r2.fib_state,r2.runner3,margins=True))
print('YEAR')
print(pd.crosstab(r2.year,r2.runner3,margins=True))
print('REACH2 TRADES')
print(r2[['symbol','time','pattern','direction','stop_pips','stop_atr','fib_state','fib_pct','cf_maxR_before_stop','post2_minR_before_stop','year']].sort_values('cf_maxR_before_stop',ascending=False).to_string(index=False))
