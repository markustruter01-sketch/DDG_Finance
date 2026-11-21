# The next ten years against the last five hundred
## Research file for DDG Finance. Context, not a trading rule.

Written by Claude (Fable 5.2), Sat 21 Nov 2026, about 12:25 Brisbane, at Markus's request (11:36, 12:00 and 12:05 Brisbane).

**Status: CONTEXT.** Nothing here is a rule. No strategy, fund, table, stop or AI prompt reads this file. What the platform does with it is in `fund-roadmap-v2-2026-11-21.md` (section 2.4, orders V2-18 to V2-22). What I expect of the platform is in `fund-thesis-2027.md`.

**How to read it.** Part 1 is one page: the whole picture from 40,000 feet. Each part after it goes one level deeper. Stop where you have enough.

**How it was made.** Web research on 21 Nov 2026: Ray Dalio's published work; the long-run records (returns since 1900, interest rates since 1311, commodity prices since 1850, government debt and default over eight centuries, reserve currencies, wars); this week's market and economic data; and the measured track records of forecasters. Plus a read of the research harness at commit `2447d4a`. Nothing was run. Sources are tagged like [U] and listed in Part 9. "General history" or "general knowledge" marks a statement I did not source today.

**Weighting, as Markus asked (12:05).** Data first. The big asset managers get low weight and a note on what they gain from saying what they say. The same test is applied to the newsletter writers and gold sellers on the other side.

**Not advice.** This is background for building and testing software on paper money. Part 6 is my own opinion, marked as opinion, with odds on it so it can be checked later.

---

# Part 1. Page one: the view from 40,000 feet

**The question.** If we are near the end of a long cycle, are the last 20 years a fair guide to the next 10?

**Seven things the evidence says.**

1. **The pressures are real and can be measured.** US government debt is 101% of the economy and projected at 120% to 133% by 2036. The deficit was $2.0 trillion last year with the economy growing. Armed conflicts are at their highest count since records began in 1946. Central banks hold more gold than US government bonds. US shares are 62% of the world's market and in October were priced at about 40 times their ten-year average profits, a level seen only once before, in 1999–2000.
2. **Today the US is not printing. It is doing the opposite.** Inflation is near 4%, the central bank is raising rates, the 10-year yield is about 5%, and the yield after inflation is the highest since 2008. That is why, this week, shares are in a correction and gold is a third below its peak.
3. **History says the pain of that choice is what usually ends it.** Countries that borrow in their own money and answer to voters have mostly shrunk big debts with years of interest rates held below inflation. Not with default, and not with decades of budget surpluses.
4. **"Printing" has usually meant slow erosion, not collapse.** The dollar has lost about 97% of its buying power since 1900. Over the same years US shares gained 6.6% a year after inflation and the US rose to the top. Collapse happened to countries that lost wars or owed money in someone else's currency.
5. **No asset wins every era.** Shares win most. Hard assets win the inflation eras and then give much of it back. Cash and bonds win when prices fall.
6. **Nobody has timed any of this.** Economists foresaw 5 of 153 recessions. Wall Street's strategists have not forecast one down year this century. Dalio has warned of a crisis every couple of years since 2015. The strongest structural argument of 2026 ("the central bank cannot tighten") was wrong on the path: it tightened.
7. **What survived every era was a method, not an asset:** hold many things that do not move together, follow trends, borrow little, and keep money in more than one place.

**My own reading, in one paragraph (opinion).** The most likely decade is repression, not collapse: inflation averaging above 3% (I put it at 55%), rates held below inflation for stretches, a dollar that stays first but smaller, and US shares returning far less than in the last decade. About one chance in four the decade looks like the 1990s instead, with AI lifting growth. Under one in ten for a real currency collapse. The path almost certainly runs through a tightening scare first, and we are in it now. For 2027 alone I have no edge on direction.

**What it changes for the fund.** No bet changes. Measurement is added: slow gauges, four daily flags, tests of our rules in other eras, and drills for a world that breaks. The history also exposed three gaps in the build, proposed as roadmap decision D14: no inflation-linked bonds in the fund, a "defensive" line that cannot step aside, and no gauge for tight money.

---

# Part 2. The argument in ten minutes

## 2.1 The frame: three clocks and two wild cards

Dalio's "Big Cycle" is a useful map even for people who doubt it as a clock. Three things move together over about 75 years, give or take 30 [D1]:

- **Debt and money.** Borrowing grows faster than income until the interest crowds out everything else. Then money is printed.
- **Order inside countries.** Gaps in wealth and values widen. Politics moves to the edges.
- **Order between countries.** A leading power is challenged. Conflict over trade and money comes before conflict with weapons.

Two wild cards cut across them: acts of nature, and powerful new technology. [D1]

He built this from the Dutch, British and American empires. [D3] He says the world order between countries has already broken down, and the cycle as a whole is one step from breakdown. [D1][D2] He gives no date and no odds. [D1]

## 2.2 Where the gauges stand

| Gauge | Now | For scale |
|---|---|---|
| US debt held by the public | 101% of the economy [CBO] | The record is 106%, in 1946. Projected 120% in 2036; 124% to 133% if rates run 0.5 to 1.5 points higher [CBO2] |
| US deficit | $2.0 trillion in the year to September 2026; a record $404 billion in October alone [M4] | In a growing economy with unemployment at 4.1% [M3] |
| Interest on the debt | About $1 trillion a year, projected $2.1 trillion in 2036 [CBO] | Already more than defence |
| 10-year Treasury yield | 4.93%, after weeks above 5% [M1][M6] | CBO's plan assumes 4.3% on average [CBO2] |
| Yield after inflation, 10 years | About 2.7% [M6] | Highest since 2008 |
| Inflation | 3.7% in the year to September; about 3.9% to 4.0% for October [M2] | Bond prices imply 2.3% a year for ten years [M6] |
| Dollar's share of reserves | 57% [R1] | 71% in 2001 |
| Gold in central-bank reserves | 27%, ahead of US government bonds at 22% [R2] | Central banks bought 321 tonnes last quarter, the most since late 2024 [M8] |
| US shares | 62% of the world; about 40 times ten-year profits in October [U][M7] | Japan was 37% of the world in 1989 [N] |
| Conflicts involving a state | 65 in 2025 [W] | The most since 1946. A US–Iran war since February has repeatedly shut the Strait of Hormuz [M9] |

## 2.3 What history says happens next

- **Big debts end in one of four ways:** growth, surpluses, default, or interest rates below inflation. For a country that prints its own money and has a mass electorate, the last has been the usual one (Part 4.3).
- **It is slow.** The US took 28 years after 1946. Britain took a century after 1815, by the hard road.
- **Reserve currencies fade over decades,** with reversals, and often share the role for a long time (Part 4.5).
- **The route matters as much as the destination.** A debt crisis can begin with falling prices and a strong currency. 1929–33 did. So did 2008. The inflation came later.

## 2.4 What forecasters expect

There is a rough consensus among independent voices: inflation above the 2010s, higher interest rates, debt that keeps rising, a dollar that erodes slowly, and a role for gold. They disagree on timing and on whether the central bank fights inflation or funds the government. Every one of them has something to sell or protect, and none has a record of timing (Part 5).

## 2.5 My reading

Part 6. In short: the direction of the consensus is probably right, its speed and violence are probably overstated, and the cheapest protection today may not be the one everybody names.

## 2.6 What it means for the fund

Part 7. In short: the fund's design already rests on the things that worked in every era. The long view shows a handful of soft spots to watch and test. It gives no reason to place a bet.

---

# Part 3. Where we stand: the facts on Saturday 21 November 2026

All from the US close on Friday 20 November unless dated otherwise.

**Markets.**
- S&P 500: 6,910. Down 3.7% on the day and 8.6% on the week, its seventh fall in a row and its worst week since April 2025. More than 10% below its record of 7,819 on 6 October. [M1]
- Nasdaq: down 5.3% on the day and now lower than at the start of 2026. The selling is led by AI shares. [M1]
- 10-year Treasury yield: 4.93%, down from 5.04%, after its longest run above 5% in almost two decades. [M1][M6]
- Gold: about $3,515 an ounce, a 14.5-month low. [M1] It averaged $4,262 in the third quarter and peaked in the first. [M8]
- Oil: Brent $95.84 on 13 November, after falling 16% and then 2.5% in two weeks. [M9] It was near $63 before the war (general knowledge from the same reports).
- The dollar is near a one-year high and the yen is at 158.6 to the dollar. [M1]

**Economy and policy.**
- Consumer prices rose 0.4% in October. The yearly rate was 3.7% in September and is estimated at 3.9% to 4.0% for October. [M2]
- The central bank's rate is 3.75% to 4.00%. A rise at the 8–9 December meeting is fully priced. It would be the second in four months, after three years without one. [M2]
- Jobs: 165,000 added in October. Unemployment 4.1%. Pay up 3.1% on the year, which is less than prices. [M3]
- The central bank stopped shrinking its balance sheet in November 2025 and began buying Treasury bills in December, about $40 billion a month at first and $10 billion a month by mid-2026. Its assets are about $6.7 trillion, against a peak of $9.0 trillion in 2022. [M5]
- The Treasury doubled its bond buyback programme in August, to calm long-term yields. [V1]

**What this adds up to.** An oil shock from a war, inflation near 4%, and a central bank that has chosen to fight it. Shares, gold and (until this week) bonds have all fallen together, and the dollar has risen. It is the 1980–82 pattern more than the 1973–74 pattern. The difference from 1980 is the debt: it was about 30% of the economy then (general history) and is 101% now, so every extra point of interest costs the government more than three times as much.

---

# Part 4. The long records

## 4.1 Shares, bonds and cash since 1900 [U]

- US, 1900 to 2025, a year after inflation: shares 6.6%, bonds 1.6%, cash 0.5%. Inflation averaged 2.9%, enough to turn one 1900 dollar into the buying power of about 3 cents.
- Shares were the best asset in all 21 countries with an unbroken record.
- The price of that return: shares and bonds have each lost more than 70% after inflation, on several occasions. A 60/40 mix never lost more than 50%.
- The US is about 62% of the world's share market, and more concentrated in a few companies than at any time in at least 100 years.
- Industries turn over completely. Railways were 63% of the US market in 1900 and are under 1% now.
- The US record is the winner's record. One study found US share prices gained 4.7% a year after inflation across most of the 20th century while the middle country of 39 gained 1.5%. [GJ] Some markets went to zero: the long-run studies count Russia in 1917 and China in 1949 as total losses. [U2]
- At its 1989 peak Japan was 37% of the world's share market and the US 29%. The Nikkei then fell by about four fifths and took 34 years to regain its peak. [N]

## 4.2 Gold and commodities

- **Gold since 1900:** 1.3% a year after inflation. Since the early 1970s, when its price was freed: 4.7% a year. [U]
- **Gold is a poor short-run shield against inflation.** It fell in 13 of the 28 years when inflation was above 3%. [U] It keeps its buying power over centuries, not over the years an investor lives through. [EH]
- **Gold can lose for a generation.** From January 1980 to 2001 it lost about 85% after inflation. In the first five of those years inflation ran above 6% a year and gold still halved, because interest rates rose faster than prices. [EH] The last twelve months have rhymed with that.
- **Governments change the rules on gold.** In April 1933 the US made private holding of gold illegal. In January 1934 it re-priced gold from $20.67 to $35. Americans could not legally own bullion again until the end of 1974. [G33]
- **Commodity futures, 1877 to 2015:** positive returns on average, and useful beside shares and bonds. [AQ]
- **Commodity prices move in super-cycles** lasting decades, around a slow trend. Things dug from the ground, energy most of all, have risen after inflation over the long run. Things that are grown have fallen. [J]
- **The 1970s are the case for hard assets.** A broad commodity index gained more than 20% a year over the decade. Oil rose about 800%, gold almost 1,000%. US shares lost ground to inflation. [A70] Someone who bought US shares at the 1966 high waited until about 1992 to be whole after inflation. [B70]
- **1929–33 is the case against a simple rule.** Prices fell. Commodity prices were still well under their 1926 level in early 1934. [G34] The gain in gold came by government order, after gold had been taken out of private hands.

## 4.3 Debt: how big debts have ended

- **The eight-century pattern.** Repeated default by governments is the usual pattern, in waves decades apart. That gap is why each generation believes "this time is different". Default tends to arrive with inflation, a currency crash, bank failures and debased money. [RR]
- **The modern rich-country way: pay in cheaper money.** From 1945 to 1980 interest rates after inflation were below zero about half the time. That shrank government debt by roughly 1% to 5% of the economy every year. Rules kept savers' money at home and in government bonds. [RS]
- **The US after 1946.** Debt fell from 106% of the economy to 23% by 1974. With balanced budgets, and without capped interest rates and surprise inflation, it would only have fallen to 74%. From 1942 to 1951 the central bank held long yields at 2.5% while inflation averaged about 7% in the five years to 1951. [AB]
- **The hard road is possible, and rare.** Britain's debt after the Napoleonic wars was about two to two and a half times its economy. It fell to under a third by 1914, with no default and no inflation, through roughly a century of budget surpluses under the gold standard. [H1] Two caveats. The voters of that Britain were largely the people who held the bonds (general history). And when Britain tried the same road in the 1920s, with surpluses and falling prices, the debt stayed stuck. [H1]
- **What the wider record says.** Budget cuts alone have often failed to bring debt down. Growth and inflation have done much of the work. [H2]
- **A live case: Japan.** Public debt above 200% of the economy. The central bank holds 43% of the government's bonds. For twenty years nothing broke. Now inflation has run above 2% for three years, the 10-year yield has reached 3% for the first time since 1996, the 30-year has set records above 4%, and the yen is near 160 to the dollar. [M10] Printing did not cause a collapse. It deferred a bill that is arriving slowly.
- **Today.** Part 2.2.

## 4.4 Interest rates since 1311 [S]

- Rates after inflation have drifted down for more than 500 years, by one or two hundredths of a percentage point a year.
- The reversals inside that drift have been fast. Low rates have never been safe to assume for long.

## 4.5 Reserve currencies

- The dollar was 57.1% of the world's currency reserves in early 2026, against about 71% in 2001. [R1]
- Gold was 27% of central banks' reserve assets at the end of 2025, ahead of US government bonds at 22%. Most of that jump is the gold price, and the IMF's own measure of the dollar's share has barely moved. [R1][R2]
- The last change of leader was not one event. The dollar first passed the pound in the mid-1920s. Both lost ground in the 1930s. The dollar became dominant only after 1945. For decades two currencies shared the job. [EF]
- Dalio's cases run the same way: Britain overtook the Dutch around 1750, yet the guilder kept its role until the 1780s. The US drew level with Britain around 1900, yet the pound kept its role for decades. [D3]

## 4.6 War, closed markets and markets that vanished

- The two world wars and the 1973–74 oil shock produced three of the six worst falls in world share markets since 1900. Yet a measure of geopolitical threat has not predicted share returns a month or a year ahead. [U] Markets fall on the event, not on the worry.
- In 2025 there were 65 armed conflicts involving a state and 8 between states, both the highest since 1946. Thirteen were full wars, the most since 1992. [W]
- The New York Stock Exchange shut on 31 July 1914 and did not fully reopen for four and a half months. [X14] The St Petersburg exchange reopened briefly in 1917 and then closed for good. [X17] The losers of the Second World War saw their currencies and debts wiped out. [D3]
- On 28 November 2025 a cooling fault in one data centre halted the world's largest futures exchange for more than 11 hours. [X25] Cyber incidents roughly doubled between the years before 2020 and 2024, and nearly one in five hits a financial firm. [IMF]

The worst losses in the record came from where the money was held and whether it could be moved, more than from which asset it was in.

## 4.7 What worked in every era

- **Trend following.** A simple rule across 67 markets made money after costs in every decade from 1880 to 2016, and in 8 of the 10 worst stretches for a 60/40 portfolio. [T]
- **Momentum** is the strongest and longest-lasting pattern in share returns since 1900. [U]
- **Spreading across countries** left investors in most markets better off. [U]
- **Bonds as a cushion did not work in every era.** Since 1875 US shares and bonds have moved together more often than apart: +0.35 from 1970 to 1999, about −0.3 from 2000. What drives it: inflation, rates after inflation, and trust in the government's credit. [SB]

## 4.8 Five eras

The US over about 100 years. Each era lasted 15 to 20 years and rewarded something different.

| Era | What happened | Did well | Did badly |
|---|---|---|---|
| 1929–1949 | Crash, falling prices, bank failures. The dollar re-priced against gold in 1934. World war. Bond yields capped. Inflation after 1946 | Government bonds and cash while prices fell. Gold, by government order, but not for private US holders. Shares bought after 1932 | Shares bought in 1929. Commodities to 1933. Bonds and cash after 1946, once inflation is counted |
| 1950–1965 | The post-war order. Growth. Low inflation | Shares | Bonds, as rates crept up. Gold, fixed at $35 |
| 1966–1982 | Inflation, two oil shocks, the dollar cut loose from gold in 1971 | Commodities, oil, gold, energy and small-company shares | Large US shares and bonds, after inflation |
| 1983–1999 | Inflation beaten. Rates falling. The Cold War ends | Shares and bonds together | Gold and commodities |
| 2000–2020 | Two crashes. Rates to zero. Money printing. China's boom, then its slowdown | Bonds. Gold and commodities to 2011. US shares after 2009 | Shares 2000–09. Commodities after 2011 |

Rows one and three carry numbers from the sources above. Rows two, four and five are general history. Roadmap order V2-21 replaces this table with measured numbers.

## 4.9 Why the last 20 years may mislead

1. **Bonds cushioned shares.** True since about 2000. Not true for most of the century before. [SB]
2. **Rates fell, then sat near zero.** Anything that borrows or holds long bonds was flattered. [S]
3. **US shares beat the world.** [U]
4. **Inflation was quiet** until 2021.
5. **Commodities had one boom and one long bust.** Our own cross-asset trend sleeve made about 2% a year in 2011–2020 (roadmap 2.1).
6. **The plumbing worked.** No long closure of a main market, no limits on moving money between rich countries.
7. **The dollar was unquestioned.** In April 2025 US shares, US bonds and the dollar all fell together, which is rare for the US. [S25]

Our own evidence is thin outside this stretch. The research harness has rebuilt prices back to 1985 only (VERIFIED: `research_harness/recon/reconstruct.py`; `explore/G4-STRESS-1985-PLAN.md`). Nothing we run has been through 1929–49 or 1966–82.

## 4.10 The new forces

- **AI and growth.** Estimates of what AI adds over ten years run from about half a percent in total (Acemoglu) through 15% (Goldman Sachs) to 10% to 20% a year (Dario Amodei, head of Anthropic, the company that made me). [A1] The measured facts so far: firm-level studies find large savings on single tasks; a Goldman economist put AI investment's contribution to US growth in 2025 at about zero, because the equipment is imported; and personal computers took about 15 years to show up in the productivity numbers. [A1]
- **AI and interest rates.** One argument says very fast growth would push rates up. A reply says people might save more and push them down. A study of 30 major AI releases found bond yields fell on those days. [AI1][AI2][AI3]
- **Cyber and conflict.** Part 4.6. Assume that at some point in ten years a price feed, a broker or an exchange is out of reach.
- **People.** The US now needs very few new jobs each month to hold unemployment steady, because of retirements and less immigration. [M3] Fewer workers means slower growth and, other things equal, more pressure on prices. (The second half is my inference.)

A disclosure: I am an AI made by an AI company, and AI shares are at the centre of this week's sell-off. I hold nothing and gain nothing either way, but treat my view on AI with that in mind.

---

# Part 5. What forecasters say, and what each stands to gain

## 5.1 How good is anyone at this?

- **Economists.** Of 153 recessions in 63 countries between 1992 and 2014, the consensus forecast in the spring of the year before foresaw 5. [F2]
- **Wall Street strategists.** Since 2000 their average year-ahead call for the S&P 500 has been a gain of about 8% to 9%, every single year. The index fell in 7 of those 25 years. The average miss is about 14 percentage points. [F1]
- **Experts in general.** The largest study of expert prediction, 284 experts over two decades, found them poor at long-range forecasts. [F3]
- **Dalio.** He warned of a 1937-style slump in 2015, the end of the debt cycle in 2016, a downturn within two years in 2018, and said "cash is trash" weeks before the 2020 crash. His main fund lost 18.6% in the first eight months of 2020 after close to a decade of low single-digit gains. Over its whole life it has averaged about 11% a year, and it made money in 2008. [F4] A fair summary: a great long-run investor whose public crisis calls have not been timely.

So the answer to "are the experts pretty much guaranteed to be right?" is no. Not on timing, and not one of them.

## 5.2 Voice by voice

| Voice | What they expect | What they gain from saying it | Checked against 2026 |
|---|---|---|---|
| **Dalio** [D1][D4] | Breakdown stage near. Debt crisis in about three years, give or take two. Hold 10–15% gold, fewer bonds | Books and a public brand built on the cycle | The pressures he lists are in the data. Gold is a third below its peak. No timing record (5.1) |
| **Luke Gromen** [V1] | The government cannot afford yields above about 4.7%. The central bank will cap yields by printing into an inflation spike. Gold $8,000 to $10,000 | Sells a research letter. His audience holds gold and bitcoin. Some interviews are sponsored by bullion dealers | The arithmetic is sound: by his count, interest, entitlement payments and veterans' spending took 106% of federal income last year. The path was wrong in 2026: the central bank raised rates, yields went above 5% and gold fell |
| **Jim Bianco** [V2] | Inflation stuck at 3% to 4%. A "4-5-6" world: 4% on cash, 5% on bonds, 6% on shares. Said the central bank must raise rates to calm bonds | Sells research | The closest to the 2026 data. He changed his own view on bonds from negative to neutral near 4.9% |
| **Russell Napier** [V3] | 15 to 20 years of rates held below inflation of 4% to 6%, with limits on moving money. Possibly falling prices first | Sells research and teaching | Fits 1945–80. Not yet visible: rates after inflation are high and positive |
| **Kenneth Rogoff** [V4] | Another bout of inflation within ten years. Rates higher for a long time. The dollar stays first with a smaller share | An academic with a book | Inflation call on track. His mid-2025 call for a recession within 18 months has not happened so far |
| **Lyn Alden** [V5] | "The fiscal side will win": a slow, steady return to money printing | Sells a newsletter | Partly visible: the balance sheet stopped shrinking and bill purchases began, on a small scale |
| **IMF** [O1] | World growth 3.1% in 2026 and 3.4% in 2027, about 3.2% a year to 2031. World public debt near 100% of output, the highest since 1945. Warns on debt and the AI boom | Cannot forecast a crisis in a member country | Forecasts of this kind miss turning points (5.1) |
| **CBO** [CBO][CBO2] | Debt 120% of the economy in 2036 | Must assume current law, no recession, and a 10-year yield averaging 4.3% | The yield is already above that. Its own higher-rate cases give 124% to 133% |
| **The bond market** [M6] | Inflation of about 2.3% a year for ten years. A yield after inflation of about 2.7% | Money on the line. The least biased forecaster here | Was badly wrong in 2020–21, just before inflation hit 9% (general knowledge) |
| **Big firms, year-ahead targets** [F1] | Up about 8%, every year | They sell investments | Never a down year forecast. Ignore |
| **Big firms, ten-year numbers** [B1] | Low returns on US shares: about 5% a year before inflation (Vanguard); minus 7% a year after inflation for seven years (GMO) | Flows into their other funds. GMO has a long-standing value tilt | Not cheerleading. But these numbers have been too low for a decade |
| **AI builders** [A1] | Very fast growth | They are raising money | Not yet in the productivity numbers |

## 5.3 What the consensus is, and where it splits

**Agreed by most independent voices:** inflation higher than the 2010s; interest rates higher; debt that keeps rising because nobody will cut it; a dollar that erodes slowly; gold as a real reserve asset; US shares priced for a great deal.

**Not agreed:** when; and whether the central bank fights inflation (Bianco's 2026 call, and what has happened) or is forced to fund the government (Gromen, Napier, Alden). That one split decides whether gold or cash wins a given year.

---

# Part 6. My own reading

Opinion. Built from Parts 3 to 5 only. Odds are my own judgment, written down so they can be scored.

## 6.1 Markus's claim, tested

The claim: faced with fixing the economy or printing money, humans and empires almost always print, which collapses the currency, causes massive inflation and brings down the empire.

**"They almost always print": mostly right, with a lag.** For a government that borrows in its own money and faces voters, the record supports it: 1933–34, 1942–51, 1945–80 across the rich world, 1971, 2008–21 (Part 4.3). The exceptions are instructive. Britain after 1815 and the US after its civil war paid down debt the hard way, under gold, when bondholders dominated the electorate. Countries that cannot print (general history: the euro area's weaker members after 2010) had to cut or default. And right now the US is choosing the pain: rates up, inflation fought. The claim is about where that road ends, and history says it usually ends when the pain becomes political.

**"Which collapses the currency and is massively inflationary": mostly wrong on size.** For the issuer of a leading currency the usual result is slow erosion. The dollar lost 97% of its buying power over 125 years, at 2.9% a year, and people got rich holding American shares the whole way. Japan has printed for a quarter of a century and has a weak yen and rising yields, not a collapse. The 2020–22 burst took US inflation to 9% and back to 3%. The violent cases, where money became worthless, involved lost wars, debts owed in gold or foreign money, or wrecked industry.

**"And brings down the empire": the order is the other way round.** Debasement travels with decline more than it causes it. Britain overtook the Dutch thirty years before the guilder failed. The pound was devalued for forty years after Britain had already lost its lead. The time scale is decades.

**My version of the claim:** *they will most likely choose to let money lose value faster than they admit, for a long time, in bursts, and it will be survivable for anyone not relying on cash and ordinary bonds alone.*

## 6.2 Where I think the experts are right

- The debt arithmetic. Nobody credible disputes it, including the government's own budget office.
- That the politically easy exit is rates below inflation.
- That bonds stopped being a reliable cushion once inflation returned.
- That central banks are quietly moving toward gold, and buy more when it falls.
- That a market this concentrated and this highly priced is fragile. This week is an example.

## 6.3 Where I think they are biased or overreaching

1. **Timing.** Every structural bear has been early by years. A view that needs "eventually" cannot run a portfolio.
2. **The route.** Most of the "print" camp skipped the step we are in: the central bank fighting first. In that step their favourite assets fall. Gold has lost a third. That is what happened in 1980–82 and it lasted years.
3. **Collapse talk.** It sells letters and gold. The base rate for the leading currency is erosion.
4. **The other currencies are no better.** Europe, Japan, Britain and China carry the same debts and older populations. The dollar can lose value against things without losing its rank against them.
5. **Gold is not the only shelter, and today may not be the cheapest.** A 10-year US bond linked to inflation pays about 2.7% a year on top of whatever inflation turns out to be. Gold's long-run record is 1.3%, with an 85% loss inside it. For the specific fear of inflation, the linked bond is a contract and gold is a hope. The linked bond has its own risks: the government measures the inflation, and can tax or change the terms. But the camp that warns about printing rarely mentions it, and their audiences do not hold it.
6. **Ordinary bonds at 5% are not ordinary bonds at 1%.** "Hold fewer bonds" was right in 2020. If the central bank later caps yields, whoever already owns 5% bonds is paid first, in price. The damage of repression falls on later savers.
7. **AI is the one thing that could make the whole story wrong,** and nobody can size it. If it lifts growth by even one point a year, the debt sums change. The bears mostly wave it away. The builders mostly oversell it.
8. **The big firms** are biased the other way on short horizons and should be ignored there. On ten-year horizons they are cautious, and wrong for a decade so far. Markus's distrust is well founded for the first and less so for the second.

## 6.4 The decade, 2027 to 2036: four roads

| Road | What it looks like | Who wins | My odds |
|---|---|---|---|
| **A. Repression** | Inflation averages 3% to 5%. Rates held below it for long stretches. Rules steer savings into government debt. No crash, a slow grind | Hard assets, trend rules, shares of firms with pricing power, inflation-linked bonds bought early. Cash and new bonds lose | 45% |
| **B. AI growth** | Productivity lifts growth. Inflation near 2% to 3%. Debt stabilises | Shares, above all. Bonds do fine. Gold and commodities lag | 25% |
| **C. Hard money** | The central bank keeps rates high for years. Recessions. Budget cuts forced by the bond market | Cash and bonds. Everything else struggles for years | 20% |
| **D. Disorder** | A funding crisis, a great-power war, or inflation above 10%. Controls on money. Markets shut or split | Whatever is held in the right place. Gold, if you can keep it | 10% |

Road A is Markus's and the consensus view, and it is my most likely single road. But it is less likely than not. Three specific numbers for scoring in 2036:

- US inflation averages above 3% a year over 2027–2036: **55%**. Above 4%: 25%. Above 6%: 7%.
- The dollar is still the largest reserve currency in 2036: **90%**. Its share is below 50%: 40%.
- Gold is higher in 2036 than today after inflation: **65%**. US shares return less than 3% a year after inflation over the decade: 55%.

## 6.5 The year 2027: four paths

| Path | What happens | Shares | Bonds | Gold | Oil and commodities | My odds |
|---|---|---|---|---|---|---|
| **1. Tight money breaks something** | A recession or a market accident. Rate cuts by late 2027 | Down | Up strongly | Down, then up | Down | 30% |
| **2. Stagflation drags on** | War and oil keep inflation at 4% or more. Rates stay high or rise | Down or flat | Flat or down | Down or flat | Up | 25% |
| **3. Relief** | The strait reopens, oil falls, inflation eases toward 3%, the rate rises stop | Up | Up a little | Up a little | Down | 30% |
| **4. The print comes early** | A bond-market scare. The central bank cuts or buys bonds with inflation still high | Up | Capped | Up strongly | Up | 15% |

Put together: shares up or down in 2027 is close to a coin toss (I make it 52% up). Bonds are more likely up than down (about 80%), because a 5% yield is a large cushion. Gold is slightly more likely up than down (58%). Oil is slightly more likely down (55%), because it already carries a war premium and three of the last five oil spikes were lower a year later (general history). None of these is strong enough to act on. The thesis paper files them in the platform's own prediction format so they are scored with everybody else's.

## 6.6 What would change my mind

- Toward Road A sooner: the central bank cutting rates with inflation above 3.5%; a formal cap on yields; a failed Treasury sale; new rules forcing funds to hold government debt.
- Toward Road B: US productivity growth above 2.5% for four quarters running; inflation falling while growth holds.
- Toward Road C: real budget cuts passed into law; rates held above inflation through a recession.
- Toward Road D: limits on taking money out of a major country; a war between large powers; a main exchange shut for more than a week.

---

# Part 7. For the fund

## 7.1 What the design already has right

- **Trend rules in most lines.** The one approach with evidence in every decade since 1880. This month shows why: a trend rule is out of gold as it falls and cutting shares, without needing an opinion.
- **A hard-assets bucket,** and a macro label that moves toward it when prices say inflation is up.
- **Sizing by risk, a cap on borrowing, a coded brake.**
- **Many lines that do not move together.**
- **Results in Australian dollars** as well as US dollars.

## 7.2 Soft spots the long view shows

None is a reason to change a rule now. Each is something to watch and test.

1. **The "defensive" bucket leans on bonds.** D-RP always holds bonds (VERIFIED: `RP_LINES = ("SPY", "IEF", "GLD")` in `research_harness/league/families.py`, no trend test). In 1946–51 or 1966–82 that was a steady loss after inflation. D-XTREND holds bonds only when they are rising.
2. **"Beat cash" is a low bar when cash loses to inflation.** Results need a column after inflation.
3. **One country, one currency, one broker per market.** Every holding is a US-listed fund through Alpaca or a currency position through OANDA (VERIFIED: `trading-platform/twins/prices.py`, `kraken-bot/alpaca_etf_engine.py`).
4. **A fund is not the thing itself.** An oil fund holds futures and pays to roll them. A gold fund is a claim on a custodian. (General knowledge.)
5. **No name for "everything American falls together".** The macro label has four states. Shares, bonds and the dollar down at once would most likely read as "bust" and move the fund toward the defensive bucket, part of which always holds bonds.
6. **No inflation-linked bonds anywhere in the fund,** although they are the most direct protection against the scenario Markus fears (6.3, point 5).
7. **One year, one kind of market.**
8. **A long outage loses decisions** (VERIFIED: `CATCH_UP_SESSIONS = 15`, `run_days` in `trading-platform/twins/league.py`).

## 7.3 What the roadmap adds (V2-18 to V2-22, and decision D14)

- **Long-view panel:** twelve slow gauges, for reading only. Every result also shown after inflation and beside a "just hold gold" yardstick.
- **Four daily flags** from prices: three-way sell-off, hard assets lead, tight money, bonds are hedging. Stored. Read by no rule.
- **Three changes to the build (decision D14),** which are not bets on the long view: a line and a yardstick for inflation-linked Treasuries; a defensive bucket made only of lines that can step aside into cash; and the tight-money flag.
- **Other eras:** our rules run through 1929–49, 1966–82 and Japan after 1989. Information only.
- **World-breaks drills:** tests and a one-page runbook.

## 7.4 What we deliberately do not do

- **No "cycle score".**
- **No rule reads the panel or the flags.**
- **This file is never pasted into an AI prompt.** The AI sees the same dated numbers the page shows. Otherwise 2027 would test the story, not the AI.
- **No tuning from the other-eras tests.**
- **No date.**

## 7.5 Ideas parked for the intake (not orders)

Each needs its one page, a registration and a replay (roadmap V2-16).

- Inflation-linked Treasuries as the cash of the hard-assets bucket. (A plain line and a yardstick for them are already proposed: roadmap D14.)
- A fifth macro label, "debt stress", built from the three-way flag.
- A version of D-RP that holds bonds only when they are rising.
- Gold-mining and resource shares as a hard-asset line.
- A share line for countries that sell commodities (Australia, Canada, Brazil).
- Trend on a wider set of commodities than four funds.

## 7.6 Questions for real money (2028), for Markus and his advisers

Not for Opus, and not advice.

- Should everything sit in one country, with one broker, in one currency?
- What protects the account if a broker fails or a market is shut for months?
- Should some hard-asset holding be in a form that does not depend on a US-listed fund?
- The Australian dollar has tended to rise with commodity prices, which trims US-dollar gains brought home. (General knowledge. The Australian-dollar columns in roadmap V2-07 will measure it.)

---

# Part 8. Signposts

Look once a quarter. Each is on the panel (V2-18) or the flags (V2-19). No single one means much.

| Would support "a new era is arriving" | Would support "more of the same" |
|---|---|
| Interest cost keeps rising as a share of tax income | The deficit narrows and interest cost levels off |
| Long yields rise while the central bank is cutting | Long yields fall when growth slows |
| Rates held below inflation for a year or more | Rates above inflation, inflation heading to 2% |
| The dollar's share of reserves falls below 55%; central banks keep buying gold as it falls | The share holds; gold buying fades |
| Shares, bonds and the dollar fall together more often | Bonds rise when shares fall |
| Hard assets beat shares for a year or more | Shares lead and commodities fade |
| New limits on moving money, on gold, or on foreign holders | None |
| Conflicts between large states widen | Conflicts settle |
| AI news is about lost jobs and fights over chips and power | Measured productivity growth rises |

---

# Part 9. Limits and sources

**Limits.**
- Nothing was run. Every number comes from a published source read on 21 Nov 2026 and was not checked against raw data.
- Long records are stitched from many sources and lean toward survivors.
- A few hundred years hold only a handful of full cycles.
- Several sources are summaries or news reports of the original work. The UBS yearbook was read in its public summary only.
- This week's market figures are from news reports of the Friday close.
- Part 6 is opinion.

**Dalio and his critics.**
- [D1] https://fortune.com/2026/03/14/ray-dalio-big-cycle-debt-crisis-political-disorder-world-order/
- [D2] https://x.com/RayDalio/status/2022788750388998543
- [D3] https://finance.yahoo.com/news/ray-dalio-commentary-changing-world-202256827.html
- [D4] https://fortune.com/2026/01/09/ray-dalio-on-38-trillion-national-debt-grandchildren-will-be-paying-devalued-dollar-currency/ · https://theedgemalaysia.com/node/815507
- [F4] https://awealthofcommonsense.com/2025/03/predicting-a-financial-crisis/ · https://realinvestmentadvice.com/resources/blog/ray-dalio-is-predicting-a-financial-crisis-again/ · https://fortune.com/2020/09/15/the-losses-continue-to-pile-up-for-hedge-fund-king-ray-dalio/ · https://www.cmcmarkets.com/en-au/opto/the-strategic-mindset-behind-bridgewaters-ray-dalio
- Reviews: https://www.aier.org/?p=144617 · https://brandonadams.substack.com/p/book-review-ray-dalios-the-changing · https://thedailyeconomy.org/article/debt-destiny-and-dalio-a-review-of-how-countries-go-broke/

**This week and this year.**
- [M1] https://spectrumlocalnews.com/nc/coastal/business/2026/11/20/wall-street-nov-20-2026 · https://www.cnbc.com/2026/11/19/stock-market-today-live-updates.html · https://cappnotes.substack.com/p/closing-look-friday-november-20-2026 · https://www.marketalleys.com/post/marketalleys-closing-tape-2026-11-20
- [M2] https://kpmg.com/us/en/articles/2026/october-2026-cpi.html · https://www.dailysabah.com/business/economy/us-inflation-tops-forecasts-fueling-december-fed-rate-hike-bets/amp · https://stockanalysis.com/news/us-cpi-rises-october-2026/ · https://news.ifyouspent.com/en/news/october-cpi-report-explained-november-2026
- [M3] https://www.dailysignal.com/?p=257482 · https://abc7news.com/story/us-employers-added-surprising-165000-jobs-october-unemployment-rate-dipped-41/20020018/
- [M4] https://www.cbo.gov/publication/61986 · https://kfgo.com/?p=1374066
- [M5] https://www.federalreserve.gov/monetarypolicy/May-2026-Federal-Reserve-Balance-Sheet-Developments.htm · https://economics.bmo.com/en/publications/detail/5f583f07-a4e8-4c6d-a213-ea780d84fae4/ · https://home.treasury.gov/system/files/221/TBACCharge1Q12026.pdf · https://rpc.cfainstitute.org/blogs/enterprising-investor/2026/when-non-monetary-fed-operations-move-markets
- [M6] https://fred.stlouisfed.org/series/T10YIE · https://alfred.stlouisfed.org/series?seid=DFII10 · https://tipswatch.com/2026/09/17/10-year-tips-reopening-gets-real-yield-of-2-653-highest-in-nearly-18-years/ · https://theedgemalaysia.com/node/826232
- [M7] https://www.mitrade.com/insights/news/live-news/article-8-2221560-20261102 · https://www.webull.com/news/15927665313498112 · https://fxnewsgroup.com/forex-news/institutional/sp-500-forward-p-e-falls-to-three-year-low-is-the-valuation-reset-creating-an-opportunity-or-signalling-more-risks/
- [M8] https://www.gold.org/goldhub/research/gold-demand-trends/gold-demand-trends-q3-2026/central-banks · https://www.kitco.com/news/article/2026-11-03/gold-demand-remains-near-record-highs-central-bank-buying-surges-42-wgc
- [M9] https://www.nationthailand.com/news/world/40073488 · https://www.thestar.com.my/aseanplus/aseanplus-news/2026/07/11/oil-prices-settle-lower-at-the-weekend-on-hopes-for-smoother-shipping-in-the-strait-of-hormuz
- [M10] https://www.mof.go.jp/english/policy/jgbs/publication/debt_management_report/2026/esaimu2026-2-3.pdf · https://www.nippon.com/en/japan-data/h02877/ · https://www.imf.org/en/publications/fandd/issues/2026/09/japans-debt-beyond-the-headlines-anand/index.md
- [CBO] https://www.cbo.gov/publication/61882 · https://www.crfb.org/papers/cbos-february-2026-budget-and-economic-outlook
- [CBO2] https://www.cbo.gov/publication/62809
- [R1] https://data.imf.org/en/news/imf%20data%20brief%20july%201 · https://wolfstreet.com/2026/03/28/status-of-us-dollar-as-global-reserve-currency-usd-share-drops-to-31-year-low-as-central-banks-diversify-into-other-currencies-gold/
- [R2] https://finance.yahoo.com/markets/commodities/articles/gold-overtakes-us-treasuries-top-100334717.html
- [W] https://www.uu.se/en/news/2026/2026-06-09-ucdp-record-number-of-conflicts-between-states
- [O1] https://www.koreatimes.co.kr/world/20261013/imf-raises-its-forecast-for-world-growth-this-year-but-warns-of-risks-from-ai-boom-and-debt · https://www.crfb.org/blogs/latest-imf-outlook-highlights-strong-growth-amid-rising-debt · https://www.thestandard.com.hk/finance/article/342505/IMF-says-global-growth-on-track-to-reach-3-in-2026-but-risks-remain-high

**The long records.**
- [U] UBS Global Investment Returns Yearbook 2026 (Dimson, Marsh, Staunton), public summary: https://www.ubs.com/content/dam/assets/wm/static/cio/documents/giry2026-summary-public.pdf · https://www.ubs.com/global/en/media/display-page-ndp/en-20260303-global-investment-returns-yearbook-2026.html
- [U2] https://www.greaterwrong.com/posts/yt5QiEkaASsA2iYrN/what-rate-of-return-should-you-expect/comment/gvGWFry9R2CXjHWGS
- [GJ] https://www.nber.org/digest/jul97/century-global-stock-markets
- [N] https://www.nippon.com/en/japan-data/h01927/nikkei-index-sets-first-record-high-since-1989.html · https://www.bostonglobe.com/2024/02/22/business/japans-nikkei-stock-index-breaks-its-1989-record-surges-an-all-time-high/ · https://www.bnnbloomberg.ca/japan-nikkei-hits-record-high-last-seen-more-than-30-years-ago-1.2037726
- [T] https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing · https://alphaarchitect.com/time-series-momentum-aka-trend-following-the-historical-evidence/
- [SB] https://top1000funds.com/wp-content/uploads/2024/11/Empirical-Evidence-on-the-Stock-Bond-Correlation.pdf
- [EH] https://www.nber.org/papers/w18706 · https://people.duke.edu/~charvey/Research/Published_Papers/P148_Gold_golden_constant.pdf · https://www.etf.com/sections/index-investor-corner/swedroe-debunking-gold-mythology
- [G33] https://en.wikipedia.org/wiki/Executive_Order_6102 · https://www.nber.org/system/files/working_papers/w26085/w26085.pdf
- [G34] https://www.bnnbloomberg.ca/victory-in-gold-battle-saved-the-new-deal-1.1083172
- [AQ] https://www.nber.org/papers/w22793 · https://www.aqr.com/Insights/Datasets/Commodities-for-the-Long-Run-Index-Level-Data-Monthly
- [J] https://www.nber.org/papers/w18874 · https://www.sfu.ca/~djacks/data/boombust/index.html
- [A70] https://awealthofcommonsense.com/?p=42582 · https://www.schroders.com/en-ch/ch/professional/insights/inflation-back-to-the-1970s/
- [B70] https://www.briefs.co/?p=22779
- [RR] https://www.nber.org/papers/w13882
- [RS] https://www.nber.org/papers/w16893
- [AB] https://www.nber.org/system/files/working_papers/w31577/w31577.pdf · https://www.aeaweb.org/research/wwii-debt-growth-us
- [H1] https://banque-france.fr/en/publications-and-statistics/publications/historical-lessons-large-increases-government-debt · https://www.imf.org/-/media/files/publications/wp/2019/wp1906.pdf.md · https://www.economicsobservatory.com/what-can-we-learn-past-about-how-pay-crisis
- [H2] https://www.imf.org/en/blogs/articles/2023/04/10/how-to-tackle-soaring-public-debt
- [S] https://www.bankofengland.co.uk/working-paper/2020/eight-centuries-of-global-real-interest-rates-r-g-and-the-suprasecular-decline-1311-2018
- [EF] https://www.nber.org/papers/w14154
- [X14] https://www.guinnessworldrecords.com/world-records/new-york-stock-exchange-longest-trading-suspension · https://users.nber.org/~confer/2003/URCDAE03/silber.pdf
- [X17] https://globalfinancialdata.com/august-1914-when-global-stock-markets-closed-2
- [X25] https://www.aljazeera.com/economy/2025/11/28/global-futures-reopen-after-exchange-operator-cme-hit-by-hours-long-outage
- [S25] https://www.npr.org/2025/04/21/nx-s1-5361202/trump-tariffs-dollar-china-wall-street-bonds
- [IMF] https://www.imf.org/en/blogs/articles/2024/04/09/rising-cyber-threats-pose-serious-concerns-for-financial-stability

**Forecasters.**
- [F1] https://www.bloombergquint.com/markets/year-to-forget-for-s-p-500-strategists-who-missed-by-400-points · https://peopledaily.digital/business/wall-street-is-again-making-irrelevant-market-forecasts
- [F2] https://www.bnnbloomberg.ca/why-are-economists-so-bad-at-forecasting-recessions-1.1250945 · https://voxeu.org/article/predicting-economic-turning-points
- [F3] https://www.scientificamerican.com/article/financial-flimflam/
- [V1] https://en.coinotag.com/gold-xau-luke-gromen-us-interest-costs-106-percent-revenue · https://advisoranalyst.com/2026/08/19/the-bull-market-that-loses-you-money-luke-gromen.html/ · https://www.tftc.io/people/luke-gromen · https://podcastalpha.substack.com/p/gold-is-replacing-treasuries · https://podwise.ai/episodes/8718364
- [V2] https://stockwirex.com/?p=54194 · https://www.webull.ca/news-detail/15275649985963008 · https://podwise.ai/episodes/8897102
- [V3] https://firstlinks.com.au/why-central-banks-are-becoming-impotent · https://marcellus.in/story/russell-napier-interview-we-are-headed-towards-a-system-of-national-capitalism/
- [V4] https://www.promarket.org/2025/07/24/what-happens-after-the-dollars-hegemony-ends/ · https://www.imf.org/en/publications/fandd/issues/2025/12/cafe-economics-the-dollar-game-bruce-edwards · https://foreignpolicy.com/2025/07/08/what-the-dollars-decline-reveals-about-america/
- [V5] https://www.kitco.com/news/video/2026-09-30/washington-is-heading-for-10-trillion-in-deficits-with-no-appetite-to-cut-says-lyn-alden · https://www.kitco.com/opinion/investment-trends/2025-12-08/lyn-alden-says-fed-has-entered-gradual-print-era-us-economy
- [B1] https://www.morningstar.com/markets/experts-forecast-stock-bond-returns-2026-edition · https://www.gmo.com/globalassets/articles/gmo-7-year-asset-class-forecast/2026/gmo-7-year-asset-class-forecastsep26.pdf
- [A1] https://investing.com/news/stock-market-news/goldman-sees-significant-economic-upside-from-ai-adoption-432SI-3471422 · https://mitsloan.mit.edu/node/48902 · https://bcf.princeton.edu/wp-content/uploads/2026/02/2026.02.19-MA-Nick-Bloom.pdf · https://www.tomsguide.com/ai/ai-contributed-basically-zero-to-the-us-economy-last-year-according-to-goldman-sachs · https://www.fortune.com/2026/07/14/goldman-ai-productivity-reality-check-worker-sabotage/
- [AI1] https://forum.effectivealtruism.org/posts/8c7LycgtkypkgYjZx/agi-and-the-emh-markets-are-not-expecting-aligned-or
- [AI2] https://marginalrevolution.com/marginalrevolution/2025/01/will-transformative-ai-raise-interest-rates.html
- [AI3] https://economics.mit.edu/sites/default/files/2026-07/Do%20Markets%20Believe%20in%20Transformative%20AI.pdf
