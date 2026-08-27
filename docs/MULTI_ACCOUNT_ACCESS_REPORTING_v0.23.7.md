# Atlas v0.23.7 — Multi-account, access and reporting architecture

## Production design decision
Atlas uses one shared, immutable approved strategy signal and isolated account execution plans. Each account has independent equity, risk percentage, broker identity, report namespace and MT5 terminal-instance binding.

## Multiple MetaTrader terminals
The MetaTrader5 Python binding is terminal-session oriented. Production multi-account operation therefore uses **one isolated worker/process per MT5 terminal/account**. Atlas must never multiplex two concurrently controlled accounts through one shared mutable MT5 bridge session. The central Supervisor publishes an immutable approved signal; each account worker independently applies its account risk plan and execution lock.

## Account reports
Every journal/trade record must carry `account_id`. Reports are partitioned by account before metrics are computed. Each account report includes trades, wins/losses, win rate, net R, expectancy, profit factor, maximum drawdown, consecutive wins/losses and pattern-level net R. Future UI sections may add balance/equity curves, deposits/withdrawals and broker costs without changing account isolation.

## Authentication and authorization
Roles:
- `ADMIN`: may view/manage all configured accounts subject to the global execution safety lock.
- `ACCOUNT_OWNER`: may view/control only explicitly assigned account IDs.
- `TRAINING_VIEWER`: cannot view or control any real account; may view only anonymized training output.

Passwords are never stored in plaintext. The reference password utility uses salted PBKDF2-HMAC-SHA256. A deployed web service should store only password hashes and use secure HTTPS sessions/cookies plus rate limiting and optional MFA.

## Training/privacy view
Training output strips account identifiers and common owner/contact/login fields and aggregates across accounts. It must not expose account number, owner name, email, phone, server/login details, address, password/secrets, or per-owner labels.

## Status
This checkpoint implements and tests the domain/security/reporting contracts. It does **not** expose an internet-facing login server yet; that belongs to the dashboard deployment phase. MT5 execution remains hard-locked.
