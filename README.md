# fly-smart

> **Find cheaper flight routes using hidden-city arbitrage and hub transfer combinations.**

`fly-smart` is a Hermes Agent skill that finds cheaper ways to fly by combining two one-way tickets through a strategic hub — exploiting pricing differences between airlines and routes that Google Flights doesn't always surface directly.

**No API keys. No browser. Just smarter flying.**

---

## How It Works

When you search for a direct flight, airlines price routes based on demand, competition, and hub strength — not just distance. This creates **pricing arbitrage**: a flight from A → B → C can sometimes cost less than A → C direct.

`fly-smart` scans 70+ global hubs, finds these combos, and shows you exactly how much you'd save — with a full price calendar across multiple dates and departure airports.

---

## What It Finds

```
┌─────────────────────────────────────────────────────────────┐
│  ✈️ MULTI-ORIGIN × MULTI-DATE  |  LAX / SFO / OAK → HKG    │
│                         May 17–23, 2026                     │
├─────────────────────────────────────────────────────────────┤
│  [ 1]  LAX → SEA → HKG   May 18   $588   Save $140 (19%)  │
│  [ 2]  SFO → SEA → HKG   May 18   $588   Save $82  (12%)  │
│  [ 3]  SAN → SEA → HKG   May 18   $598   Save $151 (20%)  │
│  [ 4]  LAX → TPE → HKG   May 19   $649   Save $85  (12%)  │
│  [ 5]  OAK → SEA → HKG   May 17   $677   Save $174 (20%)  │
└─────────────────────────────────────────────────────────────┘
```

**Real examples from May 2026:**

| Route | Transfer | Savings |
|-------|----------|---------|
| LAX → HKG | via Seattle (SEA) | **$140 saved (19%)** |
| IAD → HKG | via Taipei (TPE) | **$103 saved (11%)** |
| DCA → HKG | via San Diego (SAN) | **$86 saved (8%)** |
| OAK → HKG | via Taipei (TPE) | **$255 saved (24%)** |

---

## Features

- **70+ global hubs** — Northeast Asia, Greater China, Southeast Asia, Middle East, Europe, US coasts
- **Multi-date scanning** — scan ±7 days in parallel, see a full price calendar
- **Multi-origin scanning** — compare LAX, SFO, SAN, SJC, OAK simultaneously
- **SQLite cache** — 1-hour TTL, avoids redundant Google Flights calls
- **Self-transfer rules** — carry-on only, 3h+ buffer, transit visa checks
- **Persistent history** — saves winning finds to `~/.hermes/data/flight-searches.jsonl`

---

## Installation

```bash
# 1. Clone this repo into your Hermes skills directory
git clone https://github.com/wali-reheman/skills.git ~/.hermes/skills/repos/wali-reheman

# 2. Set up the Python environment (venv required — PEP 668 restriction)
python3 -m venv ~/.hermes/venvs/flight-search
~/.hermes/venvs/flight-search/bin/pip install flight-search
```

---

## Usage

```bash
# Single date
python3 ~/.hermes/scripts/flight-transfer-finder.py -o SFO -d HKG -dt 2026-05-20

# Multi-date: scan ±3 days (7 dates in parallel)
python3 ~/.hermes/scripts/flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --flexible 3

# Multi-origin: compare LAX, SFO, SAN, SJC, OAK at once
python3 ~/.hermes/scripts/flight-transfer-finder.py -o SFO,LAX,SAN,SJC,OAK -d HKG -dt 2026-05-20 --flexible 3

# Full power: ±7 days, 60 hubs, save history, 10-minute timeout
python3 ~/.hermes/scripts/flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 \
  --flexible 7 --aggressive --save-route --timeout 600
```

### Arguments

| Argument | Description |
|----------|-------------|
| `-o` | Origin IATA(s), comma-separated |
| `-d` | Destination IATA |
| `-dt` | Reference departure date (YYYY-MM-DD) |
| `--flexible N` | Scan ±N days around --dt |
| `--date-range START:END` | Explicit YYYY-MM-DD:YYYY-MM-DD range |
| `--aggressive` | Check 60 hubs (default: 25) |
| `--all-hubs` | Check all 70+ hubs |
| `--max-workers N` | Concurrent threads (8 is optimal) |
| `--no-cache` | Bypass cache |
| `--save-route` | Append results to history file |
| `--alert-below PRICE` | Alert if best transfer < threshold |
| `--timeout N` | Overall timeout in seconds |
| `--json` | Raw JSON output |

---

## Self-Transfer Rules

> ⚠️ **Important.** These deals require booking two separate one-way tickets.

- ✅ Book **two separate one-way tickets** — not as a round-trip
- ✅ **Carry-on only** — no checked bags (they won't transfer between tickets)
- ✅ **3+ hour buffer** between connecting legs — missed connection = forfeit second leg
- ✅ Check **transit visa** requirements for the hub country

---

## Performance

| Scan | v3 (subprocess) | v4 (library) |
|------|----------------|---------------|
| DC × 3 origins × 7 dates | 214s | **66s** |
| CA × 5 origins × 7 dates | timeout | **118s** |

---

## Why Python + httpx, Not Rust?

The bottleneck is **network I/O** — waiting for Google's servers to respond. Rust would not make HTTP faster. Python's async `httpx` layer already saturates the network pipe efficiently.

Key optimizations in v4:
- **Direct library calls** (zero subprocess overhead)
- **Per-route semaphore** — prevents thundering-herd where 8 threads all hit the same URL and trigger rate limiting
- **8 threads** (not 16) — `httpx` connection pool exhausts at ~16 concurrent requests

---

## Repository Structure

```
fly-smart/
├── SKILL.md              ← Skill definition (YAML frontmatter + instructions)
└── references/
    └── flight-transfer-finder.py   ← The v4 transfer finder script
```

---

## Related Skills

| Skill | Description |
|-------|-------------|
| `find-nearby` | Find nearby places — restaurants, cafes, bars, pharmacies |

---



## License

MIT — see [LICENSE](./LICENSE)
