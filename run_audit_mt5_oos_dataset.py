from __future__ import annotations
import argparse,json
from dataclasses import asdict
from pathlib import Path
from atlas.validation.broker_native_oos import audit_dataset, load_historical_news_csv

def main():
    ap=argparse.ArgumentParser(description='Audit broker-native MT5 out-of-sample dataset before Atlas replay')
    ap.add_argument('--dataset',required=True)
    ap.add_argument('--historical-news',default=None)
    ap.add_argument('--out',default=None)
    args=ap.parse_args()
    a=asdict(audit_dataset(args.dataset))
    news,news_reasons=load_historical_news_csv(args.historical_news)
    result={'dataset':a,'historical_news':{'events':len(news),'reason_codes':news_reasons},'replay_permission':bool(a['ok'] and 'HISTORICAL_NEWS_LOADED' in news_reasons)}
    text=json.dumps(result,indent=2)
    if args.out: Path(args.out).write_text(text,encoding='utf-8')
    print(text)
    return 0 if a['ok'] else 2
if __name__=='__main__': raise SystemExit(main())
