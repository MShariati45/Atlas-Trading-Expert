# ADR-002 — Time, Availability, Views, Taint

Owner: Ali Shariati
Status: Accepted

All instants are UTC microseconds.
Operational decisions may read only inputs whose operational availability is at or before decision time.
Retrospective labels and non-PIT macro history remain research-only and propagate taint.
Derived HTF availability is never earlier than the latest constituent it uses.
Market, label, and outcome/future views remain separate capabilities.
