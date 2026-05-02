#!/usr/bin/env python3
"""
fly-smart CLI entry point.
Provides:  fly-smart search LAX HKG 2026-06-15
           fly-smart deals LAX HKG 2026-06-15 --flexible 3
           fly-smart alert LAX HKG 2026-06-15 --threshold 600
           fly-smart verify LAX HKG 2026-06-15
           fly-smart export LAX HKG 2026-06-15 --format csv
           fly-smart --help

Translates CLI subcommands into the underlying flight-transfer-finder.py arguments.
"""

import argparse
import subprocess
import sys
from pathlib import Path

# The canonical script lives in the skill directory
SCRIPT_PATH = Path(__file__).parent / "references" / "flight_transfer_finder.py"
if not SCRIPT_PATH.exists():
    # Fallback: try the Hermes scripts directory
    SCRIPT_PATH = Path.home() / ".hermes" / "scripts" / "flight-transfer-finder.py"

HELP_EPILOG = """
Commands:
  search, find  Search for transfer deals between two airports
  alert        Run with price alert mode (exit 0 if below threshold, 1 if above)
  verify       Run with self-transfer rule verification
  export       Run with CSV export enabled

Examples:
  fly-smart search LAX HKG 2026-06-15 --flexible 3
  fly-smart alert LAX HKG 2026-06-15 --threshold 600
  fly-smart verify LAX HKG 2026-06-15
  fly-smart export LAX HKG 2026-06-15 --format csv
"""


def main():
    if len(sys.argv) < 2:
        # No subcommand — print help
        subprocess.run([sys.executable, str(SCRIPT_PATH), "--help"])
        print("\nCLI shortcuts (alternative to passing all args directly):")
        print(HELP_EPILOG)
        return

    subcommand = sys.argv[1].lower()

    if subcommand in ("-h", "--help", "help"):
        print("fly-smart — hidden-city flight deal finder\n")
        subprocess.run([sys.executable, str(SCRIPT_PATH), "--help"])
        print("\nCLI shortcuts:")
        print(HELP_EPILOG)
        return

    if subcommand in ("search", "find"):
        # fly-smart search LAX HKG 2026-06-15 [--flexible 3] [...]
        argv = [str(SCRIPT_PATH), "-o", sys.argv[2], "-d", sys.argv[3], "-dt", sys.argv[4]] + sys.argv[5:]
        subprocess.run([sys.executable] + argv)

    elif subcommand == "alert":
        # fly-smart alert LAX HKG 2026-06-15 --threshold 600
        argv = [str(SCRIPT_PATH), "-o", sys.argv[2], "-d", sys.argv[3], "-dt", sys.argv[4]] + sys.argv[5:]
        result = subprocess.run([sys.executable] + argv)
        sys.exit(result.returncode)

    elif subcommand == "verify":
        argv = [str(SCRIPT_PATH), "-o", sys.argv[2], "-d", sys.argv[3], "-dt", sys.argv[4],
                "--verify-rules"] + sys.argv[5:]
        subprocess.run([sys.executable] + argv)

    elif subcommand == "export":
        # fly-smart export LAX HKG 2026-06-15 --format csv [--csv-output PATH]
        extra = sys.argv[5:]
        extra.append("--export-csv")
        argv = [str(SCRIPT_PATH), "-o", sys.argv[2], "-d", sys.argv[3], "-dt", sys.argv[4]] + extra
        subprocess.run([sys.executable] + argv)

    else:
        print(f"Unknown command: {subcommand}")
        print(HELP_EPILOG)
        sys.exit(1)


if __name__ == "__main__":
    main()
