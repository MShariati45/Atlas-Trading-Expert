
import argparse, json
from pathlib import Path
from atlas.validation.h4_validator import validate_h4, write_validation

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="historical_data/one_year/bars")
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--out", default="h4_validation_output")
    args=ap.parse_args()
    src=Path(args.data_dir)/f"{args.symbol}_H4.csv"
    if not src.exists():
        raise SystemExit(f"Missing {src}")
    result=validate_h4(src,args.symbol)
    path=write_validation(result,args.out)
    print(json.dumps({
        "symbol": result.symbol,
        "bars": result.bars,
        "trend": result.current_trend,
        "phase": result.phase,
        "strategic_origin": result.strategic_origin,
        "strategic_endpoint": result.strategic_endpoint,
        "control_pivot": result.control_pivot,
        "events": len(result.events),
        "trendline_analysis": result.trendline_analysis,
        "output": str(path)
    }, indent=2))
    input("Press Enter to close...")
if __name__=="__main__": main()
