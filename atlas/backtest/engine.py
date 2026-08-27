
from collections import defaultdict
from .models import PaperTrade

class HistoricalPaperHarness:
    """Deterministic paper outcome engine for already-approved Atlas candidates.

    It never manufactures signals. Candidate generation must come from the normal
    Atlas H4/H1/Fib/M15/Coordinator/Supervisor pipeline.
    """
    def __init__(self, target_r=2.0, be_trigger_r=1.4):
        self.target_r = float(target_r)
        self.be_trigger_r = float(be_trigger_r)

    def resolve(self, trade: PaperTrade, future_bars):
        risk = abs(trade.entry - trade.stop)
        if risk <= 0:
            trade.outcome, trade.reject_reason = "INVALID", "NON_POSITIVE_RISK"
            return trade
        long = trade.direction.upper() == "LONG"
        best = worst = 0.0
        stop = trade.stop
        be = False
        for bar in future_bars:
            hi, lo = float(bar["high"]), float(bar["low"])
            fav = (hi-trade.entry)/risk if long else (trade.entry-lo)/risk
            adv = (trade.entry-lo)/risk if long else (hi-trade.entry)/risk
            best, worst = max(best, fav), max(worst, adv)
            # Conservative same-bar ordering: if both stop and a profit trigger
            # are touched, assume the adverse event happened first.
            stop_hit = lo <= stop if long else hi >= stop
            target_hit = hi >= trade.target if long else lo <= trade.target
            if stop_hit:
                trade.outcome = "BE" if be and stop == trade.entry else "SL"
                trade.realized_r = 0.0 if trade.outcome == "BE" else -1.0
                trade.exit_time, trade.exit_price = str(bar.get("time","")), stop
                break
            if target_hit:
                trade.outcome, trade.realized_r = "TP", self.target_r
                trade.exit_time, trade.exit_price = str(bar.get("time","")), trade.target
                break
            if not be and fav >= self.be_trigger_r:
                be = True
                stop = trade.entry
                trade.be_triggered = True
        trade.mae_r, trade.mfe_r = round(worst,4), round(best,4)
        return trade

def summarize(trades):
    resolved=[t for t in trades if t.realized_r is not None]
    by_symbol=defaultdict(list)
    for t in resolved: by_symbol[t.symbol].append(t)
    def stats(rows):
        n=len(rows); total=sum(t.realized_r for t in rows)
        wins=sum(t.realized_r>0 for t in rows)
        return {"trades":n,"wins":wins,"win_rate":round(100*wins/n,2) if n else 0,
                "net_r":round(total,2),"avg_r":round(total/n,3) if n else 0}
    return {"overall":stats(resolved),
            "by_symbol":{s:stats(r) for s,r in sorted(by_symbol.items())}}
