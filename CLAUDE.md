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

## Infrastructure

### Media Storage (Cloudflare R2)

- **Backend:** `STORAGE_BACKEND=s3` using `django-storages` with Cloudflare R2
- **Bucket:** `marketing-minicart-com`
- **Public domain:** `ig.tinym.ca` (used as `S3_CUSTOM_DOMAIN`)
- **ACL:** `public-read`, no signed URLs (`AWS_QUERYSTRING_AUTH=False`)
- **Media URLs:** `https://ig.tinym.ca/media_library/YYYY/MM/<filename>`
- **Deployed on:** DigitalOcean Droplet at `45.55.164.155` (SSH as `root`), Docker Compose

### Deployment

- **Server:** `ssh root@45.55.164.155`
- **App dir:** `/root/brightbean-studio`
- **Deploy:** `git pull origin main && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
- **Services:** app (gunicorn), worker (background tasks), caddy (reverse proxy/TLS), postgres, maintenance

## Resolved Issues

### Instagram Scheduled Post Failure (2026-04-17) — RESOLVED 2026-04-18

- **Original error:** Instagram Graph API couldn't fetch media from local storage (`marketing.minicart.com/media/...`)
- **Fix:** Migrated media storage from local filesystem to Cloudflare R2 with public CDN domain `ig.tinym.ca`
- **Also fixed:** API upload was mislabeling videos as `image` (used browser Content-Type instead of magic bytes). Now uses `_detect_mime_from_bytes` for accurate detection.
- **Remaining:** Old scheduled posts using local storage URLs need to be deleted and rescheduled with R2-hosted media. Day-label offset in captions still needs correction.
