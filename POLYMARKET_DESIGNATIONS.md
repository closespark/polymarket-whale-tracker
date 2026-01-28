# Polymarket API: Market Designations & resolution (from docs)

Polymarket does **not** document a dedicated "timeframe" or "designation" field (e.g. 15min / hourly / daily / monthly) for crypto resolution windows. The official Gamma schema and fetch guides do not define values for that.

## Crypto market URL paths (UI)

These match the “designation” filters on [Polymarket Crypto](https://polymarket.com/crypto):

| Path | Meaning |
|------|---------|
| [polymarket.com/crypto/15M](https://polymarket.com/crypto/15M) | 15‑minute (e.g. “8:00PM–8:15PM ET”) |
| [polymarket.com/crypto/hourly](https://polymarket.com/crypto/hourly) | Hourly (e.g. “January 27, 8PM ET”) |
| [polymarket.com/crypto/4hour](https://polymarket.com/crypto/4hour) | 4‑hour (e.g. “8:00PM–12:00AM ET”) |
| [polymarket.com/crypto/daily](https://polymarket.com/crypto/daily) | Daily (e.g. “Up or Down on January 28?”) |

## What `outcomePrices` 1/0 means (Gamma)

In the Gamma market object, **`outcomePrices`** is a stringified array (e.g. `'["1","0"]'` or `'["0","1"]'`) with the **same length and index order** as `outcomes` and `clobTokenIds`:

- **Index `i`** = post‑resolution price for **`outcomes[i]`** / **`clobTokenIds[i]`**.
- **`"1"`** = that outcome won (token is redeemable for $1).
- **`"0"`** = that outcome lost.

So for binary Up/Down: `outcomePrices[0] === "1"` ⇒ first outcome (e.g. “Up”) won; `outcomePrices[1] === "1"` ⇒ second outcome (e.g. “Down”) won. Use this when Gamma does not populate `outcome` / `resolution` / `winning_outcome`. See [Get Markets](https://docs.polymarket.com/developers/gamma-markets-api/get-markets) response schema.

## Other Polymarket endpoints (summary)

| API | Base URL | Purpose |
|-----|----------|---------|
| **Gamma** | `https://gamma-api.polymarket.com` | Market discovery, metadata, events. **GET /markets** (incl. `clob_token_ids`) is the main source for question, outcomes, outcomePrices, events/series. No separate “resolution” route. |
| **CLOB** | `https://clob.polymarket.com` | Order book, prices, orders. **GET /price**, **GET /prices**, **GET /book**, **GET /midpoint** return **trading** bid/ask/mid, not resolution outcome. |
| **Data API** | `https://data-api.polymarket.com` | User-centric: **GET /positions**, **GET /activity**, **GET /trades**. Positions include `outcome`, `curPrice`, `redeemable` per position; useful per user, not for bulk “all resolved markets”. |

Resolution itself is done on-chain via [UMA Optimistic Oracle](https://docs.polymarket.com/developers/resolution/UMA); for API consumers, **Gamma’s market `outcomePrices` (and optionally `umaResolutionStatus`)** are the resolution source when the market is closed.

---

## What Gamma *does* expose (from [Get Markets](https://docs.polymarket.com/developers/gamma-markets-api/get-markets))

| Field        | Type    | Doc description / use |
|-------------|---------|------------------------|
| **category** | string \| null | Market category (e.g. Crypto, Sports, Politics). No enum of values is documented. |
| **marketType** | string \| null | Generic market type. Schema shows type only, not allowed values. |
| **formatType** | string \| null | Format/style of the market. No enum documented. |
| **tags**      | (on events) | Array of tag objects (id, label, slug). Used to "filter by category, sport, or topic" ([Fetch by Tags](https://docs.polymarket.com/developers/gamma-markets-api/fetch-markets-guide)). |
| **groupItemTitle** | string \| null | Grouping title. |
| **marketGroup**    | number \| null | Group id. |

Tags are the closest thing to "designations": [GET /tags](https://docs.polymarket.com/api-reference/tags/list-tags) returns `id`, `label`, `slug`. Markets can be filtered with `tag_id`. The docs do **not** list tag labels (e.g. whether "15 Min Crypto" or "Hourly Crypto" exist as tag labels).

For **sports**, Polymarket documents an explicit designation: [sportsMarketType / sportsMarketTypeV2](https://docs.polymarket.com/api-reference/sports/get-valid-sports-market-types) with values **MONEYLINE**, **SPREAD**, **TOTAL**, **PROP**. There is no analogous documented type for crypto resolution windows.

## Practical takeaway

- **category**, **marketType**, **formatType**, and **tags** may already encode UI sections like "15 Min Crypto" / "Hourly Crypto" in their backend; the public docs do not specify that.
- To rely on "designations" you can:  
  1. Inspect live Gamma responses for a few 15min/hourly/daily markets and see what `category`, `marketType`, `formatType`, or `tags[].label` contain, or  
  2. Call [GET /tags](https://gamma-api.polymarket.com/tags) and see if any tag labels correspond to 15min / hourly / 4hr / daily / monthly.

Until then, inferring from **question** text (e.g. "15 minute", "8:00PM-8:15PM ET", "on January 28", "in January") remains the only doc-based way to get resolution-timeframe designations.
