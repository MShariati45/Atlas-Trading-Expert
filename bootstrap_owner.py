from __future__ import annotations

import argparse
from pathlib import Path
import secrets

from atlas.security import SQLiteAuthStore, TOTP, UserRole

ROOT = Path(__file__).resolve().parent


def main() -> int:
    p = argparse.ArgumentParser(description="Bootstrap the first Atlas OWNER in an empty staging auth database")
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    args = p.parse_args()
    store = SQLiteAuthStore(ROOT / "runtime" / "atlas_auth.sqlite3")
    secret = TOTP.generate_secret()
    user = store.create_user(actor=None, username=args.username, password=args.password, role=UserRole.OWNER, require_mfa=True, mfa_secret=secret)
    print("Created:", user.user_id, user.username, user.role.value)
    print("TOTP_SECRET_HEX:", secret.hex())
    print("Store this secret securely; it is not recoverable through the web API.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
