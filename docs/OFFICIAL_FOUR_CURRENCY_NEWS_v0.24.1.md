# Atlas v0.24.1 - Official four-currency scheduled-news backbone

This checkpoint adds a zero-AI scheduled-news backbone for USD, EUR, CAD and JPY using primary sources only.

- USD: U.S. BLS official release-calendar ICS plus Federal Reserve FOMC policy dates.
- EUR: ECB Governing Council monetary-policy decision dates.
- CAD: Bank of Canada fixed policy announcement dates plus Statistics Canada's rolling CPI/Labour Force schedule.
- JPY: Bank of Japan Monetary Policy Meeting dates plus Statistics Bureau of Japan CPI and Labour Force schedules.

The bundle is fail-closed: if a required primary source cannot be reached or does not match expected schedule markers, refresh exits non-zero and paper supervision must remain unavailable.

Important: this is a scheduled-news backbone, not a breaking-news wire. BoJ policy decisions use a broad event-specific blackout because the exact announcement time is not fixed. MT5 execution remains hard locked.
