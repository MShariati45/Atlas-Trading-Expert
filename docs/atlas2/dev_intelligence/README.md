# Atlas Development Intelligence

Atlas has its own development-intelligence layer. It is intentionally isolated from Sigma WorkOffice and Alpha Lead Engine.

- Graphify output: repository-local `graphify-out/`; never added to the global graph.
- Graphify refresh: deterministic code-only update, max two workers, no LLM/API spend.
- Obsidian vault: `/Users/alishaariati/Projects/Atlas Project/02_Knowledge_Vault/Atlas Trading`.
- CodeRabbit: repository-specific config; current account billing usage remains inactive.
- Dependabot: weekly pip + GitHub Actions checks only.
- GitHub remains the durable code/change history. Generated knowledge artifacts are not authority for trading behavior; frozen architecture/contracts and immutable evidence are.

After each closed implementation stage, refresh the graph after the stage is merged to `atlas2-p0`, then update the Obsidian implementation checkpoint note. This keeps lookup fast without making background indexing part of the trading runtime.
