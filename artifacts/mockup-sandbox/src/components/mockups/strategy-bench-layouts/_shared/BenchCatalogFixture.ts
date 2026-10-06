export const MOCK_CATALOG = {
  schema_version: 1,
  generated_at: "2026-10-05T00:45:45.754501Z",
  snapshot_as_of: "2026-10-05T00:45:45.754501Z",
  source_label: "Helium research database · read-only export",
  source: "helium_research_database_snapshot",
  source_detail: "Static sample records for layout review; not live data.",
  row_counts: { experiments: 2, exploration_runs: 3 },
  experiments: [
    {
      id: 17,
      family: "bot2_momentum_fullmarket",
      hypothesis:
        "12-1 cross-sectional momentum, top 20 equal weight, monthly rebalance, on a full-market mechanically screened US equity universe produces positive risk-adjusted returns.",
      parameters_summary:
        "allocation=equal_weight; cash_model=one shared cash balance; max_deployment=1.0; momentum=12-1; rebalance=monthly first-trading-day; top_n=20; universe_size=500",
      pass_bar: { pooled_sharpe_min: 0.6, pooled_max_drawdown_max: 0.4 },
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31", warmup_start: "2018-01-01" },
      metrics: { sharpe: 1.799, return_pct: 96.23, max_drawdown_pct: 18.3 },
      outcome: "PASS",
      created_at: "2026-08-29T01:59:27.614437Z",
    },
    {
      id: 19,
      family: "bot2_momentum_rank500_regime",
      hypothesis:
        "Adding a market regime filter to rank-500 12-1 momentum reduces the momentum-crash drawdown without destroying the return.",
      parameters_summary:
        "allocation=equal_weight; idle_capital=cash; market_regime=SPY prior 200-session SMA; top_n=20; universe_size=500",
      pass_bar: { sharpe_min: 0.6, max_drawdown_max: 0.4 },
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31", warmup_start: "2018-01-01" },
      metrics: { sharpe: 0.887, return_pct: 209.2, max_drawdown_pct: 33.79 },
      outcome: "FAIL",
      created_at: "2026-08-29T03:45:41.438825Z",
    },
  ],
  exploration_runs: [
    {
      id: 1,
      family: "bot2_momentum_rank500",
      parameters_summary: "allocation=equal_weight; momentum=12-1; top_n=20; universe_size=500",
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31" },
      sharpe: 0.702,
      return_pct: 3.218,
      max_drawdown: 72.016,
      source: "bench_gate",
      created_at: "2026-08-30T23:43:10.581668Z",
    },
    {
      id: 2,
      family: "bot2_momentum_rank500_regime",
      parameters_summary: "allocation=equal_weight; market_regime=SPY prior 200-session SMA; top_n=20",
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31" },
      sharpe: 0.381,
      return_pct: 0.707,
      max_drawdown: 75.104,
      source: "bench_gate",
      created_at: "2026-08-30T23:44:43.929863Z",
    },
    {
      id: 3,
      family: "bot2_momentum_rank500",
      parameters_summary:
        "allocation=equal_weight; catastrophe_stop=0.2; idle_capital=cash; max_deployment=1.0; momentum=12-1; random_control_iterations=1000; random_control_seed=2712026; rebalance=monthly first-trading-day; screening=4 fields; slippage_each_leg_bps=10.0; top_n=20; universe_rule=top 500 by trailing 60-session median dollar volume; universe_size=500",
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31", warmup_start: "2018-01-01" },
      sharpe: 0.7016876886753177,
      return_pct: 3.218342604572803,
      max_drawdown: 72.01566486898376,
      source: "bench_gate",
      created_at: "2026-08-31T00:03:17.861893Z",
    },
  ],
};
