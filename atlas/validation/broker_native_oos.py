from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import csv, hashlib, json

REQUIRED_TIMEFRAMES=("D1","H4","H1","M15")


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def parse_dt(v:str)->datetime:
    dt=datetime.fromisoformat(v.replace('Z','+00:00'))
    if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

@dataclass(slots=True)
class FileAudit:
    symbol:str; timeframe:str; file:str; rows:int; first_bar_utc:str|None; last_bar_utc:str|None
    hash_ok:bool; monotonic:bool; duplicate_timestamps:int; malformed_rows:int; spread_observations:int

@dataclass(slots=True)
class DatasetAudit:
    ok:bool; manifest_path:str; broker:str; account_id:str; symbols:list[str]; files:list[dict]; reason_codes:list[str]


def audit_dataset(root:str|Path)->DatasetAudit:
    root=Path(root); mp=root/'manifest.json'; reasons=[]; audits=[]
    if not mp.exists():
        return DatasetAudit(False,str(mp),'','',[],[],['MANIFEST_MISSING'])
    m=json.loads(mp.read_text(encoding='utf-8'))
    symbols=sorted(m.get('symbol_metadata',{}).keys())
    recs=m.get('records',[])
    by={(r['symbol'],r['timeframe']):r for r in recs}
    for s in symbols:
        for tf in REQUIRED_TIMEFRAMES:
            if (s,tf) not in by: reasons.append(f'REQUIRED_HISTORY_MISSING:{s}:{tf}')
    for r in recs:
        p=root/r['file']; malformed=0; dups=0; monotonic=True; prev=None; first=None; last=None; rows=0; spread_obs=0
        if not p.exists():
            reasons.append(f'FILE_MISSING:{r["symbol"]}:{r["timeframe"]}')
            audits.append(asdict(FileAudit(r['symbol'],r['timeframe'],r['file'],0,None,None,False,False,0,1,0))); continue
        with p.open(newline='',encoding='utf-8') as f:
            reader=csv.DictReader(f)
            for row in reader:
                try:
                    dt=parse_dt(row['time_utc']); float(row['open']); float(row['high']); float(row['low']); float(row['close'])
                    if row.get('spread_points') not in (None,''): spread_obs += 1
                except Exception:
                    malformed += 1; continue
                rows += 1; first=first or dt; last=dt
                if prev is not None:
                    if dt==prev: dups += 1
                    if dt<=prev: monotonic=False
                prev=dt
        hash_ok=sha256(p)==r.get('sha256')
        if not hash_ok: reasons.append(f'HASH_MISMATCH:{r["symbol"]}:{r["timeframe"]}')
        if malformed: reasons.append(f'MALFORMED_ROWS:{r["symbol"]}:{r["timeframe"]}:{malformed}')
        if dups: reasons.append(f'DUPLICATE_TIMESTAMPS:{r["symbol"]}:{r["timeframe"]}:{dups}')
        if not monotonic: reasons.append(f'NON_MONOTONIC:{r["symbol"]}:{r["timeframe"]}')
        if rows != int(r.get('rows',rows)): reasons.append(f'ROW_COUNT_MISMATCH:{r["symbol"]}:{r["timeframe"]}')
        audits.append(asdict(FileAudit(r['symbol'],r['timeframe'],r['file'],rows,first.isoformat() if first else None,last.isoformat() if last else None,hash_ok,monotonic,dups,malformed,spread_obs)))
    return DatasetAudit(not reasons,str(mp),str(m.get('broker','')),str(m.get('account_id','')),symbols,audits,reasons or ['DATASET_AUDIT_PASSED'])


def load_historical_news_csv(path:str|Path|None)->tuple[list[dict],list[str]]:
    if not path: return [],['HISTORICAL_NEWS_UNAVAILABLE']
    p=Path(path)
    if not p.exists(): return [],['HISTORICAL_NEWS_UNAVAILABLE']
    rows=[]; reasons=[]
    with p.open(newline='',encoding='utf-8') as f:
        for r in csv.DictReader(f):
            try:
                dt=parse_dt(r['event_time_utc'])
                rows.append({'event_time_utc':dt.isoformat(),'currency':r['currency'].upper(),'impact':r.get('impact','HIGH').upper(),'title':r.get('title',''),'event_id':r.get('event_id','')})
            except Exception:
                reasons.append('HISTORICAL_NEWS_MALFORMED_ROW')
    return rows, reasons or ['HISTORICAL_NEWS_LOADED']
