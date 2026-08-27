"""Legacy pre-v0.23 dashboard launcher.

Disabled intentionally in v0.23.6 because it used the obsolete universal
H4/H1 + Fibonacci-first gating path. Use run_m15_first_observer.py for the
audited four-symbol strategy.
"""
from __future__ import annotations

def main() -> int:
    print("LEGACY_LAUNCHER_DISABLED: use run_m15_first_observer.py (v0.23.6 audited M15-first profile).")
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
