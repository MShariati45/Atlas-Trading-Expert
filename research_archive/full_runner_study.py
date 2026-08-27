import pandas as pd, numpy as np
from pathlib import Path
root=Path('/mnt/data/atlas_flag_runner/work')
a=pd.read_csv(root/'challenger_enriched_events_v0223.csv')
b=pd.read_csv(root/'gbpusd_active_events_v0223.csv')
for d in [a,b]: d['time']=pd.to_datetime(d.time,utc=True)
b=b[(b.time.dt.dayofweek<4)&b.outcome.isin(['WIN','LOSS'])]
c=pd.concat([a,b],ignore_index=True,sort=False).drop_duplicates('event_id')
f=c[c.agent.eq('M15_FLAG_PENNANT')].copy().reset_index(drop=True)
f['year']=f.time.dt.year
# load candles headerless
cdfs={}
for sym in ['EURUSD','GBPUSD']:
    cc=pd.read_csv(root/f'{sym}_M15.csv',header=None,names=['time','open','high','low','close','volume'])
    cc['time']=pd.to_datetime(cc.time,utc=True); cc=cc.sort_values('time').reset_index(drop=True)
    # ATR14 Wilder/simple rolling TR is enough descriptive metric
    prev=cc.close.shift(1)
    tr=pd.concat([(cc.high-cc.low).abs(),(cc.high-prev).abs(),(cc.low-prev).abs()],axis=1).max(axis=1)
    cc['atr14']=tr.rolling(14,min_periods=14).mean()
    cdfs[sym]=cc

def metrics(row,horizon=480):
    cc=cdfs[row.symbol]; t=row.time; idx=int(cc.time.searchsorted(t,'left'))
    if idx>=len(cc): return pd.Series(dtype=float)
    entry=float(row.entry); stop=float(row.stop); risk=abs(entry-stop); d=row.direction.upper()
    atr=cc.iloc[max(0,idx-1)].atr14
    # find first target 2R candle. Since row is a baseline winner, target precedence is accepted for that bar.
    first2=None; pre2_mae=0.0; pre2_mfe=0.0
    for j in range(idx,min(len(cc),idx+horizon+1)):
        bar=cc.iloc[j]
        fav=(bar.high-entry)/risk if d=='LONG' else (entry-bar.low)/risk
        adv=(bar.low-entry)/risk if d=='LONG' else (entry-bar.high)/risk
        pre2_mfe=max(pre2_mfe,fav); pre2_mae=min(pre2_mae,adv)
        if fav>=2:
            first2=j; break
        # if baseline loss may stop first; don't need runner post2
        hitstop=bar.low<=stop if d=='LONG' else bar.high>=stop
        if hitstop: break
    postmax=np.nan; postmin=np.nan; stopped_after2=False; bars_after2=np.nan
    if first2 is not None:
        postmax=2.0; postmin=np.nan
        # begin next candle to avoid unresolved intrabar ordering on first 2R bar
        for k in range(first2+1,min(len(cc),idx+horizon+1)):
            bar=cc.iloc[k]
            fav=(bar.high-entry)/risk if d=='LONG' else (entry-bar.low)/risk
            adv=(bar.low-entry)/risk if d=='LONG' else (entry-bar.high)/risk
            postmax=max(postmax,fav); postmin=adv if np.isnan(postmin) else min(postmin,adv)
            hitstop=bar.low<=stop if d=='LONG' else bar.high>=stop
            if hitstop:
                stopped_after2=True; bars_after2=k-first2; break
        if np.isnan(postmin): postmin=0.0
    return pd.Series({'atr_pips_calc':atr*10000,'stop_atr_calc':abs(entry-stop)/atr if pd.notna(atr) and atr>0 else np.nan,
                      'first2_idx':first2 if first2 is not None else np.nan,'pre2_mae_calc':pre2_mae,
                      'post2_maxR':postmax,'post2_minR':postmin,'stopped_after2':stopped_after2,'bars_after2_to_stop':bars_after2,
                      'hour_utc':t.hour+t.minute/60})

m=f.apply(metrics,axis=1); f=pd.concat([f,m],axis=1)
# baseline winners only for runner study
w=f[f.outcome.eq('WIN')].copy()
w['runner_2p5']=w.post2_maxR>=2.5; w['runner_3']=w.post2_maxR>=3; w['runner_4']=w.post2_maxR>=4; w['runner_5']=w.post2_maxR>=5
f.to_csv(root/'flag_runner_full46_v0225.csv',index=False)
w.to_csv(root/'flag_winners_runner_features_v0225.csv',index=False)
print('full sample',len(f),'wins',len(w),'losses',len(f)-len(w))
print('winner extension counts', {k:int(w[k].sum()) for k in ['runner_2p5','runner_3','runner_4','runner_5']})
print('stopped_after2',int(w.stopped_after2.sum()))
# Compare >=3R runners vs non-runners among 14 winners
for label,mask in [('runner3',w.runner_3),('runner2p5',w.runner_2p5)]:
    print('\n',label,'count',int(mask.sum()),'non',int((~mask).sum()))
    for col in ['stop_pips','atr_pips','stop_atr','stop_atr_calc','fib_pct','hour_utc','pre2_mae_calc','bars_to_resolution']:
        if col not in w.columns: continue
        x=w[mask][col].dropna(); y=w[~mask][col].dropna()
        print(col,'R med',round(x.median(),3),'mean',round(x.mean(),3),'| NR med',round(y.median(),3),'mean',round(y.mean(),3))
    for col in ['pattern','direction','fib_state','symbol']:
        print(col); print(pd.crosstab(w[col],mask,margins=True))
# Entry-time candidate rules and precision/coverage for runner3
w['early_session']=w.hour_utc<10
w['stopatr_ge2']=w.stop_atr_calc>=2
w['bull']=w.direction.eq('LONG')
w['shallow']=w.fib_state.eq('ACTIVE_SHALLOW')
print('\nRULES runner3 precision coverage')
for rule in ['early_session','stopatr_ge2','bull','shallow']:
    sub=w[w[rule]]
    print(rule,'n',len(sub),'runner3',int(sub.runner_3.sum()),'precision',round(sub.runner_3.mean(),3) if len(sub) else None,'coverage',round(sub.runner_3.sum()/max(1,w.runner_3.sum()),3))
# combinations
for name,mask in [('early&stopatr2',w.early_session&w.stopatr_ge2),('early&shallow',w.early_session&w.shallow),('stopatr2&shallow',w.stopatr_ge2&w.shallow),('early&stopatr2&shallow',w.early_session&w.stopatr_ge2&w.shallow)]:
    sub=w[mask]
    print(name,'n',len(sub),'runner3',int(sub.runner_3.sum()),'precision',round(sub.runner_3.mean(),3) if len(sub) else None,'coverage',round(sub.runner_3.sum()/max(1,w.runner_3.sum()),3))
print('\nWINNERS DETAIL')
cols=['symbol','time','pattern','direction','stop_pips','stop_atr_calc','fib_state','fib_pct','hour_utc','pre2_mae_calc','post2_maxR','post2_minR','stopped_after2','year']
print(w[cols].sort_values('post2_maxR',ascending=False).to_string(index=False))
