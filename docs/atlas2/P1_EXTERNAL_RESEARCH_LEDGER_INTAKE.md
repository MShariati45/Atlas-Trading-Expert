# External Research Ledger Intake Policy

Owner: Ali Shariati
Status: PROVISIONAL — source review required before promotion

External deep-dive findings, model-generated ledgers, and experimental heuristics must enter Atlas through an isolated Research/Lab intake lane first. They are not merged directly into production strategy tiers, gate logic, or execution rules.

Default flow:

1. Archive the source artifact and hash it.
2. Parse each claim/rule into a versioned research record with provenance, scope, assumptions, and source references.
3. Classify each record as evidence, hypothesis, candidate feature, candidate gate, candidate strategy rule, or evaluation methodology.
4. Test in replay/lab with holdout discipline and explicit taint/provenance.
5. Compare against C0 and frozen Owner Track A without changing them.
6. Promote only records that pass explicit review and owner approval into a named, versioned production component.

Until the deep-dive ledger is reviewed, Atlas must not decide whether its items belong in any existing Tier A / Tier B / Tier COD structure. That mapping is a review output, not an ingestion assumption.

External evaluators/models may be used as independent reviewers or labelers in the Lab, but their outputs remain attributed evidence and do not become ground truth or training targets automatically.
