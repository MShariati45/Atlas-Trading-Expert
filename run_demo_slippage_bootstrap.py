from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POLICY_FILE = ROOT / "config" / "broker_cost_policy.json"
STATE_FILE = ROOT / "runtime" / "supervised_demo_state.json"

BOOTSTRAP_VERSION = "0.1-LOCKED"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    print("=" * 64)
    print("ATLAS DEMO SLIPPAGE BOOTSTRAP")
    print(f"Version: {BOOTSTRAP_VERSION}")
    print("MODE: LOCKED / INSPECTION ONLY")
    print("NO MT5 ORDER CAN BE SENT BY THIS VERSION")
    print("=" * 64)

    errors: list[str] = []

    try:
        policy = load_json(POLICY_FILE)
        print(f"[OK] Broker cost policy found: {POLICY_FILE}")
        print(f"     approved={policy.get('approved')}")
        print(f"     mode={policy.get('mode')}")
        print(f"     execution_validated={policy.get('execution_validated')}")
    except Exception as exc:
        errors.append(f"POLICY_READ_FAILED: {exc}")

    try:
        state = load_json(STATE_FILE)
        readiness = state.get("readiness", {})
        print(f"[OK] Supervised DEMO state found: {STATE_FILE}")
        print(f"     account_id={state.get('account_id')}")
        print(f"     mode={state.get('mode')}")
        print(f"     real_money={state.get('real_money')}")
        print(f"     execution_enabled={readiness.get('execution_transport_enabled')}")
        print(f"     global_blockers={readiness.get('global_blockers')}")
    except Exception as exc:
        errors.append(f"STATE_READ_FAILED: {exc}")

    print("-" * 64)

    if errors:
        print("STATUS: NOT READY FOR BOOTSTRAP DEVELOPMENT")
        for error in errors:
            print(f"[ERROR] {error}")
        return 1

    print("STATUS: LOCKED SCAFFOLD VERIFIED")
    print("NEXT: add DEMO identity + protected transport composition")
if __name__ == "__main__":
    raise SystemExit(main())