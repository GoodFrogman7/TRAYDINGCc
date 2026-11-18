# Venue access: crypto perpetual futures by API for a New York retail trader (Coinbase vs Kraken)

As of 2026-11-18 02:45 UTC (evening of 2026-11-17 in New York).

## Bottom line

- **Kraken is not usable from New York.** Kraken's own support pages say it does not offer services to residents of New York (and Maine). That blocks everything: spot, the offshore `PF_` perpetuals on futures.kraken.com (which are not offered to US residents in any state), and the new US perpetuals Kraken launched in June 2026 (which require a verified Kraken account).
- **Coinbase is the only candidate of the two.** Coinbase Financial Markets (CFM) offers CFTC-regulated "perpetual-style" futures listed on Coinbase Derivatives (CDE), tradable through the Advanced Trade API. They are live and liquid (see live table below).
- **New York eligibility for Coinbase futures is NOT confirmed from a primary source.** I found no Coinbase page that either includes or excludes New York for futures. One third-party guide says Coinbase futures are available in every state including New York. Treat it as "probably yes, unproven". The only definitive test is to complete Coinbase's futures onboarding on the real account before writing any venue-specific code.
- **Coinbase trading fees for a small account are NOT confirmed.** Coinbase's own sources conflict (0.02% with a $0.15 per-contract minimum vs 0.05%). Read the real rate from the account before sizing anything (method below).

## How this was researched, and its limits

- The session's network policy blocked direct fetching of help.coinbase.com, support.kraken.com, www.kraken.com, docs.cdp.coinbase.com, docs.kraken.com, cftc.gov and dfs.ny.gov. Statements attributed to those pages come from **web-search extracts of the pages**, not from reading the full pages. Wording, dates and context could be off.
- Two public market-data APIs were reachable and were queried directly at 2026-11-18 02:40-02:42 UTC. Everything marked **[live API]** is first-hand:
  - `GET https://api.coinbase.com/api/v3/brokerage/market/products?product_type=FUTURE` (no auth)
  - `GET https://api.coinbase.com/api/v3/brokerage/market/product_book?product_id=...` (no auth)
  - `GET https://futures.kraken.com/derivatives/api/v3/instruments` and `/feeschedules` (no auth)
- Confidence labels used below: **[live API]** first-hand; **[primary, via search]** exchange's own page seen only as a search extract; **[secondary]** press or third-party; **[unconfirmed]** could not establish.

---

## 1. Kraken

### 1a. Kraken Futures linear perpetuals (`PF_` on futures.kraken.com): not for US residents

- Kraken's product pages describe the multi-collateral perpetuals as for clients **outside the United States**; US clients are pointed to a separate entity, Kraken Derivatives US. [primary, via search]
- The live instruments feed lists 219 `PF_` contracts, each with a `platformsPermitted` list (`europa`, `mtf`, `dlt`, `payward_digital_solutions`, `beaufort_fiduciaries`, ...). No US platform appears in that list. This is consistent with the US exclusion but is my reading of an undocumented field, not a stated rule. [live API, inference]
- For reference only (not accessible to a US person): `PF_XBTUSD` contract size 1 BTC with 4-decimal trade precision, tick $1, initial margin 1% / maintenance 0.5% at the first tier; fee schedule 0.02% maker / 0.05% taker below $5M 30-day volume. [live API]

### 1b. What Kraken offers US residents instead

- **Kraken Derivatives US** = NinjaTrader Clearing, LLC d/b/a Kraken Derivatives US, a CFTC-registered futures commission merchant. Offers CME-listed futures and, since about 15 June 2026, **CFTC-regulated perpetual futures listed on Bitnomial Exchange** (a CFTC designated contract market that Kraken's parent Payward acquired in spring 2026). Traded on Kraken Pro. [primary, via search; launch date from press]
- Launch markets: BTC, ETH, SOL, XRP, ADA, LINK, DOGE, LTC, AVAX. USD collateral only. [secondary, consistent across sources]
- Funding: 8-hour interval. Kraken's blog gives 7:00 pm, 3:00 am, 11:00 am CT; Kraken's product page gives 00:00, 08:00, 16:00 UTC; the fee page says funding is settled as one cash adjustment at 3:00 pm CT daily. These do not agree with each other. [primary, via search; conflicting]
- Contract size: a 2026 Bitnomial CFTC filing describes the BTC perpetual `PBTCUC` as 0.01 BTC, tick $5. Not confirmed as the contract Kraken routes to. [primary filing, via search]
- Fees: Kraken's "US Futures Fees" page was extracted twice with different numbers: an older version at $0.15 per contract per side all-in ($0.03 commission + $0.10 exchange/clearing + $0.02 NFA), and a newer one at $0.0113 per contract per side ($0.0003 + $0.001 + $0.01). I could not tell which is current. [primary, via search; conflicting]
- Eligibility text: "US residents can trade Perpetual Futures directly on Kraken Pro ... Certain states may have restrictions - eligibility is confirmed at sign-up", and requires a verified Kraken account. [primary, via search]
- **API access to the US perpetuals: unconfirmed.** Kraken's developer docs index shows a "US Perps" section but I could not read it. The documented futures REST/WebSocket/FIX API at futures.kraken.com is the non-US platform.

### 1c. Kraken and New York

- Kraken's "Where is Kraken licensed or regulated?" page and its "Quick start for clients in the United States" page both state that Kraken (including Kraken Securities LLC and Kraken Adviser LLC) **does not offer services to residents of New York (NY) and Maine (ME)**. A search extract dated the licensing page as updated August 2026. [primary, via search]
- I found no Kraken statement that carves the Derivatives US perpetuals out of that exclusion, and the product requires a verified Kraken account that a New York resident cannot open. Conclusion: **not available to a New York resident.** The perps-specific state list itself was not seen. [inference from primary]
- NYDFS's own licensee list could not be fetched. Two aggregator sites list Kraken as a BitLicense holder; that contradicts Kraken's own page and I give it no weight.

---

## 2. Coinbase US perpetual-style futures

### 2a. Structure

- Listed on **Coinbase Derivatives, LLC (CDE)**, a CFTC designated contract market; cleared at Nodal Clear; retail access through **Coinbase Financial Markets, Inc. (CFM)**, a CFTC-registered FCM and NFA member. Futures cash is held at CFM, separate from the Coinbase Inc. spot account. [primary, via search]
- Launched 21 July 2025 with BTC and ETH; many more since. [primary, via search]
- These are a different product from Coinbase's international perpetuals (`BTC-PERP-INTX`), which are not for US persons. A May 2026 CFTC step let CFM connect US clients to Deribit's global perpetuals and options; coverage describes that as institutional so far, with US retail "later". Not confirmed as available to US retail. [secondary]

### 2b. Eligibility

- US: requires an existing verified Coinbase account, a futures application (age, experience, employment, income, net worth, photo ID) and a tax ID. If you later lose an eligible address, the futures order screen is removed and open positions are liquidated. [primary, via search]
- **New York: unconfirmed.** No Coinbase source found that names New York either way for futures. Coinbase Inc. holds an NYDFS virtual currency licence for spot. State carve-outs that Coinbase does publish (Nevada, Michigan, Ohio) concern prediction markets and sports contracts; one aggregator report applies a Nevada exclusion to CFM "futures and swaps" generally. One third-party guide (Datawallet, 2026) says Coinbase's regulated perpetuals are available in every state including New York and contrasts that with Kraken. [secondary]
- Definitive check: open the futures application in the Coinbase app or Advanced web UI. If approved, confirm with a view-only key that `GET /api/v3/brokerage/cfm/balance_summary` returns a futures account.

### 2c. Contracts that exist now [live API, 2026-11-18 02:40 UTC]

101 futures products are listed on CDE: 29 perpetual-style and 72 dated. Of the 29, 24 are crypto. All 29 report `funding_interval = 3600s`, minimum order 1 contract, order increment 1 contract (whole contracts only).

Crypto perpetual-style contracts, sorted by 24h dollar volume:

| Product id | Contract size | Price | Notional per contract ($) | Tick (bps of price) | Intraday margin long/short | Overnight margin long/short | Cash for 1 contract intraday ($) | Cash for 1 contract overnight long/short ($) | Fee in bps per side IF a $0.15 minimum applies | 24h volume ($M) |
|---|---|---|---|---|---|---|---|---|---|---|
| BIP-20DEC30-CDE | 0.01 BTC | 64300 | 643 | 5 (0.8 bps) | 10% / 10% | 21% / 26% | 64 | 135 / 165 | 2.3 | 432.4 |
| ETP-20DEC30-CDE | 0.1 ETH | 1805 | 180 | 0.5 (2.8 bps) | 10% / 10% | 24% / 30% | 18 | 44 / 55 | 8.3 | 80.0 |
| ZEC-20DEC30-CDE | 1 ZEC | 955.7 | 956 | 0.05 (0.5 bps) | 25% / 25% | 54% / 98% | 239 | 513 / 939 | 1.6 | 39.3 |
| NER-20DEC30-CDE | 500 NEAR | 3.3688 | 1,684 | 0.0001 (0.3 bps) | 20% / 20% | 38% / 56% | 337 | 644 / 946 | 0.9 | 31.4 |
| XPP-20DEC30-CDE | 500 XRP | 0.9738 | 487 | 0.0001 (1.0 bps) | 20% / 20% | 37% / 57% | 97 | 182 / 276 | 3.1 | 25.6 |
| SLP-20DEC30-CDE | 5 SOL | 74.45 | 372 | 0.01 (1.3 bps) | 20% / 20% | 37% / 56% | 74 | 136 / 208 | 4.0 | 21.0 |
| PAU-20DEC30-CDE | 1 PAXG | 3791.1 | 3,791 | 0.1 (0.3 bps) | 5% / 5% | 8% / 8% | 189 | 290 / 309 | 0.4 | 9.3 |
| HYP-20DEC30-CDE | 10 HYPE | 68.73 | 687 | 0.01 (1.5 bps) | 20% / 20% | 37% / 55% | 137 | 257 / 377 | 2.2 | 5.9 |
| AVE-20DEC30-CDE | 5 AAVE | 111.41 | 557 | 0.01 (0.9 bps) | 25% / 25% | 43% / 67% | 139 | 240 / 374 | 2.7 | 4.3 |
| PEP-20DEC30-CDE | 100000 (1k PEPE) | 0.003791 | 379 | 0.000001 (2.6 bps) | 25% / 25% | 54% / 114% | 95 | 205 / 433 | 4.0 | 3.6 |
| XLP-20DEC30-CDE | 5000 XLM | 0.14035 | 702 | 0.00001 (0.7 bps) | 25% / 25% | 28% / 39% | 175 | 197 / 271 | 2.1 | 2.3 |
| ENA-20DEC30-CDE | 5000 ENA | 0.11432 | 572 | 0.00001 (0.9 bps) | 25% / 25% | 39% / 57% | 143 | 221 / 326 | 2.6 | 2.3 |
| SUP-20DEC30-CDE | 500 SUI | 0.7278 | 364 | 0.0001 (1.4 bps) | 25% / 25% | 39% / 57% | 91 | 141 / 206 | 4.1 | 2.3 |
| ADP-20DEC30-CDE | 1000 ADA | 0.1527 | 153 | 0.0001 (6.5 bps) | 20% / 20% | 28% / 42% | 31 | 43 / 64 | 9.8 | 2.1 |
| LNP-20DEC30-CDE | 50 LINK | 9.179 | 459 | 0.001 (1.1 bps) | 20% / 20% | 32% / 44% | 92 | 147 / 201 | 3.3 | 1.6 |
| OND-20DEC30-CDE | 1000 ONDO | 0.3067 | 307 | 0.0001 (3.3 bps) | 20% / 20% | 34% / 48% | 61 | 105 / 146 | 4.9 | 1.3 |
| AVP-20DEC30-CDE | 10 AVAX | 7.13 | 71 | 0.01 (14.0 bps) | 20% / 20% | 33% / 45% | 14 | 23 / 32 | 21.0 | 0.9 |
| HEP-20DEC30-CDE | 5000 HBAR | 0.05771 | 289 | 0.00001 (1.7 bps) | 25% / 25% | 39% / 61% | 72 | 113 / 176 | 5.2 | 0.9 |
| DOP-20DEC30-CDE | 5000 DOGE | 0.05934 | 297 | 0.00001 (1.7 bps) | 25% / 25% | 52% / 92% | 74 | 154 / 272 | 5.1 | 0.7 |
| LCP-20DEC30-CDE | 5 LTC | 44.51 | 223 | 0.01 (2.2 bps) | 25% / 25% | 37% / 53% | 56 | 82 / 118 | 6.7 | 0.5 |
| BNB-20DEC30-CDE | 1 BNB | 591.65 | 592 | 0.05 (0.8 bps) | 25% / 25% | 38% / 63% | 148 | 226 / 375 | 2.5 | 0.4 |
| BCP-20DEC30-CDE | 1 BCH | 208.7 | 209 | 0.05 (2.4 bps) | 25% / 25% | 42% / 65% | 52 | 88 / 135 | 7.2 | 0.3 |
| POP-20DEC30-CDE | 100 DOT | 0.732 | 73 | 0.001 (13.7 bps) | 20% / 20% | 73% / 107% | 15 | 54 / 79 | 20.5 | 0.2 |
| SHP-20DEC30-CDE | 10000 (1k SHIB) | 0.00384 | 38 | 0.00001 (26.0 bps) | 25% / 25% | 53% / 95% | 10 | 20 / 37 | 39.1 | 0.1 |

Notes on the table:

- Notional per contract = API `price` x `contract_size`. For PEP and SHP the API labels the group "1k PEPE" / "1k Shib"; I did not verify the quoting unit beyond that arithmetic.
- Margin rates are the API's `intraday_margin_rate` and `overnight_margin_rate` at the moment of the query. They are set by Coinbase and the clearinghouse and change.
- The fee column is a conditional illustration, not a confirmed fee (see section 3).
- Non-crypto perpetual-style contracts also exist on CDE: US500 (US5), Tech100 (TEK), AI index (AIP), Defense index (DEF), China index (CHN), each 1 index unit, 5% intraday margin, not 24x7.
- **Product ids may not be stable.** The API now reports `contract_expiry` of 2089-12-30 for most crypto perpetual-style contracts while the id still ends `-20DEC30` (PAU and PEP still show 2030-12-20). Code should discover contracts from the product list by `contract_code` and `funding_interval`, not hard-code ids.

Top-of-book spreads observed at 02:41 UTC [live API]: BIP 64300 / 64310 (1.6 bps), ETP 1803.5 / 1804.5 (5.5 bps), SLP 74.40 / 74.42 (2.7 bps), XPP 0.9738 / 0.9742 (4.1 bps). Single snapshot, quiet hours.

### 2d. Funding

- Interval: hourly (`funding_interval = 3600s`); the feed publishes `funding_rate` and `funding_time` per contract. BIP's last hourly rate was -0.000007 (-0.0007% per hour, roughly -6% annualised if it persisted). [live API]
- Formula per Coinbase's funding help page: hourly premium = time-weighted average of (futures minus spot) sampled every 3 minutes, divided by 24; published rate = 0.75 x current premium + 0.25 x previous hour's rate. No rate is published for an hour in which the market is closed. [primary, via search]
- **Settlement: funding accrues hourly but cash moves twice a day**, at the midday and end-of-day margin cycles, as clearinghouse cash adjustments. Example from Coinbase: 1 contract x 0.01 x $100,000 x 0.010% = $1.00. [primary, via search]
- A cap on the US funding rate: not found. The +/-5% cap in Coinbase documentation belongs to the international product. [unconfirmed]
- Exact clock times of the two daily margin cycles: not found. [unconfirmed]

### 2e. Margin and leverage

- Coinbase advertises up to 10x intraday on crypto perpetual-style futures. The live rates agree for BTC and ETH only (10% intraday). Every other crypto contract is 20-25% intraday, i.e. 4-5x. [live API]
- Overnight margin is much higher: BTC 21% long / 26% short (about 4.8x / 3.9x), ETH 24% / 30%, most alts 28-60%, several shorts 90%+ (PEPE short 114%, DOT short 107%, i.e. more than fully funded). [live API]
- Intraday leverage is **opt-in** and can be switched off by Coinbase without notice. Turning it off moves all positions to overnight rates immediately. [primary, via search]
- Intraday window hours conflict across Coinbase's own pages: 6 pm-4 pm ET (leverage help page), 6 pm-5 pm ET (perpetual-style overview), 8 am-4 pm ET weekdays (API docs for the margin-setting endpoint). All agree it does not apply on weekends or holidays. [primary, via search; conflicting]
- Rates ramp from intraday to overnight between 3:30 and 4:00 pm ET. Coinbase's own example shows a position at 82% margin ratio jumping to about 107% at 4:02 pm with no price move, which liquidates it. Liquidation triggers at a margin ratio of 100%, and open orders are cancelled. [primary, via search]
- Practical reading: any strategy that holds through 4 pm ET or over a weekend must be sized on overnight margin. Plan on roughly 4x for BTC, less for everything else.
- Position limits are tiered by the income and net worth attested in the account. Per-order maximum is 5000 contracts on BIP/ETP, 1000 on the rest. [primary, via search; live API]

### 2f. API access

- The **Advanced Trade API supports US derivatives (CFM)** at `https://api.coinbase.com/api/v3/brokerage`. Orders use the normal order endpoints with the futures `product_id`. Futures-specific endpoints: `cfm/balance_summary`, `cfm/positions`, `cfm/sweeps` (+ `/schedule`), `cfm/intraday/margin_setting` (GET and POST; values STANDARD / INTRADAY), `cfm/intraday/current_margin_window`. WebSocket has a `futures_balance_summary` channel. [primary, via search]
- Public market data for these contracts needs no key (verified by the calls above). [live API]
- A docs extract says INTX perpetuals left the Advanced Trade API on 1 October 2026 and US futures are unaffected. [primary, via search]
- US derivatives work only in the **default portfolio**, so the key must be scoped to it. Consequence: the futures key can also trade spot held in the default portfolio; futures cannot be isolated in a sub-portfolio. [primary, via search]

---

## 3. Fees for a small account

### Coinbase (CFM): not confirmed, sources conflict

| Source | What it says | Age |
|---|---|---|
| Coinbase blog "Perpetual futures have arrived in the U.S." | Fees "as low as 0.02% per contract", inclusive of exchange, clearing and NFA fees, with a **$0.15 minimum per contract** | July 2025 |
| Coinbase developer guide "Advanced Trade US Derivatives" | Same structure as Advanced Trade; 0.05% during an "introductory beta period" | Undated, looks old |
| Coinbase blog on the Advanced fee upgrade programme | 0.05% per contract per side, $0.20 minimum, liquidation fee 80 bps | About 2023-24 |
| Coinbase Derivatives exchange fee schedule, effective 26 Jan 2026 | Exchange-level per-contract fees by participant class (e.g. $0.10 electronic for nano Bitcoin, non-professional). This is the exchange component, not the retail all-in. The BIP row could not be read reliably | Jan 2026 |
| Third-party reviews | 0.04% / 0.06% maker/taker tiers, and other figures that disagree with each other | Various |

- I could not establish the current all-in retail rate, whether maker and taker differ, or whether volume tiers apply to futures.
- **If** the $0.15 per-contract minimum still applies, it dominates on small contracts, because every contract here is under $750 notional except ZEC, NEAR and PAXG. The table column shows the effect: about 2.3 bps per side on BIP, 8.3 bps on ETP, 20+ bps on AVAX, DOT and SHIB. Round trip on BIP would be roughly 4.7 bps in fees plus spread; on ETP roughly 17 bps plus spread. Under that assumption BIP is the only contract cheap enough for frequent trading.
- **How to get the real number before trading:**
  1. `GET /api/v3/brokerage/transaction_summary?product_type=FUTURE` with a view-only key returns the account's fee tier.
  2. `POST /api/v3/brokerage/orders/preview` for 1 contract returns the commission without placing an order.
  3. After a first 1-contract trade, read `commission` on the fill and the NFA line on the futures statement.
- Funding is a transfer between longs and shorts, not a Coinbase fee, per Coinbase's description.

### Kraken (for completeness; not available from New York)

- Offshore `PF_` perpetuals: 0.02% maker / 0.05% taker below $5M 30-day volume. [live API]
- US perpetuals via Kraken Derivatives US: flat per contract per side, $0.0113 or $0.15 depending on which extract of Kraken's fee page is current. [primary, via search; conflicting]

---

## 4. API key safety

### Coinbase (CDP API keys for Advanced Trade)

- Three permissions: **View, Trade, Transfer**. Transfer is what allows sending funds on or off platform. A key with View + Trade and no Transfer cannot withdraw. [primary, via search]
- Futures orders use the standard order endpoints, which need Trade. The CFM balance, position and sweep-list endpoints need View. **Scheduling or cancelling a sweep (moving excess cash from the futures account back to the USD spot wallet) needs Transfer.** So a trade-only key can trade futures but cannot pull cash back to spot; do that by hand in the UI. [primary, via search]
- Not confirmed: that order placement on a `-CDE` product is accepted with Trade alone (the docs extract did not show the per-endpoint scope for futures orders), and how cash gets from spot USD into the futures account for margin without a Transfer-scoped call. Test with `orders/preview` and a 1-contract order.
- **IP allow-listing is supported** (IPv4 and IPv6, single addresses or CIDR), optional, recommended by Coinbase. [primary, via search]
- Keys are scoped to a portfolio; futures need the default portfolio (see 2f). Signature algorithm: ECDSA is the safe choice for Advanced Trade; one Coinbase page says Ed25519 is not supported by the Coinbase App SDK. [primary, via search]
- `GET /api/v3/brokerage/key_permissions` reports what a key can do; call it at startup and refuse to run if `can_transfer` is true.

### Kraken (documented for completeness)

- Spot keys: granular permissions (Query Funds, Deposit, Withdraw Funds, query / create / cancel orders, and others). A key without Withdraw Funds cannot withdraw. IP whitelisting per key is supported and recommended. Kraken warns against combining "Add Withdrawal Addresses" with "Withdraw Funds" on one key. [primary, via search]
- Futures (futures.kraken.com) keys are separate from spot keys, with two settings: General API = No Access / Read Only / Full Access (excludes withdrawals), and Withdrawal API = No Access / Full Access. A trading key is General = Full Access, Withdrawal = No Access. [primary docs plus third-party guides, via search]
- IP whitelisting on futures keys specifically, and the key model for Kraken Derivatives US perpetuals: unconfirmed.

---

## 5. Recommendation

1. Drop Kraken from the plan. It does not serve New York residents, and its offshore `PF_` perpetuals are closed to all US residents. Do not attempt access by VPN or a non-New York address: that breaches the terms and risks frozen funds and forced liquidation.
2. Before building anything venue-specific, apply for futures on the existing Coinbase account from the real New York address. Approval or refusal there is the eligibility answer; nothing found online settles it.
3. If approved, create a CDP key with View + Trade only, default portfolio, IP allow-list set to the bot's fixed address. Verify with `key_permissions`.
4. Read the true fee from `transaction_summary` and `orders/preview`, then re-check any strategy's edge against it. With whole-contract sizing and a possible $0.15 per-contract minimum, BIP is the natural first contract; ETP costs several times more per dollar traded.
5. Design for the venue's real constraints: whole contracts only (about $643 per BIP, $180 per ETP at current prices), hourly funding accrual with twice-daily cash settlement, 10x only intraday and only on BTC/ETH, roughly 4x if a position is held through 4 pm ET or a weekend, and the 3:30-4:00 pm ET margin ramp that can liquidate an unchanged position.

---

## What I could not confirm

- Whether Coinbase Financial Markets accepts New York residents for futures.
- The current Coinbase retail futures fee: rate, per-contract minimum, maker/taker split, volume tiers.
- Whether a Trade-only Coinbase key is sufficient for futures orders, and how margin cash moves from spot to the futures account without Transfer.
- The current intraday margin window hours (three Coinbase pages give three answers) and the clock times of the two daily funding settlement cycles.
- Whether the US funding rate has a cap.
- Kraken's perps-specific US state list (the New York conclusion rests on Kraken's general "no New York residents" statement).
- Kraken US perpetuals: current per-contract fee, contract specifications, funding timestamps, and whether any API reaches them.
- IP allow-listing on Kraken Futures keys.
- NYDFS licensee status for either firm from NYDFS itself, and CFM's registration from CFTC/NFA records (both sites unreachable from this session).
- Whether US retail can yet reach Deribit-listed global perpetuals through Coinbase.

## Sources

Reached directly:

- Coinbase Advanced Trade public products API: https://api.coinbase.com/api/v3/brokerage/market/products?product_type=FUTURE (queried 2026-11-18 02:40 UTC)
- Coinbase Advanced Trade public order book API: https://api.coinbase.com/api/v3/brokerage/market/product_book (queried 2026-11-18 02:41 UTC)
- Kraken Futures instruments and fee schedules API: https://futures.kraken.com/derivatives/api/v3/instruments and https://futures.kraken.com/derivatives/api/v3/feeschedules (queried 2026-11-18 02:41 UTC)

Seen only as web-search extracts:

- Kraken, Where is Kraken licensed or regulated?: https://support.kraken.com/articles/where-is-kraken-licensed-or-regulated
- Kraken, Quick start for clients in the United States: https://support.kraken.com/articles/quick-start-for-clients-in-the-united-states
- Kraken, Kraken Derivatives eligibility requirements: https://support.kraken.com/articles/360023786632-kraken-derivatives-eligibility
- Kraken, Trade crypto perpetual futures on Kraken Pro: https://www.kraken.com/features/futures
- Kraken blog, Announcing CFTC-regulated perpetual futures for US traders: https://blog.kraken.com/product/kraken-derivatives/announcing-cftc-regulated-us-perps
- Kraken, US Futures Fees on Kraken Pro: https://support.kraken.com/articles/us-futures-fees
- Kraken, US Perpetual Futures: https://support.kraken.com/articles/us-perpetual-futures
- Kraken, Contract Specifications: https://support.kraken.com/articles/contract-specifications
- Kraken developers, API key permissions: https://docs.kraken.com/exchange/guides/rest/api-keys
- Kraken developers, Derivatives introduction: https://docs.kraken.com/api/docs/guides/futures-introduction/
- Business Wire, Kraken Launches Perpetual Futures for US Clients (2026-06-15): https://www.businesswire.com/news/home/20260615010932/en/Kraken-Launches-Perpetual-Futures-for-US-Clients
- Bitnomial CFTC product filing 26-036: https://bitnomial.com/exchange/regulatory/cftc/product-filings/26-036.pdf
- Coinbase blog, Perpetual futures have arrived in the U.S. (July 2025): https://www.coinbase.com/blog/perpetual-futures-have-arrived-in-the-us
- Coinbase help, US perpetual-style futures overview: https://help.coinbase.com/en/coinbase/derivatives/us-perpetual-futures-overview
- Coinbase help, US Perpetual-Style Futures Contract Specifications: https://help.coinbase.com/en/derivatives/perpetual-style-futures/contract-specifications
- Coinbase help, US Perpetual-Style Futures Funding Rate Mechanism: https://help.coinbase.com/en/derivatives/perpetual-style-futures/funding-rate
- Coinbase help, US Perpetual-Style Futures Market Access: https://help.coinbase.com/en/derivatives/perpetual-style-futures/market-access
- Coinbase help, Leverage and margin rates (Futures): https://help.coinbase.com/coinbase/trading-and-funding/derivatives/futures-leverage-margin
- Coinbase help, Margin ratio and liquidation risk management (US Derivatives): https://help.coinbase.com/en/coinbase/derivatives/us-derivatives-risk-management-and-liquidations
- Coinbase help, Get started with US Derivatives: https://help.coinbase.com/en/coinbase/trading-and-funding/derivatives/futures-intro
- Coinbase developers, Advanced Trade US Derivatives guide: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/futures
- Coinbase developers, Advanced Trade REST endpoints: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/rest-api
- Coinbase developers, Set Intraday Margin Setting: https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/set-intraday-margin-settings
- Coinbase developers, API security best practices: https://docs.cdp.coinbase.com/get-started/authentication/security-best-practices
- Coinbase developers, Coinbase for Agents overview (default-portfolio note): https://docs.cdp.coinbase.com/coinbase-for-agents/overview
- Coinbase Derivatives Fee Schedule effective 2026-01-26: https://assets.ctfassets.net/k3n74unfin40/sgInuF26edJX4v4nUlE29/87f18103cd35feede93f0bb92a5f1065/Fee_Schedule_1.26.2026.pdf
- Coinbase blog, fee upgrade programme for high volume traders: https://www.coinbase.com/blog/coinbase-advanced-now-offers-a-fee-upgrade-program-for-high-volume-traders
- Datawallet, Best Regulated Perpetual Exchanges in the USA (2026) (third-party; source of the "every state including New York" claim): https://www.datawallet.com/crypto/best-regulated-perpetual-exchanges-usa
- Cointelegraph, Coinbase / Deribit US derivatives access: https://cointelegraph.com/news/coinbase-deribit-us-crypto-options-perpetual-futures
