# fly-smart

> **Find cheaper flights using hidden-city arbitrage** — no API key, no browser, just smarter routing across 70+ global hubs.

[![Health](https://img.shields.io/badge/community%20health-100%25-brightgreen)](https://github.com/wali-reheman/fly-smart/community)
[![MIT License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/wali-reheman/fly-smart/blob/main/LICENSE)
[![Topics](https://img.shields.io/badge/topics-flights%20%7C%20travel%20%7C%20budget--travel-blue)](https://github.com/topics/flights)

---

## Demo

![fly-smart terminal demo](docs/demo.svg)

*Scanning 7 dates × 25 hubs in 66 seconds — finding routes Google Flights doesn't show directly.*

---

## How It Works

When you search for a direct flight, airlines price routes based on demand, competition,
and hub strength — not just distance. This creates **pricing arbitrage**: a flight from
A → B → C can sometimes cost less than A → C direct.

`fly-smart` scans 70+ global hubs, finds these combos, and shows you exactly how much
you'd save — with a full price calendar across multiple dates and departure airports.

---

## What It Finds

```
┌─────────────────────────────────────────────────────────────┐
│  ✈ MULTI-ORIGIN × MULTI-DATE  |  LAX / SFO / OAK → HKG    │
│                         Jun 15–21, 2026                     │
├─────────────────────────────────────────────────────────────┤
│  [ 1]  LAX → SEA → HKG   Jun 16   $588   Save $140 (19%)  │
│  [ 2]  SFO → SEA → HKG   Jun 16   $588   Save $82  (12%)  │
│  [ 3]  SAN → SEA → HKG   Jun 16   $598   Save $151 (20%)  │
│  [ 4]  LAX → TPE → HKG   Jun 17   $649   Save $85  (12%)  │
│  [ 5]  OAK → TPE → HKG   Jun 17   $677   Save $174 (20%)  │
└─────────────────────────────────────────────────────────────┘
```

**Real savings (May 2026):**

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

### Option 1: As a Hermes Agent skill (recommended)

```bash
# Clone into your Hermes skills directory
git clone https://github.com/wali-reheman/fly-smart.git \
  ~/.hermes/skills/repos/wali-reheman/fly-smart

# Set up Python environment (venv required — PEP 668 restriction)
python3 -m venv ~/.hermes/venvs/flight-search
~/.hermes/venvs/flight-search/bin/pip install fast-flights
```

Then ask Hermes: **"search flights from LAX to HKG on June 15"**

---

### Option 2: Standalone CLI

```bash
# Clone the repo
git clone https://github.com/wali-reheman/fly-smart.git
cd fly-smart

# Set up venv
python3 -m venv ~/.hermes/venvs/fly-smart
source ~/.hermes/venvs/fly-smart/bin/activate
pip install fast-flights

# Run directly
python3 fly-smart/references/flight-transfer-finder.py \
  -o LAX -d HKG -dt 2026-06-15 --flexible 3
```

---

## Usage

```bash
# Single date — fast (direct price only)
python3 ~/.hermes/scripts/flight-transfer-finder.py \
  -o LAX -d HKG -dt 2026-06-15 --direct-only

# Multi-date: scan ±3 days (7 dates in parallel)
python3 ~/.hermes/scripts/flight-transfer-finder.py \
  -o LAX -d HKG -dt 2026-06-15 --flexible 3

# Multi-origin: compare LAX, SFO, SAN, SJC, OAK at once
python3 ~/.hermes/scripts/flight-transfer-finder.py \
  -o SFO,LAX,SAN,SJC,OAK -d HKG -dt 2026-06-15 --flexible 3

# Full power: ±7 days, 60 hubs, save history, 10-minute timeout
python3 ~/.hermes/scripts/flight-transfer-finder.py \
  -o LAX -d HKG -dt 2026-06-15 \
  --flexible 7 --aggressive --save-route --timeout 600

# Alert if any route drops below $600
python3 ~/.hermes/scripts/flight-transfer-finder.py \
  -o LAX -d HKG -dt 2026-06-15 --flexible 7 --alert-below 600
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `-o` | Origin IATA(s), comma-separated | required |
| `-d` | Destination IATA | required |
| `-dt` | Reference departure date (YYYY-MM-DD) | required |
| `-c` | Cabin class: economy, premium-economy, business, first | economy |
| `-p` | Number of passengers (adults) | 1 |
| `--flexible N` | Scan ±N days around --dt | off |
| `--date-range START:END` | Explicit YYYY-MM-DD:YYYY-MM-DD range | off |
| `--aggressive` | Check 60 hubs (default: 25) | off |
| `--all-hubs` | Check all 70+ hubs | off |
| `--direct-only` | Skip hub transfer search — show direct price only | off |
| `--max-workers N` | Concurrent threads (8 is optimal) | 8 |
| `--no-cache` | Bypass cache — force fresh Google Flights data | cache on |
| `--save-route` | Append winning finds to history file | off |
| `--alert-below PRICE` | Only report if best transfer < PRICE | off |
| `--timeout N` | Overall timeout in seconds | 600 |
| `--json` | Raw JSON output | off |

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

## Repository Structure

```
fly-smart/
├── SKILL.md                          # Skill definition (Hermes Agent format)
├── docs/
│   └── demo.svg                      # Demo visualization
├── fly-smart/
│   ├── SKILL.md                      # Skill definition (YAML frontmatter + docs)
│   └── references/
│       └── flight-transfer-finder.py # Core script
├── .github/
│   ├── workflows/
│   │   └── ci.yml                   # Lint + smoke test
│   ├── ISSUE_TEMPLATE/              # Bug report + feature request
│   └── PULL_REQUEST_TEMPLATE.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── README.md
└── LICENSE
```

---

## Contributing

PRs welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and style guide.

---

## License

MIT — see [LICENSE](LICENSE)
