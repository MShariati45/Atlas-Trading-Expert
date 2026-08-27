from __future__ import annotations

WATCHLIST_CURRENCY_MAP: dict[str, frozenset[str]] = {
    "EURUSD": frozenset({"EUR", "USD"}),
    "USDJPY": frozenset({"USD", "JPY"}),
    "USDCAD": frozenset({"USD", "CAD"}),
    "XAUUSD": frozenset({"USD"}),
}


def currencies_for_symbols(symbols: list[str] | tuple[str, ...] | set[str]) -> frozenset[str]:
    out: set[str] = set()
    for symbol in symbols:
        out.update(WATCHLIST_CURRENCY_MAP.get(str(symbol).upper(), frozenset()))
    return frozenset(out)


def symbols_for_currencies(currencies: list[str] | tuple[str, ...] | set[str]) -> frozenset[str]:
    ccys = {str(x).upper() for x in currencies}
    return frozenset(sym for sym, mapped in WATCHLIST_CURRENCY_MAP.items() if mapped & ccys)
