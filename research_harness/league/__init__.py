"""Shadow League (roadmap Phase 1): fake-money strategies on real prices, no orders.

Every strategy here is PURE: it reads bars up to a day and returns target
weights. No broker, no clock, no network, no database. The nightly job
(trading-platform/twins/league.py) asks each strategy what it would hold and
appends that to the twins' decision log; the twins engine then values every
shadow at the close exactly as it values the mirror twins.

Registrations: research_harness/registrations/LEAGUE-V1.json (one entry per
strategy; its hash is stored on each shadow account when it starts).
"""
