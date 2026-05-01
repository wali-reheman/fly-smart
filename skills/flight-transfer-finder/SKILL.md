---
name: flight-transfer-finder
description: "Find cheaper self-transfer flight routes by checking 70+ hub airports. Scans direct vs. transfer prices and reports savings opportunities."
version: 1.0.0
author: Wali Reheman
license: MIT
metadata:
  hermes:
    tags: [flights, travel, finance, scraping]
    platforms: [macos, linux]
    requires_toolsets: [terminal]
---

# Flight Transfer Finder

Find cheaper flight routes by checking if transferring through a hub airport beats the direct price. Useful for transpacific, transatlantic, and long-haul routes where hub airlines charge a premium.

## Setup

The script requires Python 3 and the `fast-flights` package. Create a dedicated venv:

```bash
python3 -m venv ~/.hermes/venvs/flight-search
~/.hermes/venvs/flight-search/bin/pip install fast-flights
```

The script goes at `~/.hermes/scripts/flight-transfer-finder.py`. Full source is in the [fly-smart repo](https://github.com/wali-reheman/fly-smart).

## Usage

```bash
# Single route — find transfer savings
python3 ~/.hermes/scripts/flight-transfer-finder.py -o SFO -d HKG -dt 2026-06-15

# Flexible dates (±3 days = 7 dates scanned)
python3 ~/.hermes/scripts/flight-transfer-finder.py -o LAX -d HKG -dt 2026-06-15 --flexible 3

# Multi-origin search (find cheapest departure city)
python3 ~/.hermes/scripts/flight-transfer-finder.py -o SFO,LAX,OAK -d HKG -dt 2026-06-15 --flexible 3

# Business class, 3 passengers
python3 ~/.hermes/scripts/flight-transfer-finder.py -o JFK -d DXB -dt 2026-07-01 -c business -p 3

# Aggressive (60 hubs, more thorough)
python3 ~/.hermes/scripts/flight-transfer-finder.py -o LAX -d HKG -dt 2026-06-15 --aggressive

# Direct price only (fast, no transfer search)
python3 ~/.hermes/scripts/flight-transfer-finder.py -o SFO -d HKG -dt 2026-06-15 --direct-only

# Alert if savings exceed threshold
python3 ~/.hermes/scripts/flight-transfer-finder.py -o SFO -d HKG -dt 2026-06-15 --alert-below 800
```

## How It Works

1. **Direct price** — fetches the direct (non-stop) price for the route using `fast-flights`
2. **Hub scan** — concurrently checks 25-60 hub airports for transfer leg prices
3. **Savings calc** — compares `leg1 + leg2` vs. direct price
4. **Reports** — shows all hubs sorted by total price, highlights savings

## Key Options

| Flag | Description |
|------|-------------|
| `-o` | Origin IATA (comma-separated for multi-origin) |
| `-d` | Destination IATA |
| `-dt` | Departure date (YYYY-MM-DD) |
| `-c` | Cabin class: economy, premium-economy, business, first |
| `-p` | Number of passengers |
| `--flexible N` | Scan ±N days around the date |
| `--date-range START:END` | Explicit date range |
| `--aggressive` | Check 60 hubs instead of 25 |
| `--direct-only` | Skip hub scan, show direct price only |
| `--alert-below PRICE` | Print alert if best transfer is below this price |
| `--no-cache` | Bypass 1-hour price cache |
| `--json` | Raw JSON output |

## Limitations

- **Self-transfer risk**: Two separate bookings = two separate tickets. Luggage, delays, and missed connections are your problem.
- **Carry-on only**: Budget airlines may charge for checked bags on each leg.
- **Transit visa**: Check if you need a visa for the hub country.
- **3-hour buffer**: Always leave 3+ hours between legs for self-transfers.
- **Cache TTL**: Prices cached for 1 hour to avoid redundant API calls.
- **No loyalty programs**: This finds cheapest cash fares, not award tickets.

## Uninstall

```bash
rm -rf ~/.hermes/venvs/flight-search
rm -rf ~/.hermes/cache/flights
```
