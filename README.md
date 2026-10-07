# SafeTrade Radar

An independent, unofficial dashboard for every market on the SafeTrade exchange, built on data pulled
straight from its public API: daily and hourly candles back to the listing day, order-book depth,
trade flow (buys vs sells) and newly created markets.

The interface is available in English, German, French, Russian, Chinese and Spanish.

## What is in the repo

| File | Role |
|---|---|
| `collect.py` | Collector. Plain Python 3, no packages to install. Writes everything to `data/`. |
| `index.html` | The site. Reads `data/data.js`; works from disk (double-click) and on GitHub Pages. |
| `i18n.js` | Interface translations. English is the source; add a language by adding one block. |
| `.github/workflows/collect.yml` | GitHub Actions job: collects every 2 hours and stores data on the `data` branch. |
| `mac/run.command` | macOS double-click: collect, then open the site. |
| `mac/install-auto.sh` | Optional: collect in the background every 30 minutes while the Mac is on. |

## Quick start

```
python3 collect.py
open index.html        # macOS; on other systems open the file in a browser
```

The first run downloads the full history of every market and takes a few minutes. Later runs are fast.

## Views

- **Markets**: signal lists (new markets, volume spikes, breakouts, tight bases, buy pressure, strong bids)
  and a sortable table of every market. Click a row for candles, order-book history and buy/sell flow.
- **Phase charts**: one card per market with the daily chart, the accumulation base, the breakout
  and the current phase (breakout, uptrend, accumulation, consolidation, correction, new listing).

## Data

- Endpoints under `https://safetrade.com/api/v2/trade/public`: `/markets`, `/tickers`,
  `/markets/{id}/k-line`, `/markets/{id}/depth`, `/markets/{id}/trades`. No API key is required.
- `data/daily`, `data/hourly`: candles `[time, open, high, low, close, volume]`.
- `data/flow`: buys and sells in USD per hour. `data/snap`: order-book snapshots (spread, capital within 2% and 10%).
- `data/events.json`: new markets and state changes detected between runs.
- `data/summary.json`: everything the site shows, as plain JSON.

## Phase rules

A base is the longest window around the period low in which the high/low ratio stays within 2.5x.
A close above the base is a breakout. After a breakout: within 10% of the peak is breakout or uptrend,
within 25% is consolidation, deeper is correction, back inside the base range is accumulation.

## Publishing

`data/` is not committed to `main`; the workflow keeps it on a separate `data` branch.
To publish with GitHub Pages, set the repository variable `PUBLISH_PAGES=true`
(Settings → Secrets and variables → Actions → Variables) and choose Settings → Pages → Source: GitHub Actions.
Never put an API key in any file in this repository.

## When SafeTrade refuses the connection (HTTP 403)

SafeTrade sits behind Cloudflare, which rejects traffic from many data centers. If the GitHub Actions job
ends with `BLOCKED`, run the collector on a home machine instead (`mac/run.command` or `mac/install-auto.sh`).

## Disclaimer

Not affiliated with SafeTrade. Research material, not investment advice.
