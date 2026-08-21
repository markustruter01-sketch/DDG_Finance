CREATE OR REPLACE VIEW public.bot_trades AS
" SELECT 'oracle'::text AS bot_id,
    'trades'::text AS source_table,
    trades.trade_id AS source_id,
    trades.ticker AS symbol,
    NULL::text AS direction,
    NULL::double precision AS entry_price,
    trades.actual_fill_price AS exit_price,
    NULL::double precision AS units,
    trades.realized_pnl AS pnl_usd,
    trades.pnl_percentage AS pnl_pct,
    trades.exit_reason AS reason,
    trades.regime_at_entry AS regime,
    NULL::double precision AS holding_hours,
    COALESCE(trades.closed_at, trades.date::timestamp with time zone) AS closed_at,
    trades.status AS raw_status,
    trades.asset_class
   FROM trades
  WHERE (trades.status = ANY (ARRAY['Closed_Win'::text, 'Closed_Loss'::text])) AND trades.realized_pnl IS NOT NULL
UNION ALL
 SELECT
        CASE kraken_trades.bot_id
            WHEN 'davy-jones'::text THEN 'spy_qqq_trend'::text
            WHEN 'blackbeard'::text THEN 'jerome_macro'::text
            ELSE kraken_trades.bot_id
        END AS bot_id,
    'kraken_trades'::text AS source_table,
    kraken_trades.id::text AS source_id,
    kraken_trades.symbol,
    kraken_trades.side AS direction,
    kraken_trades.entry_price,
    kraken_trades.exit_price,
    NULL::double precision AS units,
    kraken_trades.pnl_usd,
    kraken_trades.pnl_pct,
    kraken_trades.reason,
    kraken_trades.regime_at_entry AS regime,
    NULL::double precision AS holding_hours,
    kraken_trades.closed_at,
    'closed'::text AS raw_status,
    'crypto'::text AS asset_class
   FROM kraken_trades
  WHERE kraken_trades.closed_at IS NOT NULL AND kraken_trades.pnl_usd IS NOT NULL AND (kraken_trades.bot_id <> ALL (ARRAY['apex-predator'::text, 'bot7_macro_bond'::text, 'calypso'::text, 'bot4_sector'::text]))
UNION ALL
 SELECT 'kraken_trend'::text AS bot_id,
    'kraken_current_trades'::text AS source_table,
    kraken_current_trades.id::text AS source_id,
    kraken_current_trades.symbol,
    kraken_current_trades.direction,
    kraken_current_trades.entry_price,
    kraken_current_trades.exit_price,
    kraken_current_trades.units,
    kraken_current_trades.pnl AS pnl_usd,
    NULL::double precision AS pnl_pct,
    kraken_current_trades.reason,
    NULL::text AS regime,
    kraken_current_trades.holding_days * 24::double precision AS holding_hours,
    kraken_current_trades.closed_at,
    'closed'::text AS raw_status,
    'crypto'::text AS asset_class
   FROM kraken_current_trades
  WHERE kraken_current_trades.closed_at IS NOT NULL AND kraken_current_trades.pnl IS NOT NULL
UNION ALL
 SELECT 'poseidon_momentum'::text AS bot_id,
    'poseidon_momentum_trades'::text AS source_table,
    poseidon_momentum_trades.id::text AS source_id,
    poseidon_momentum_trades.symbol,
    poseidon_momentum_trades.direction,
    poseidon_momentum_trades.entry_price,
    poseidon_momentum_trades.exit_price,
    poseidon_momentum_trades.units,
    poseidon_momentum_trades.net_pnl AS pnl_usd,
    NULL::double precision AS pnl_pct,
    poseidon_momentum_trades.reason,
    NULL::text AS regime,
    poseidon_momentum_trades.holding_hours,
    poseidon_momentum_trades.closed_at,
    'closed'::text AS raw_status,
    'crypto'::text AS asset_class
   FROM poseidon_momentum_trades
  WHERE poseidon_momentum_trades.closed_at IS NOT NULL AND poseidon_momentum_trades.net_pnl IS NOT NULL
UNION ALL
 SELECT
        CASE forex_trades.bot_id
            WHEN 'navigator'::text THEN 'forex_gump'::text
            ELSE forex_trades.bot_id
        END AS bot_id,
    'forex_trades'::text AS source_table,
    forex_trades.id::text AS source_id,
    forex_trades.pair AS symbol,
    forex_trades.direction,
    forex_trades.entry_price,
    forex_trades.exit_price,
    forex_trades.units,
    forex_trades.pnl_usd,
    NULL::double precision AS pnl_pct,
    NULL::text AS reason,
    NULL::text AS regime,
    EXTRACT(epoch FROM forex_trades.exit_time - forex_trades.entry_time) / 3600.0 AS holding_hours,
    forex_trades.exit_time AS closed_at,
    forex_trades.status AS raw_status,
    'forex'::text AS asset_class
   FROM forex_trades
  WHERE forex_trades.status = 'closed'::text AND forex_trades.exit_time IS NOT NULL AND forex_trades.pnl_usd IS NOT NULL;"
