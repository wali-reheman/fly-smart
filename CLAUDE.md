# CLAUDE.md

Skills repository for Hermes Agent by Wali Reheman.

## Repository Structure

```
skills/
├── flight-search/
│   ├── SKILL.md              # Main skill with YAML frontmatter + instructions
│   └── references/           # Supporting files
│       └── flight-transfer-finder.py   # The v4 transfer finder script
├── README.md
└── LICENSE
```

## Skill File Format

Each skill has a `SKILL.md` with this structure:

```markdown
---
name: skill-name
description: What the skill does and when to use it
license: MIT
metadata:
  author: wali-reheman
  version: "1.0.0"
triggers:
  - "trigger phrase 1"
  - "trigger phrase 2"
tools:
  - terminal
  - web_search
---

# Skill Title

Content...
```

## Adding New Skills

1. Create `skill-name/SKILL.md` with YAML frontmatter (`name`, `description`) and instructions
2. Add `references/` folder with supporting files
3. Update README.md with the new skill
4. Commit to main

## Commit Policy

Commit directly to main. Version bumps for:
- **MINOR**: New features, content additions
- **PATCH**: Bug fixes, typo corrections
