# Optional Jev household energy action ranking

Jev can provide a bounded semantic suitability judgment for actions already selected by the energy planner. The planner continues to own action creation, applicability guards, exclusions, descriptions, source references, savings figures, and totals. A complete, high-confidence batch may reorder at most 12 existing actions. `unknown` on any action always discards the full batch; `neutral` is a known tie and keeps baseline order. Every accepted active batch, including an unchanged order, carries applied metadata for the today card.

## Configuration

`JEV_ENERGY_RANKING_MODE` is independent of `JEV_ROUTING_MODE`:

- `off` (default): no network call.
- `shadow`: make one batch request and log proposed action IDs and the allowed `fit` / `neutral` / `poor` / `unknown` judgments; never change plan order or action data.
- `active`: apply a fully validated result, persist sanitized per-action ranking metadata, and preserve the resulting order in the today card.

Provider, credential, and model use `JEV_PROVIDER`, the corresponding `TYPESAFE_API_KEY` or `OPENROUTER_API_KEY`, and `JEV_MODEL`, following the routing integration. Endpoints are fixed. TLS verification stays enabled; proxies, redirects, and retries are disabled. `LLM_MOCK=true` disables calls. Only allowlisted device/preference facts and bounded candidate descriptions are sent. User IDs, city/address, bills, and conversation/profile history are excluded.

Money-priority plans skip Jev ranking (`money_order_preserved`) to preserve their existing saving amount ordering. Low confidence on any action, unknown evidence, invalid/missing/extra answers, invalid distributions, network/HTTP errors, or oversized output discard the whole ranking batch. Existing deterministic order breaks equal suitability scores. Today cards honor model order only when every action has valid applied metadata (`fit`/`neutral`/`poor`, confidence 0.8–1, finite score 0–1); otherwise deterministic difficulty/savings ordering applies.

## Limits and risks

The labels are semantic preferences, not evidence that savings are real or that an action is safe. They must never be treated as facts. Household information may be incomplete; the ranker treats missing facts as unknown and does not infer elderly residents, babies, or daytime occupancy from family size. Network availability and model judgment quality can still affect active ordering, so evaluate representative household cases in shadow mode before enabling active mode. Ranking never creates an action or changes its numeric or source fields.

## Rollback

Set `JEV_ENERGY_RANKING_MODE=off` (or unset it). This stops all ranking calls and restores the existing today-card ordering behavior for newly generated plans.

## Verification

Focused ranking tests: `pytest tests/test_jev_energy_ranking.py -q`. Baseline captured before this change: 79 passed, 8 failed in `test_energy_personalization.py` and `test_energy_weekly.py`; these pre-existing failures remain out of scope and are not suppressed.
