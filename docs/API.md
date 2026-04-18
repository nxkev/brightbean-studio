# BrightBean Studio REST API

Base URL: `https://marketing.minicart.com/api/v1`

## Authentication

All requests require a Bearer token in the Authorization header:

```
Authorization: Bearer bb_your_api_key_here
```

Set the `API_KEY` environment variable on the server to configure the key.

---

## Endpoints

### List Connected Accounts

```
GET /api/v1/accounts/?workspace_id={uuid}
```

**Query params:**
- `workspace_id` (optional) — filter by workspace UUID

**Response:**
```json
{
  "accounts": [
    {
      "id": "uuid",
      "platform": "instagram_personal",
      "account_name": "Minicart.com",
      "account_handle": "minicartcom",
      "connection_status": "connected",
      "workspace_id": "uuid"
    }
  ]
}
```

---

### Upload Media

```
POST /api/v1/media/upload/
Content-Type: multipart/form-data
```

**Form fields:**
- `file` (required) — the image or video file
- `workspace_id` (required) — workspace UUID

Media type is auto-detected from file content (magic bytes), not the `Content-Type` header. Supported types: JPEG, PNG, WebP, GIF, MP4, QuickTime, AVI, WebM, PDF.

Files are uploaded to Cloudflare R2 and served publicly via `ig.tinym.ca`.

**Response (201):**
```json
{
  "id": "uuid",
  "filename": "photo.png",
  "media_type": "image",
  "file_size": 245760,
  "url": "https://ig.tinym.ca/media_library/2026/04/photo.png"
}
```

**Example:**
```bash
curl -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -F "file=@photo.png" \
  -F "workspace_id=af23ceb2-4021-4e3d-aa2f-74a20a8c779d" \
  https://marketing.minicart.com/api/v1/media/upload/
```

---

### Create & Schedule a Post

```
POST /api/v1/posts/
Content-Type: application/json
```

**Body:**
```json
{
  "workspace_id": "uuid",
  "caption": "Your post caption here",
  "title": "",
  "first_comment": "",
  "tags": ["launch", "product"],
  "media_ids": ["uuid-from-upload", "uuid-from-upload"],
  "account_ids": ["uuid-of-social-account"],
  "scheduled_at": "2026-04-20T10:00:00Z"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `workspace_id` | Yes | Workspace UUID |
| `caption` | No | Post caption text. Defaults to `""` if omitted. |
| `account_ids` | Yes | Array of social account UUIDs to post to |
| `media_ids` | No | Array of media asset UUIDs (from upload endpoint) |
| `scheduled_at` | No | ISO 8601 datetime. If omitted, publishes immediately |
| `title` | No | Post title (used by YouTube, Pinterest) |
| `first_comment` | No | Auto-posted as first comment after publishing |
| `tags` | No | Array of tag strings |

**Response (201):**
```json
{
  "id": "uuid",
  "caption": "Your post caption",
  "title": "",
  "status": "scheduled",
  "tags": ["launch"],
  "scheduled_at": "2026-04-20T10:00:00+00:00",
  "published_at": null,
  "created_at": "2026-04-16T15:00:00+00:00",
  "platform_posts": [
    {
      "id": "uuid",
      "platform": "instagram_personal",
      "account_name": "Minicart.com",
      "status": "scheduled",
      "scheduled_at": "2026-04-20T10:00:00+00:00",
      "published_at": null,
      "platform_post_id": null,
      "publish_error": null
    }
  ],
  "media": [
    {
      "id": "uuid",
      "filename": "photo.png",
      "media_type": "image",
      "url": "https://ig.tinym.ca/media_library/2026/04/photo.png",
      "position": 0
    }
  ]
}
```

**Example — schedule a post with images:**
```bash
# 1. Upload images
IMG1=$(curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -F "file=@slide1.png" \
  -F "workspace_id=$WORKSPACE_ID" \
  https://marketing.minicart.com/api/v1/media/upload/ | jq -r '.id')

IMG2=$(curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -F "file=@slide2.png" \
  -F "workspace_id=$WORKSPACE_ID" \
  https://marketing.minicart.com/api/v1/media/upload/ | jq -r '.id')

# 2. Create the post
curl -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"caption\": \"Check this out!\",
    \"media_ids\": [\"$IMG1\", \"$IMG2\"],
    \"account_ids\": [\"$ACCOUNT_ID\"],
    \"scheduled_at\": \"2026-04-20T10:00:00Z\"
  }" \
  https://marketing.minicart.com/api/v1/posts/
```

---

### List Posts

```
GET /api/v1/posts/?workspace_id={uuid}&status={status}&limit={n}&offset={n}
```

**Query params:**
- `workspace_id` (optional) — filter by workspace UUID
- `status` (optional) — filter by platform post status. Valid values: `draft`, `pending_review`, `pending_client`, `approved`, `changes_requested`, `rejected`, `scheduled`, `publishing`, `published`, `failed`
- `limit` (optional, default 50, max 200)
- `offset` (optional, default 0)

> **Note:** The `status` filter matches against individual `PlatformPost` records. A `Post` is included in the results if any of its platform posts have the given status. For example, `status=failed` returns posts that have at least one failed platform post.

**Response:**
```json
{
  "posts": [...],
  "total": 15,
  "limit": 50,
  "offset": 0
}
```

---

### Get Post Detail

```
GET /api/v1/posts/{post_id}/
```

Returns full post with platform posts and media.

---

### Delete a Post

```
DELETE /api/v1/posts/{post_id}/
```

Deletes the post, all associated platform posts, and all attached `MediaAsset` records (including the underlying files). This is irreversible.

**Response:**
```json
{
  "deleted": true,
  "post": { ... }
}
```

**Example:**
```bash
curl -X DELETE \
  -H "Authorization: Bearer $API_KEY" \
  https://marketing.minicart.com/api/v1/posts/{post_id}/
```

---

### Retry Failed Post

```
POST /api/v1/posts/{post_id}/retry/
```

Resets all failed platform posts back to `scheduled` for immediate retry.

**Response:**
```json
{
  "retried": 1,
  "post": { ... }
}
```

---

## Scheduling Workflow

1. **Upload media** via `POST /api/v1/media/upload/`
2. **Get account IDs** via `GET /api/v1/accounts/`
3. **Create post** via `POST /api/v1/posts/` with `scheduled_at` and `account_ids`
4. The background worker publishes at the scheduled time
5. **Check status** via `GET /api/v1/posts/{id}/`

## Status Values

These are `PlatformPost` status values, used both in `platform_posts[].status` response fields and as the `status` query parameter on `GET /api/v1/posts/`.

| Status | Description |
|--------|-------------|
| `draft` | Not yet scheduled or submitted for review |
| `pending_review` | Submitted for internal review |
| `pending_client` | Awaiting client approval |
| `approved` | Approved internally or by client |
| `changes_requested` | Reviewer requested edits |
| `rejected` | Post was rejected |
| `scheduled` | Queued for publishing at `scheduled_at` |
| `publishing` | Currently being published |
| `published` | Successfully posted to the platform |
| `failed` | Publishing failed (check `publish_error`) |

The aggregate `Post.status` (derived from its `platform_posts`) can additionally be `partially_published` when some platform posts succeeded and others failed.
