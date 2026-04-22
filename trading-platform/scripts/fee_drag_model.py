"""
fee_drag_model.py — Models real fee drag across all 8 bots before live capital decisions.

Reads actual trade history from the DB and calculates:
  - Total fees paid to date (paper)
  - Fee drag as % of starting capital per bot
  - Break-even win rate required to overcome fees at current trade frequency
  - Projected annual fee drag if volumes scale to live trading
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.postgres import get_conn, is_pg_available

def run():
    if not is_pg_available():
        print("DB unavailable")
        return

    print("=" * 70)
    print("QUANT TERMINAL — FEE DRAG MODEL")
    print("=" * 70)

    with get_conn() as conn:
        with conn.cursor() as cur:

            # ── ORACLE (Alpaca) ───────────────────────────────────────────────
            print("\n── ORACLE (#1 — Alpaca NYSE) ──")
            cur.execute("""
                SELECT 
                    COUNT(*) as trades,
                    AVG(ABS(pnl_percentage)) as avg_move_pct,
                    COUNT(*) FILTER (WHERE status = 'Closed_Win') as wins
                FROM trades
                WHERE status IN ('Closed_Win', 'Closed_Loss')
            """)
            row = cur.fetchone()
            if row and row[0]:
                trades, avg_move, wins = row
                # Alpaca paper trading: no real fees in paper mode
                # Live: $0 commission but 0.003% SEC fee on sells + spread ~0.05%
                live_fee_per_trade = 0.0005  # ~0.05% round trip spread + SEC
                total_fee_drag = trades * live_fee_per_trade * 100000
                breakeven_wr = live_fee_per_trade / (avg_move / 100) if avg_move else 0
                print(f"  Trades: {trades} | Wins: {wins} | Win rate: {wins/trades*100:.1f}%")
                print(f"  Avg move per trade: {avg_move:.3f}%")
                print(f"  Est. live fee per trade: {live_fee_per_trade*100:.3f}%")
                print(f"  Projected fee drag on {trades} trades: ${total_fee_drag:,.2f}")
                print(f"  Fee breakeven win rate adjustment: +{breakeven_wr*100:.1f}%")

            # ── KRAKEN BOTS ───────────────────────────────────────────────────
            print("\n── KRAKEN BOTS (#2 Davy Jones / #3 Blackbeard / #4 Calypso / #5 Apex) ──")
            cur.execute("""
                SELECT 
                    bot_id,
                    COUNT(*) as trades,
                    COALESCE(SUM(fees_usd), 0) as total_fees,
                    COALESCE(SUM(pnl_usd), 0) as total_pnl,
                    AVG(ABS(pnl_pct)) as avg_move_pct,
                    COUNT(*) FILTER (WHERE pnl_usd > 0) as wins
                FROM kraken_trades
                WHERE closed_at > NOW() - INTERVAL '30 days'
                GROUP BY bot_id
                ORDER BY bot_id
            """)
            rows = cur.fetchall()
            total_kraken_fees = 0
            for r in rows:
                bot_id, trades, fees, pnl, avg_move, wins = r
                total_kraken_fees += fees
                wr = wins/trades*100 if trades else 0
                fee_pct_capital = fees / 100000 * 100
                daily_trades = trades / 30
                annual_fees = fees * (365/30)
                print(f"\n  {bot_id}:")
                print(f"    Trades (30d): {trades} | Win rate: {wr:.1f}%")
                print(f"    Fees paid (30d): ${fees:,.2f} ({fee_pct_capital:.3f}% of $100k capital)")
                print(f"    Net P&L after fees: ${pnl:,.2f}")
                print(f"    Daily trade frequency: {daily_trades:.1f} trades/day")
                print(f"    Projected annual fees at this rate: ${annual_fees:,.2f}")
                if avg_move and avg_move > 0:
                    fee_per_trade = fees/trades if trades else 0
                    avg_move_usd = avg_move/100 * 100000 * 0.10  # ~10% position
                    breakeven_extra = fee_per_trade / avg_move_usd if avg_move_usd else 0
                    print(f"    Fee per trade: ${fee_per_trade:.2f}")
            print(f"\n  Total Kraken fees (30d): ${total_kraken_fees:,.2f}")

            # ── NAVIGATOR (Forex) ─────────────────────────────────────────────
            print("\n── NAVIGATOR (#6 — Forex) ──")
            cur.execute("""
                SELECT 
                    COUNT(*) as trades,
                    COUNT(*) FILTER (WHERE pnl_usd > 0) as wins,
                    COALESCE(SUM(ABS(pnl_usd)), 0) as gross_volume,
                    COALESCE(AVG(pnl_pips), 0) as avg_pips
                FROM forex_trades
                WHERE status = 'closed'
            """)
            row = cur.fetchone()
            if row and row[0]:
                trades, wins, volume, avg_pips = row
                spread_cost_pct = 0.001  # 0.1% per side = 0.2% round trip
                est_total_fees = trades * 100000 * 0.01 * spread_cost_pct * 2
                wr = wins/trades*100 if trades else 0
                print(f"  Trades: {trades} | Win rate: {wr:.1f}%")
                print(f"  Avg P&L in pips: {avg_pips:.1f}")
                print(f"  Est. spread cost per trade: {spread_cost_pct*2*100:.2f}%")
                print(f"  Projected total spread drag: ${est_total_fees:,.2f}")
                print(f"  Note: Navigator uses simulated spread at 0.1% per side")

            # ── SUMMARY ───────────────────────────────────────────────────────
            print("\n" + "=" * 70)
            print("LIVE TRADING FEE REALITY CHECK")
            print("=" * 70)
            print("""
  Before deploying real capital, key fee considerations per bot:

  ORACLE (Alpaca):
    Paper mode has zero fees. Live mode has:
    - No commission (Alpaca is commission-free)
    - SEC/FINRA sell fee: ~$0.000145 per $1 sold (~negligible)
    - Primary cost: BID/ASK spread on entry AND exit
    - Typical spread: 0.01-0.05% per side on liquid NYSE stocks
    - Round-trip cost on $10k position: ~$10-50
    - At 261 trades with avg $6,650 position: ~$1,700-8,600 total drag
    - Oracle's -$494 net P&L would be -$2,200 to -$9,100 in live trading

  KRAKEN BOTS (Davy Jones, Blackbeard, Calypso, Apex):
    Fees are REAL and already paid in paper mode (Kraken charges fees
    even on paper accounts if using real API calls — CHECK THIS).
    Kraken taker fee: 0.26% per side = 0.52% round trip.
    At $10k position: $52 round trip cost.
    A strategy needs >0.52% average profit per trade to break even.
    Check avg_move_pct above vs 0.52% fee threshold per bot.

  NAVIGATOR (Forex):
    Forex brokers charge via spread, not commission.
    Simulated at 0.1% per side = 0.2% round trip.
    Real retail forex spreads: 0.5-2 pips on majors.
    EUR/USD 1 pip = 0.01% on $100k position = $10.
    At 11 trades: ~$220 real spread cost vs simulated $22.
    Navigator's spread simulation may be 5-10x cheaper than reality.
""")

if __name__ == "__main__":
    run()
