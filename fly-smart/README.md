# fly-smart

> **Find cheaper flight routes using hidden-city arbitrage and hub transfer combinations.**

`fly-smart` is a Hermes Agent skill that finds cheaper ways to fly by combining two one-way tickets through a strategic hub — exploiting pricing differences between airlines and routes that Google Flights doesn't always surface directly.

**No API keys. No browser. Just smarter flying.**

---

## How It Works

When you search for a direct flight, airlines price routes based on demand, competition, and hub strength — not just distance. This creates **pricing arbitrage**: a flight from A → B → C can sometimes cost less than A → C direct.

`fly-smart` scans 70+ global hubs, finds these combos, and shows you exactly how much you'd save — with a full price calendar across multiple dates and departure airports.

---

## Features

- **70+ global hubs** — Northeast Asia, Greater China, Southeast Asia, Middle East, Europe, US coasts
- **Multi-date scanning** — scan ±7 days in parallel, see a full price calendar
- **Multi-origin scanning** — compare LAX, SFO, SAN, SJC, OAK simultaneously
- **SQLite cache** — 1-hour TTL, avoids redundant Google Flights calls
- **Self-transfer rules** — carry-on only, 3h+ buffer, transit visa checks
- **Persistent history** — saves winning finds to `~/.hermes/data/flight-searches.jsonl`

---

## Quick Start

```bash
# Set up the Python environment (one-time)
python3 -m venv ~/.hermes/venvs/flight-search
~/.hermes/venvs/flight-search/bin/pip install flight-search

# Single date
python3 ~/.hermes/scripts/flight-transfer-finder.py -o SFO -d HKG -dt 2026-05-20

# Multi-date ±3 days
python3 ~/.hermes/scripts/flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --flexible 3

# Multi-origin (5 California airports × 7 dates in parallel)
python3 ~/.hermes/scripts/flight-transfer-finder.py -o SFO,LAX,SAN,SJC,OAK -d HKG -dt 2026-05-20 --flexible 3
```

---

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `-o` | Origin IATA(s), comma-separated | required |
| `-d` | Destination IATA | required |
| `-dt` | Reference departure date | required |
| `--flexible N` | Scan ±N days around --dt | off |
| `--date-range START:END` | Explicit YYYY-MM-DD:YYYY-MM-DD range | off |
| `--aggressive` | Check 60 hubs (default: 25) | off |
| `--all-hubs` | Check all 70+ hubs | off |
| `--max-workers N` | Concurrent threads | 8 |
| `--no-cache` | Bypass cache | cache on |
| `--save-route` | Append results to history | off |
| `--alert-below PRICE` | Alert if best transfer < threshold | off |
| `--timeout N` | Overall timeout in seconds | 600 |
| `--json` | Raw JSON output | off |

---

## Self-Transfer Rules

> ⚠️ **Important.** These deals require booking two separate one-way tickets.

- ✅ Book **two separate one-way tickets** — not as a round-trip
- ✅ **Carry-on only** — no checked bags (they won't transfer between tickets)
- ✅ **3+ hour buffer** between connecting legs
- ✅ Check **transit visa** requirements for the hub country

---

## Performance

| Scan | v3 (subprocess) | v4 (library + semaphore) |
|------|----------------|--------------------------|
| 3 origins × 7 dates | 214s | **66s** |
| 5 origins × 7 dates | timeout | **118s** |

---

## License

MIT
