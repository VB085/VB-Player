# VB Player — CLAUDE.md

## Project

PyQt6 desktop audio player with spectrum visualization, scrolling lyrics, album management, and frameless window. Runs on Linux/Windows/macOS via GStreamer.

## Build & Run

```bash
# Install dependencies
pip install PyQt6 mutagen numpy

# Run
python main.py
```

## Agent skills

### Issue tracker

Local markdown in `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context. See `docs/agents/domain.md`.

### Auto-trigger rules

When these conditions are met, suggest the user invoke the corresponding skill:

| Condition | Suggest |
|-----------|---------|
| User reports a bug or says something is broken/failing | `/diagnose` |
| User describes a new feature request without clear specs | `/grill-me` |
| User asks "how does this code work" or is confused by a module | `/zoom-out` |
| Conversation is getting very long and context is strained | `/handoff` |
| User says "be brief", "less tokens", or "shorter" | `/caveman` |
| User wants to refactor or improve code structure | `/improve-codebase-architecture` |
| User has a plan/spec and wants to break it into tasks | `/to-issues` |
| User asks about domain terminology or naming confusion | `/ubiquitous-language` |
| User wants to build a feature test-first | `/tdd` |
