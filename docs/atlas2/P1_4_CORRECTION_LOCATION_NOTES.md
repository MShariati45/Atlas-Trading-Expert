# Atlas v2 P1-4 — Correction Location Notes

Owner: Ali Shariati
Status: CLOSED — implementation, independent review, and dual-runtime validation complete

The implementation adds a pure correction-location measurement policy plus P1 Track A integration. It uses pinned, sealed H4 label evidence under the frozen label-view semantics and never blocks ACCEPT because CORRECTION_LOCATION remains informational by the frozen architecture.

For OPERATIONAL pins, operational availability and data cutoffs must both be no later than the decision time. RESEARCH pins preserve their research view, taint, and provenance rather than being treated as operational truth.

No-label, late-operational-label, ambiguous-label, abstention, unsealed-group, and missing-depth cases fail closed or remain explicitly unmeasured rather than being guessed.

Independent review found two issues: missing operational-availability enforcement and silent dropping of unsealed pinned groups. Both were fixed. Independent re-review: **PASS**.

Validation: focused P1-4/evaluation/architecture tests **44/44 PASS** on Python 3.14 and Python 3.12; full Atlas v2 suite **202/202 PASS + 236 subtests** on both runtimes; compileall and git diff checks PASS.
