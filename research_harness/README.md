# Research harness (research_harness/)

One engine for every strategy test, so results are comparable and honest.

| Piece | File | Rule it enforces |
|---|---|---|
| Held-out lock | `harness/holdout.py` | Data from 1 Jan 2021 on is read only by a registered test |
| Data store | `harness/store.py` | Immutable datasets, SHA-256 per file, re-checked on every load |
| Registry + ledger | `harness/registry.py`, `registrations/`, `ledger.jsonl` | Register before testing; one held-out test per registration; edits after a run are refused |
| Costs | `harness/costs.py` | No defaults; anything omitted labels the result OPTIMISTIC |
| Simulator | `harness/portfolio.py` | Decide at close, trade next open; T-bill on cash, financing on borrowing, borrow on shorts |
| Metrics | `harness/metrics.py` | Full picture every time (return, Sharpe, drawdown, trades, win rate, turnover, leverage) |
| Fleet | `harness/fleet.py` | Sleeve: beats T-bills, raises fleet Sharpe, correlation < 0.5. Fleet: beats SPY on Sharpe AND drawdown |

Data lives in `.local/research_data` (not in git). Pull it with `python -m research_harness.fetch ...` (see the file header).

First job: `python -m research_harness.replications.fx_bt1 --dataset <fx dataset>` must reproduce the registered FX-BT1 result before any new strategy is trusted to the harness.
