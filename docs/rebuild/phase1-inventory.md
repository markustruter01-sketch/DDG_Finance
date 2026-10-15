# Phase 1 demolition inventory — first cut (15 Oct 2026)

Method: static import graph from the live entry points (kraken-bot/runner.py, trading-platform/main.py, main.py) plus the four strategy modules the runner loads by name (asia_trend_strategy, bot3_hard_assets_strategy, bot2_momentum_strategy, forex_ai_strategy), then a name-reference search for every unimported file. Tests excluded.

Nothing here is deleted yet. Deletion happens in one reviewed change after the Phase 0 restore test passes.

## DEAD — not imported and not referenced anywhere

- kraken-bot/bot7_market_context.py
- kraken-bot/check_bot2_book_parity.py
- kraken-bot/correlation_tracker.py
- kraken-bot/dual_momentum_backtest.py
- kraken-bot/forex_baseline_backtest.py
- kraken-bot/forex_council_dryrun.py
- kraken-bot/forex_csm_backtest.py
- kraken-bot/forex_v2_backtest.py
- kraken-bot/hurst_filter.py
- kraken-bot/jerome_v2_backtest.py
- kraken-bot/per_pair_params.py
- kraken-bot/scalp_exits.py
- kraken-bot/scalp_strategies.py
- market_universe.py
- trading-platform/analysis/bot2_commodity_research.py
- trading-platform/analysis/bot2_earnings_validation.py
- trading-platform/analysis/bot3_hard_assets_backtest.py
- trading-platform/analysis/bot3_rebalanced_backtest.py
- trading-platform/analysis/fleet_test.py
- trading-platform/analysis/global_universe_audit.py
- trading-platform/analysis/health_monitor.py
- trading-platform/analysis/load_research_daily_prices.py
- trading-platform/data/ingest_historical.py
- trading-platform/execution/short_scanner.py
- trading-platform/execution/stop_backfill.py
- trading-platform/scripts/export_strategy_bench_snapshot.py

## REVIEW — not imported, but named somewhere (often only by other dead files or docs)

- kraken-bot/adaptive_params.py | ./kraken-bot/CRO_AUDIT_REPORT.md ./trading-platform/analysis/fleet_enforcer.py ./trading-platform/analysis/learning_snapshot.py 
- kraken-bot/bot2_spy_qqq.py | ./replit.md ./kraken-bot/asia_trend_strategy.py ./kraken-bot/spy_qqq_oos_validation.py 
- kraken-bot/fetch_data.py | ./trading-platform/routes/system.py 
- kraken-bot/flow_sentiment.py | ./kraken-bot/config.py 
- kraken-bot/logic.py | ./shared/circuit_breaker.py ./shared/risk_profile.py ./shared/var_circuit_breaker.py 
- kraken-bot/microstructure.py | ./kraken-bot/CRO_AUDIT_REPORT.md ./trading-platform/analysis/global_universe.py ./trading-platform/core/degradation_tracker.py 
- kraken-bot/migrate_global_etf.py | ./kraken-bot/config.py 
- kraken-bot/oos_validation.py | ./kraken-bot/dual_momentum_backtest.py ./trading-platform/db/postgres.py ./.agents/memory/oos-cash-tracking.md 
- kraken-bot/oracle_oos_validation.py | ./.agents/memory/oos-cash-tracking.md ./.agents/memory/oracle-oos-results.md 
- kraken-bot/spy_qqq_oos_validation.py | ./.agents/memory/spy-qqq-oos-results.md 
- kraken-bot/swing_exits.py | ./kraken-bot/scalp_exits.py 
- kraken-bot/swing_strategies.py | ./kraken-bot/scalp_strategies.py 
- kraken-bot/ws_feed.py | ./kraken-bot/CRO_AUDIT_REPORT.md 
- shared/circuit_breaker.py | ./shared/__init__.py ./kraken-bot/logic.py ./kraken-bot/db.py 
- shared/exit_bracket.py | ./shared/__init__.py ./trading-platform/execution/executor.py 
- shared/market_snapshot_validator.py | ./shared/__init__.py ./trading-platform/analysis/analyzer.py ./Technical_Logic_Blueprint.md 
- shared/risk_profile.py | ./shared/__init__.py ./shared/exit_bracket.py ./trading-platform/routes/admin.py 
- shared/var_circuit_breaker.py | ./shared/__init__.py ./trading-platform/core/pipeline.py ./trading-platform/execution/executor.py 
- trading-platform/analysis/bench_gate.py | ./trading-platform/data/strategy_bench_snapshot.json ./artifacts/mockup-sandbox/src/components/mockups/strategy-bench-layouts/_shared/BenchCatalogFixture.ts ./artifacts/mockup-sandbox/src/components/mockups/strategy-bench-redesign/ResearchRecord.tsx 
- trading-platform/analysis/bot1_baseline.py | ./trading-platform/analysis/fleet_test.py 
- trading-platform/analysis/bot2_trend_candidates.py | ./trading-platform/analysis/fleet_test.py 
- trading-platform/analysis/bot3_baseline.py | ./trading-platform/analysis/fleet_test.py 
- trading-platform/analysis/export_bot2_strategy_bench.py | ./trading-platform/analysis/bench_gate.py 
- trading-platform/analysis/global_universe.py | ./trading-platform/analysis/global_universe_audit.py 
- trading-platform/analysis/oracle_oos_validation.py | ./kraken-bot/oracle_oos_validation.py ./.agents/memory/oos-cash-tracking.md ./.agents/memory/oracle-oos-results.md 
- trading-platform/analysis/regime_bias_manager.py | ./kraken-bot/CRO_AUDIT_REPORT.md 
- trading-platform/analysis/strategy_bench_sweep.py | ./trading-platform/data/strategy_bench_snapshot.json 
- trading-platform/core/bot_drawdown_guard.py | ./.agents/memory/arc3-fail-closed.md 
- trading-platform/core/pnl_math.py | ./kraken-bot/paper_engine.py ./forex-engine/paper_engine.py 
- trading-platform/routes/forex.py | ./replit.md ./kraken-bot/paper_engine.py ./kraken-bot/forex_council.py 

## BULK (non-code)

- Root zips: qt-code.zip, qt-code-0907.zip, qt-code-0908.zip (~14 MB each), plus two tiny zips
- kraken-bot/gates/ (~15 MB), screenshots/ (~6 MB), artifacts/mockup-sandbox/ (~7.4 MB)
- Root reports: report-p1..p4.txt, trading-report-2026-04-05_latest.txt, sedwfJKhP

## RESEARCH TO KEEP (moves to research/, not deleted)

- kraken-bot/forex_baseline_backtest.py — produced the registered FX-BT1 result; the new harness must reproduce it
