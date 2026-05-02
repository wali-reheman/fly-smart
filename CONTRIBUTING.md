# Contributing to fly-smart

🎯 **First time contributor?** Thank you! Every contribution helps travelers save money.

## How to Contribute

### Reporting Bugs

Open an issue with the label `bug`. Include:
- Python version (`python3 --version`)
- Hermes Agent version
- The exact command that failed
- Full error output (paste the traceback)
- What you expected to happen vs what actually happened

### Suggesting Features

Open an issue with the label `enhancement`. Describe:
- The use case (why do you need this?)
- The route/paremeters you tried
- Any workarounds you've found

### Pull Requests

1. **Fork** the repo and create a branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```

2. **Run tests** (if any — see below):
   ```bash
   python3 -m venv ~/.hermes/venvs/test-flight
   ~/.hermes/venvs/test-flight/bin/pip install -r requirements-test.txt
   ~/.hermes/venvs/test-flight/bin/pytest
   ```

3. **Make your changes** — keep commits small and focused:
   ```bash
   git add .
   git commit -m "fix: handle empty price strings from Google Flights"
   ```

4. **Push and open a PR**:
   ```bash
   git push origin feat/your-feature-name
   ```
   Then open a pull request on GitHub.

### Style Guide

- Python: follow [PEP 8](https://pep8.org/)
- Commit messages: use imperative mood (`"add hub"`, not `"added hub"`)
- SKILL.md: preserve the YAML frontmatter — it is machine-readable

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/fly-smart.git
cd fly-smart

# Set up Python venv
python3 -m venv ~/.hermes/venvs/fly-smart-dev
source ~/.hermes/venvs/fly-smart-dev/bin/activate
pip install fast-flights

# Test the script
python3 fly-smart/references/flight-transfer-finder.py -o LAX -d HKG -dt 2026-06-01 --direct-only
```

## Project Structure

```
fly-smart/
├── SKILL.md                        # Skill definition (YAML frontmatter + docs)
├── references/
│   └── flight-transfer-finder.py   # Core script
├── README.md                       # Public landing page
└── CONTRIBUTING.md                 # This file
```

## License

By contributing, you agree your contributions will be licensed under the MIT License.
