# Atlas v2 — External Research Pack Review and Integration Decision

Owner: Ali Shariati
Reviewer role: Chief advisory / independent technical review
Date: 2026-10-02
Status: ADVISORY REVIEW COMPLETE — NO STRATEGY PROMOTION AUTHORIZED BY THIS DOCUMENT

## Source identity

Reviewed source:
`Atlas_Complete_Research_and_Data_Engineering_Pack_2026-10-02.zip`

Uploaded-pack SHA-256:
`27bb6fb4fcfa03e4bfe320b726872a26c5d4cf2ee6d2a4eb0643f63c0e6417f2`

The pack contains 18 top-level records. Its checksum manifest lists 17 payload files; every listed byte count and SHA-256 was independently rechecked and matched. The nested historical archives were treated as preserved source history, not as newer authority over the later correction/synthesis records.

## Executive decision

The pack is useful and unusually disciplined, but its main value is **research governance, causal data engineering, experiment design, and a bounded challenger queue**. It is not evidence that a new model, indicator, pair, exit rule, AI agent, or portfolio method is profitable for Atlas.

Do **not** merge this pack wholesale into Owner Track A, existing gate roles, or any Tier A / Tier B / Tier COD concept.

The correct integration is:

`External Research -> Research/Lab Intake -> Existing Atlas ResearchRegistry + Holdout -> Replay/Counterfactual Evaluation -> Promotion Review -> Owner-approved versioned component`

The pack should strengthen how Atlas learns, tests and rejects ideas. It should not directly become trading authority.
## What should be adopted now

The following are engineering/governance improvements, not strategy changes:

- Preserve every owner-eligible opportunity, including skipped/rejected candidates, so later take/pass research is not trained only on executed trades.
- Keep event time, source availability time, decision time, revision/vintage identity and taint separate.
- Use chronological train/calibration/test partitions. Random row CV is not the confirmatory default.
- Explicitly handle overlapping outcome horizons, purge/embargo requirements and repeated model/threshold inspection.
- Protect final OOS data with the existing Atlas holdout guard.
- Evaluate management changes in full chronological account replay, not only isolated trade pairs, because exits can change capacity and later opportunity availability.
- Keep observed execution, simulated counterfactual outcome and proxy outcome as distinct evidence classes.
- Model spread, commission, swap, slippage, delay and ambiguous intrabar order explicitly; never assume same-bar favorable ordering.
- Preserve the initial-risk denominator when comparing BE/trailing/partial/time exits.
- Keep external model labels and reviews attributable and non-operational unless explicitly promoted.

These principles fit Atlas v2 directly and should inform the next data/outcome/research slices.

## Claims challenged

### 1. Take/pass / meta-labeling

**Useful idea, not a production filter yet.**

Meta-labeling is a good conceptual fit for asking whether an already owner-authorized opportunity should be taken or passed. The external library semantics, especially triple-barrier labels, are not Atlas semantics. Atlas must define labels from its own entry, stop, target, cost and management contracts.

Recommended internal name: **policy-specific trade-quality selector** rather than treating a third-party meta-label recipe as authority.

Do not alter Owner Track A gate roles. Implement a separate Lab challenger arm and compare it beside C0 and Track A.

### 2. Logistic regression / gradient boosting

**Good baselines, not evidence of edge.**

Logistic regression should be the first transparent baseline. A nonlinear tree/boosting model can follow only if the simple model leaves stable, replicated signal. Calibration must use temporally disjoint data and be evaluated separately from discrimination.

No deep model is justified before these baselines establish incremental economic value.

### 3. Causal trend / persistence features

**Promising but confirmation-time correctness is the main risk.**

Any turning-point, persistence or structure feature must store both the historical extremum time and the later confirmation time. A reducer that emits a historical index after future confirmation cannot be joined back to that index as if the feature was known then.

TTRA is therefore a research reference, not a drop-in Atlas feature source.

### 4. BE, trailing, partial and time exits

**High-value experiments because they are directly tied to the current owner baseline, but they need account replay.**

The pack's BE arithmetic is a useful sanity identity, not empirical evidence. The existing Track A BE@1.4R baseline plus no-BE ablation gives Atlas a clean first management comparison once the outcome resolver is trustworthy.

Trailing, partial close and time exits should be tested one policy at a time before joint selectors.

### 5. Volatility scaling / sizing

**Keep as a bounded hypothesis.**

Sizing can reduce exposure without creating informational edge. The cited literature itself contains strong counterevidence to universal volatility-management benefits. Do not mix entry selection improvements and sizing changes in one experiment.

### 6. RL / learned management

**Defer.**

RL is currently too flexible relative to Atlas evidence volume and owner constraints. It introduces reward-design, action-space, reproducibility and simulator-fidelity risk before simpler questions are answered.

Use action masks and decomposed reward logging as design ideas only. No RL controller should enter the Atlas decision path in current P1.

### 7. RD-Agent / Qlib / external research automation

**Reference later; do not install into the Atlas core now.**

Atlas already has a content-addressed research registry, append-only trial evidence and holdout guards. RD-Agent/Qlib would currently duplicate governance and introduce a second research execution stack with assumptions oriented toward its own data/scenario conventions.

If later used, it should be an isolated experiment worker whose outputs return through Atlas ResearchRegistry, never the system of record.

### 8. Portfolio optimization

Batch 05 is preserved as historical research, but the later individual-account correction is controlling for current priorities. Cross-account allocation, HRP/risk-parity/skfolio/Riskfolio and Kelly-style allocation are later-horizon work.

Within a single account, correlated simultaneous FX exposure may still matter and can be researched as an account-risk filter without promoting a portfolio optimizer.
## Atlas placement matrix

| Research item | Atlas destination | Decision now |
|---|---|---|
| Evidence vocabulary / provenance / availability time | Core research/evidence contracts and export views | ADOPT NOW |
| ATX-00 replay and accounting fidelity | Existing ResearchRegistry; prerequisite experiment | HIGHEST PRIORITY |
| Opportunity retention incl. rejects | Capture/evaluation evidence and research export | ADOPT NOW |
| Take/pass selector | New Lab challenger StrategyVersion, never Track A mutation | TEST AFTER ATX-00 |
| Net-value ranking across pairs in one account | Lab ranking experiment over unchanged eligibility/capacity | TEST AFTER reliable account replay |
| Causal trend/persistence feature | Lab feature experiment with confirmation-time adapter | SECOND WAVE |
| BE/no-BE | Existing Track A versions + counterfactual account replay | FIRST MANAGEMENT TEST |
| Trailing / partial / time exits | Lab management variants with owner-permitted actions | LATER, ONE AT A TIME |
| Session/news/cost abstention | Source-backed gate experiments; production only after exact rules/data | HIGH VALUE, DATA-DEPENDENT |
| Pair/setup specialization | Pre-registered subgroup experiment with temporal replication | LATER |
| Volatility risk reduction | Separate sizing overlay experiment | LATER |
| Learned management / RL | Restricted-action Lab only | DEFER |
| RD-Agent/Qlib | Optional isolated research worker | DEFER |
| Optuna | Bounded trial proposer under Atlas search budget | CONDITIONAL LATER |
| River/drift monitoring | Delayed monitoring, not automatic adaptation | CONDITIONAL LATER |
| Portfolio optimizers / Kelly | Future multi-account research | DEFER |

## How the ATX protocol maps to existing Atlas

The ATX identifiers should be **human-readable aliases in preregistration payloads**, not a second experiment registry or new source of truth.

Use existing Atlas primitives:

- `ResearchRegistry.register_experiment(...)` for ATX preregistration.
- `Trial` for parameter/model/policy variants.
- `TrialEvent` for PLANNED/STARTED/COMPLETED/INSPECTED/SELECTED/REPLICATED history.
- `TrialResult` for primary and replication result packets.
- Existing holdout segments/grants/exposures for final OOS control.
- Existing `Decision` for the research decision; owner promotion remains separate and explicit.
- `StrategyVersion` / `ArmResult` for challenger strategy comparison when the candidate reaches replay evaluation.

The proposed files such as `opportunities.parquet`, `events.parquet`, `account_curve.csv`, and `metrics_by_cell.csv` should be **derived export artifacts**, not a second canonical research database. Atlas SQLite + immutable evidence remains authoritative.

The proposed verdict `VALIDATED_FOR_SCOPE` may be used in a report, but it does not mean production approval and must never bypass Atlas Decision evidence plus explicit owner promotion.
## Critical Atlas gaps before machine-learning experiments

The pack correctly asks for experiments that Atlas cannot yet evaluate honestly end-to-end. The blockers are architectural/data readiness, not lack of model choice.

1. **Outcome/execution fidelity:** production-quality counterfactual outcome resolution and full account replay are not yet complete. ATX-00 must prove chronology, fills, stop/target ordering, cost accounting and capacity effects first.
2. **Fully evaluable owner opportunity set:** as of P1-5, H4_CONTEXT is implemented, but M15_COORDINATION, SESSION_DAY, NEWS_RISK and SPREAD_COST still remain unresolved or NOT_EVALUABLE. A take/pass model trained before owner eligibility is stable risks learning from the wrong opportunity population.
3. **Remaining owner entry semantics:** meaningful/valid swing, retest-hold, rejection-candle qualification, structural-level identification, shorthand exact fills, the 2R-realism test and final per-instrument ATR buffer remain explicit unresolved semantics.
4. **Economic feature snapshots:** the research feature matrix must be reconstructed only from information available at decision time; final labels/outcomes must never leak back into features.
5. **Search accounting:** every inspected model, threshold, feature group and management setting must count toward the research trail so a later holdout result cannot be treated as untouched after adaptive exploration.

Therefore the next Atlas milestone should not be "train an AI model." It should be **make the experiment substrate trustworthy enough that a simple model can fail honestly**.

## Recommended execution order

### Phase R0 — intake freeze
- Preserve this pack's source hash and review.
- Register its research hypotheses as aliases under existing Atlas experiment contracts.
- Freeze the source-derived priority order and supersession notes.
- Do not promote any research claim to trading authority.

### Phase R1 — ATX-00 replay/accounting fidelity
- Build/finish deterministic outcome and account replay semantics.
- Prove observed vs simulated/proxy outcomes are distinguishable.
- Validate cost, stop/target ordering, capacity and chronological opportunity accounting.
- Add golden tests for ambiguous intrabar paths and stop-modification delay.

### Phase R2 — owner baseline research packet
- Run unchanged Owner Track A baseline and no-BE ablation on identical opportunity streams.
- Produce account-level and same-entry diagnostics.
- Do not tune the 1.4R owner baseline on the same data used to judge it.

### Phase R3 — ATX-01 take/pass baseline
- Start with transparent logistic regression.
- Separate model-fit, probability-calibration and threshold-selection periods.
- Compare economic results with unchanged Track A and C0.
- Require improvement after costs, coverage/abstention analysis and temporal replication.
- Only after this baseline is credible may a nonlinear challenger be compared.

### Phase R4 — context and cost challengers
- ATX-02 causal persistence feature.
- ATX-08 session/news/spread contextual abstention.
- Pair/setup specialization only after sufficient replicated sample size.

### Phase R5 — management challengers
- Trailing, partial and time exit one at a time.
- Then a constrained management selector if individual policies show stable incremental value.

### Phase R6 — advanced automation
- Only after the above: Optuna-style bounded search, River-style drift monitoring, optional external research worker.
- RL/deep sequential controllers remain last, not first.

## Promotion rule

A research item may move toward Atlas operational code only when all of the following are true:

- source/provenance is immutable and attributable;
- exact hypothesis and comparison were preregistered;
- causal data availability is proven;
- final holdout exposure is controlled;
- result survives costs and full account chronology;
- benefit is not explained only by one pair, one regime or one tuned subperiod unless specialization itself was preregistered;
- regression/safety tests pass;
- the component has a named, versioned integration boundary;
- explicit Owner approval is recorded.

Anything failing these conditions stays Lab-only or is rejected.
## External model/evaluator use

External AI can help Atlas, but the useful role is **independent research labeler/reviewer**, not hidden authority.

Recommended protocol:

- Blind the evaluator to Atlas final outcomes when asking for ex-ante labels.
- Give it the same causal snapshot that was available at the decision time.
- Store a stable identity such as `engine:<provider>:<model>:<version>`.
- Keep model-generated labels under ENGINE/RESEARCH evidence.
- Compare against owner-authoritative labels and later realized outcomes.
- Measure agreement, disagreement, abstention, calibration and economic value separately.
- Never feed the final evaluation set back into tuning/training.
- Never convert model agreement into Owner truth.
- Promote a derived feature or rule only through the same preregistered Lab path as every other challenger.

This lets Atlas exploit extra model intelligence without contaminating its owner authority or final holdout.

## Independent source spot-check

The review also spot-checked several high-consequence external claims against current primary/official sources:

- mlfinpy documents binary take/pass meta-labeling when side is provided; this supports the concept, not Atlas-specific label semantics.
- MetaQuotes documents that successful `OrderSend` return is not proof that the trade has executed and that trade events can occur later.
- MetaQuotes documents real-tick/generation behavior and fallback generation where minute bars exist without tick data.
- MetaQuotes documents that NewTick events are not queued again while one is queued or processing.
- MetaQuotes documents trade-server-time calendar semantics and the Strategy Tester calendar limitation.
- Current scikit-learn documentation supports the need for careful probability calibration and temporal CV control; defaults are not automatically Atlas-safe.
- The Cederburg et al. JFE paper reports no systematic real-time advantage from volatility management across 103 equity strategies.
- RD-Agent's current quant scenarios are built around Qlib workflows and configurable train/validation/test ranges; this is useful research automation but not a direct Atlas/FX strategy proof.

These checks increase confidence that the pack's cautious interpretations are generally responsible. They do not validate profitability.

## Final advisory conclusion

The research should change **how Atlas researches**, before it changes **how Atlas trades**.

The immediate payoff is to make Atlas an auditable experimental system that can distinguish:
- an interesting idea,
- a causal implementation,
- a statistically convincing result,
- an economically useful account result,
- and an owner-approved production rule.

That separation is more valuable now than adding another model.

No item in this pack is approved by this review as a live/Demo trading rule, owner-rule replacement, automatic training target, or standalone Tier.
