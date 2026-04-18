# CLAUDE.md - Brightbean Studio

## Project Overview

Django project (see `manage.py`, `pyproject.toml`, `requirements.txt`).

## Working Preferences

### Use Sub-Agents and Agent Teams

- Leverage sub-agents and agent teams whenever possible to parallelize work and keep the main context clean.
- Use the `Agent` tool with appropriate `subagent_type` for specialized tasks (e.g., `Explore` for codebase research, `code-reviewer` for reviews, `vercel-builder` for build checks).
- When multiple independent tasks exist, spawn agents in parallel.

### Model Selection

- Do not default to Opus for everything. Use Sonnet (`model: "sonnet"`) for straightforward tasks where Opus-level reasoning is not necessary.
- Reserve Opus for complex architectural decisions, nuanced code review, or tasks requiring deep reasoning.
- Use Haiku for simple lookups or lightweight operations when available.

## Known Issues

### Instagram Scheduled Post Failure (2026-04-17)

- **Error:** `"The media could not be fetched from this URI: https://marketing.minicart.com/media/media_library/2026/04/image_kttME6Q.png … Only photo or video can be accepted as media type."`
- **Scheduled:** 2026-04-17 10am ET — post failed to publish
- **Caption:** "Something new is brewing…" (Day 1 caption, not Day 2 — schedule is offset by one day vs launch-content folder labels)
- **Root cause:** Instagram Graph API couldn't fetch the image at publish time. URL is valid, Content-Type is `image/png`, file was uploaded days prior. Likely a transient fetch failure on Instagram's side — Caddy config has no blocking/rate limiting.
- **Additional issues:**
  - All scheduled BrightBean media still uses the old dark DSLR images, not the new cream/mint set
  - Day-label offset: scheduled posts are off by one day vs the launch-content folder labels
- **Status:** Unresolved — needs retry/reschedule with corrected images and day alignment
