# Atlas v2 P1-4 — Correction Location Notes

Owner: Ali Shariati
Status: CLOSED — implementation, independent review, and dual-runtime validation complete

The implementation adds a pure correction-location measurement policy plus P1 Track A integration. It uses pinned, sealed H4 label evidence under the frozen label-view semantics and never blocks ACCEPT because CORRECTION_LOCATION remains informational by the frozen architecture.

For every pin view, task cutoff, group cutoff, and label submission time must be no later than the decision time. OPERATIONAL pins additionally require an OPERATIONAL label with operational availability no later than decision time. RESEARCH pins preserve their research view, taint, and provenance rather than being treated as operational truth.

No-label, late-label, ambiguous-label, abstention, unsealed-group, and missing-depth cases fail closed or remain explicitly unmeasured rather than being guessed. Pinned H4 groups are not silently removed before evaluation; non-causal and unsealed pinned sources remain visible in semantic/replay evidence and prevent a false-singleton measurement.

Independent review found two causality/selection blockers: RESEARCH pins could admit labels submitted after decision time, and pre-filtering pinned groups could collapse an ambiguous pin into a false singleton. Both were fixed. The informational unsealed-group path was also changed to remain unmeasured without aborting the whole evaluation. Independent re-review: **PASS**.

Validation: focused P1-4/evaluation/strategy/architecture tests **53/53 PASS** on Python 3.14 and Python 3.12; full Atlas v2 suite **205/205 PASS + 236 subtests** on both runtimes; compileall and git diff checks PASS.
