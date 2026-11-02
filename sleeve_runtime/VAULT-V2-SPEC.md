# VAULT-V2 — the profit vault (Fable 5.1, 2 Nov 2026; owner's instruction)

Markus (2 Nov 2026): a long-running platform that takes a share of every
profit into a vault that sits in safe, yield-bearing cash forever and is never
traded. Fable chose the rate and the asset; Markus accepted ("do whatever
percentage you recommend").

Today's vault (`trading-platform/execution/per_bot_vault.py`): 20% of every
profitable close, split 50/50 BIL/VOO, deployed every 15 minutes, rebalanced
quarterly, excluded from every strategy's capital and from the kill switch's
stop checks, activated per account with a confirmation token. Keep the
plumbing; change the rule, the asset and the reporting.

## 1. Skim rule (replaces "20% of each winning close")
- **Trading equity** of an account = broker equity − vault holdings' value.
- On the first session of each month, after the previous month's close: if
  trading equity > its **high-water mark**, skim **10%** of (trading equity −
  high-water mark) into the vault; then set the high-water mark = trading
  equity − skim. Otherwise nothing moves and the mark is unchanged.
- The mark starts at trading equity on the day the vault is activated for
  that account (or at cutover for the three FLEET accounts, 3 Nov 2026).
- The skim is a tagged cash amount inside the same Alpaca account (as now);
  the deployment job buys BIL with it on the next market-hours cycle.
- One rule for all three accounts, whatever they trade (stocks, ETFs, options
  premium): profit is measured on equity, not per trade. The per-trade hook
  (`record_profitable_close`) is retired; the contributions table gains a
  monthly row per account instead.
- Why 10%: trading capital is expected to compound at roughly 10–15% a year,
  the vault at the T-bill rate (~4% today); each dollar skimmed trades
  expected growth for certainty. 10% costs the bots about 1–1.5 points a
  year of compounding and builds a second income that matters within a few
  years; 20% starves the engine; 5% does not matter for a decade.
- Why net new highs: skimming winners without netting losers moves money
  out of an account that may be losing overall, and penalises strategies
  that trade often (F1 closes hundreds of small trades a year). Net new
  highs are the only honest definition of profit.

## 2. Holdings
- **100% BIL** (SPDR 1-3 Month T-Bill ETF). No VOO, no bonds beyond three
  months, nothing foreign, nothing with credit risk. Principal does not
  move; the yield follows the Fed and is reported, not promised.
- BIL rather than SGOV so that vault holdings have their own ticker,
  distinct from the bots' parked cash (SGOV), and stay auditable by symbol.
- Transition: the next deployment cycle sells the vault's VOO and buys BIL;
  the quarterly 50/50 rebalance job is retired (nothing to rebalance).
- The vault is never sold except by an explicit owner action with the
  confirmation token, recorded in the ledger.

## 3. Reporting
- Each account's performance (dashboard, comparison table, 2027 verdict) is
  measured on **total equity including its vault**, so skimming never makes
  a strategy look worse than it is. The vault's value is also shown on its
  own.
- Dashboard vault card (Home, under the three accounts): balance per
  account and total, BIL yield (30-day SEC yield as published), income this
  month and lifetime, contributions this year and lifetime, the next skim
  date, and each account's high-water mark and distance from it.
- Every skim writes one ledger row: account, date, trading equity, mark
  before and after, amount.

## 4. Safety, unchanged
- Vault holdings are excluded from sleeve capital, protective-stop checks
  and the drawdown governors (which use broker equity; a skim moves money
  within the account, so equity is unchanged by it).
- Activation per account with the existing confirmation token
  (`ACTIVATE_PER_BOT_VAULT`); `PER_BOT_VAULT_ENABLED=true` stays the master
  switch. Paper accounts from cutover; real money follows the same rule.

## 5. Build (Opus, with the dashboard pass)
- `per_bot_vault.py`: monthly high-water skim job (scheduler, first session
  of the month after the close), retire the per-trade hook and the
  quarterly rebalance, BIL-only deployment, VOO liquidation once.
- `routes/vault.py` (or extend `fleet_v1.py`): the figures in section 3.
- Dashboard: the vault card; account returns computed on total equity.
- Tests: the skim fires only above the mark, 10% of the excess, mark reset
  to post-skim equity; no skim in a down or recovering month; BIL only;
  vault excluded from strategy capital (existing tests still pass).
- Fable: review before merge, as for every change that moves money.
