# Instagram Posting & Scheduling System — Full Reference

This document describes the complete flow for scheduling and publishing Instagram posts, from API upload through background publishing. It is self-contained enough to recreate the system from scratch.

---

## Meta App Setup (Prerequisites)

Both Instagram login methods require a **Meta Developer App**. Here's how to set it up:

### 1. Create a Meta Developer Account
- Go to [developers.facebook.com](https://developers.facebook.com)
- Log in with any Facebook account (personal is fine — this is just the developer account)
- Complete the developer registration if prompted

### 2. Create a New App
- Go to **My Apps > Create App**
- Select **"Other"** use case, then **"Business"** type
- Name it (e.g. "My Scheduler") and create

### 3. Add Instagram Product
- In the app dashboard, click **"Add Product"**
- Find **"Instagram"** and click **"Set Up"**
- This gives you access to the Instagram API

### 4. Get Your Credentials
- Go to **App Settings > Basic**
- Copy the **App ID** (this is your `client_id`)
- Copy the **App Secret** (this is your `client_secret`)

### 5. Configure OAuth Redirect
- Go to **Instagram > Basic Display** (or **Instagram Login** settings)
- Add your callback URL: `https://your-domain.com/social-accounts/callback/instagram_personal/`
- Add it to **Valid OAuth Redirect URIs**

### 6. Required Permissions
Request these scopes (some need App Review for production use):
- `instagram_business_basic` — read profile info
- `instagram_business_content_publish` — create posts, reels, carousels
- `instagram_business_manage_comments` — post first comments
- `instagram_business_manage_messages` — inbox (optional)

### 7. App Review (for Production)
- In **Development mode**, you can only post to accounts that are added as test users in the app
- For production use, submit the app for **App Review** with the above permissions
- You'll need to provide a screencast demo and privacy policy URL

### Two Login Methods — Same App

The same Meta app supports both login methods. The difference is the user experience:

| | Instagram Login (`instagram_personal`) | Facebook Login (`instagram`) |
|---|---|---|
| **User logs in with** | Instagram credentials directly | Facebook credentials |
| **Account types** | Personal, Creator, and Business | Business only (must have linked Facebook Page) |
| **OAuth URL** | `api.instagram.com/oauth/authorize` | `facebook.com/v21.0/dialog/oauth` |
| **Simpler for users?** | Yes — no Facebook Page required | No — requires FB Page + IG account linking |
| **Recommended for** | Most use cases | Apps that also need Facebook Page posting |

**Recommendation:** Use `instagram_personal` (Instagram Login) unless you specifically need Facebook Page integration. It works with all account types and is simpler for end users.

### Store Credentials in the App
Once you have `client_id` and `client_secret`, add them to your app:
- **Environment variables:** `PLATFORM_INSTAGRAM_APP_ID` and `PLATFORM_INSTAGRAM_APP_SECRET`
- **Or database:** Create a `PlatformCredential` record with `platform="instagram_personal"`, `credentials={"client_id": "...", "client_secret": "..."}`, `is_configured=True`

---

## Architecture Overview

```
API Upload → MediaAsset (stored in R2/S3)
API Create Post → Post + PostMedia + PlatformPost(status=scheduled)
Background Worker (15s loop) → finds due posts → calls Instagram API → marks published
```

Three layers:
1. **REST API** — upload media, create/schedule posts
2. **Models** — Post, PlatformPost, PostMedia, MediaAsset, SocialAccount, PlatformCredential
3. **Publish Engine** — background worker that polls for due posts and publishes them

---

## Models

### MediaAsset
Stores uploaded files. Uses Django's storage backend (S3/R2 or local filesystem).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `workspace` | FK Workspace | |
| `organization` | FK Organization | |
| `file` | FileField | `upload_to="media_library/%Y/%m/"` |
| `filename` | CharField | original name |
| `media_type` | CharField | `image`, `video`, `gif`, `document` |
| `mime_type` | CharField | e.g. `image/png` |
| `file_size` | BigInt | bytes |
| `width`, `height` | Int | pixels |
| `processing_status` | CharField | `pending`, `completed`, `failed` |

`asset.file.url` returns the public URL (e.g. `https://ig.tinym.ca/media_library/2026/04/image.png`).

### Post
The base content record. Caption, tags, schedule time.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `workspace` | FK Workspace | |
| `caption` | TextField | base caption for all platforms |
| `title` | CharField | for YouTube/Pinterest |
| `first_comment` | TextField | posted 2 min after publish |
| `tags` | JSONField | list of strings |
| `scheduled_at` | DateTimeField | default schedule time |
| `published_at` | DateTimeField | set after publish |

`Post.status` is a **derived property** — computed from child PlatformPost statuses, never stored.

### PlatformPost
One per (Post, SocialAccount) pair. **This is where status lives.**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `post` | FK Post | |
| `social_account` | FK SocialAccount | |
| `status` | CharField | `draft`, `scheduled`, `publishing`, `published`, `failed` |
| `platform_post_id` | CharField | ID returned by Instagram after publish |
| `publish_error` | TextField | last error message |
| `scheduled_at` | DateTimeField | nullable — falls back to `post.scheduled_at` |
| `published_at` | DateTimeField | set on success |
| `retry_count` | Int | 0-3 |
| `next_retry_at` | DateTimeField | when to retry |
| `platform_specific_caption` | TextField | nullable override |
| `platform_specific_first_comment` | TextField | nullable override |
| `platform_extra` | JSONField | e.g. `{"post_type": "reel"}` |

Unique: `(post, social_account)`.

### PostMedia
Links Post to MediaAsset with ordering.

| Field | Type | Notes |
|---|---|---|
| `post` | FK Post | |
| `media_asset` | FK MediaAsset | |
| `position` | Int | 0, 1, 2... determines carousel order |

### SocialAccount
Connected Instagram account with encrypted tokens.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `workspace` | FK Workspace | |
| `platform` | CharField | `instagram_personal` |
| `account_platform_id` | CharField | Instagram user ID |
| `account_name` | CharField | display name |
| `oauth_access_token` | EncryptedTextField | AES-256-GCM |
| `oauth_refresh_token` | EncryptedTextField | AES-256-GCM |
| `token_expires_at` | DateTimeField | ~60 days from issue |
| `connection_status` | CharField | `connected`, `disconnected`, etc. |

### PlatformCredential
App-level OAuth credentials (org-scoped).

| Field | Type | Notes |
|---|---|---|
| `organization` | FK Organization | |
| `platform` | CharField | `instagram_personal` |
| `credentials` | EncryptedJSONField | `{"client_id": "...", "client_secret": "..."}` |
| `is_configured` | Boolean | must be True |

---

## Instagram OAuth Flow

Uses **Instagram Login** (not Facebook Login). API version: v21.0.

### 1. Authorization URL

```
https://api.instagram.com/oauth/authorize
  ?client_id=APP_ID
  &redirect_uri=REDIRECT_URI
  &state=CSRF_TOKEN
  &scope=instagram_business_basic,instagram_business_content_publish,instagram_business_manage_comments,instagram_business_manage_messages
  &response_type=code
  &enable_fb_login=0
  &force_authentication=1
```

### 2. Token Exchange (short-lived)

```
POST https://api.instagram.com/oauth/access_token
Content-Type: application/x-www-form-urlencoded

client_id=APP_ID&client_secret=APP_SECRET&code=CODE&grant_type=authorization_code&redirect_uri=REDIRECT_URI
```

Response: `{"access_token": "SHORT_TOKEN", "user_id": "12345"}`

### 3. Exchange for Long-Lived Token (~60 days)

```
GET https://graph.instagram.com/v21.0/access_token
  ?grant_type=ig_exchange_token
  &client_secret=APP_SECRET
  &access_token=SHORT_TOKEN
```

Response: `{"access_token": "LONG_TOKEN", "expires_in": 5183944}`

Store `LONG_TOKEN` as both `oauth_access_token` and `oauth_refresh_token` (Instagram uses the same token for both).

### 4. Token Refresh

```
GET https://graph.instagram.com/v21.0/refresh_access_token
  ?grant_type=ig_refresh_token
  &access_token=CURRENT_LONG_TOKEN
```

Returns a new long-lived token with fresh 60-day expiry.

### 5. Profile Fetch

```
GET https://graph.instagram.com/v21.0/me
  ?fields=user_id,username,name,profile_picture_url,followers_count
  &access_token=TOKEN
```

---

## Instagram Publishing Flow

Instagram uses a **two-step container model**: create a media container, wait for processing, then publish it.

### Single Image Post

**Step 1 — Create container:**
```
POST https://graph.instagram.com/v21.0/me/media
{
  "image_url": "https://public-url.com/image.png",
  "caption": "Post caption here"
}
```
Response: `{"id": "CONTAINER_ID"}`

**Step 2 — Poll until ready:**
```
GET https://graph.instagram.com/v21.0/{CONTAINER_ID}?fields=status_code,status
```
Poll every 2 seconds. Wait for `status_code == "FINISHED"`. Max 60 attempts (~2 min).

**Step 3 — Publish:**
```
POST https://graph.instagram.com/v21.0/me/media_publish
{"creation_id": "CONTAINER_ID"}
```
Response: `{"id": "PUBLISHED_MEDIA_ID"}`

### Reel (Video)

Same flow, but container payload is:
```json
{
  "media_type": "REELS",
  "video_url": "https://public-url.com/video.mp4",
  "caption": "Caption"
}
```

### Carousel (Multiple Images/Videos)

**Step 1 — Create child containers** (one per media item):
```json
// Image child:
{"is_carousel_item": true, "image_url": "https://..."}

// Video child:
{"is_carousel_item": true, "media_type": "VIDEO", "video_url": "https://..."}
```
Wait for each child to reach `FINISHED`.

**Step 2 — Create carousel container:**
```json
{
  "media_type": "CAROUSEL",
  "children": "child_id_1,child_id_2,child_id_3",
  "caption": "Caption"
}
```

**Step 3 — Publish** (same as single post).

### First Comment

Posted 2 minutes after publish:
```
POST https://graph.instagram.com/v21.0/{PUBLISHED_MEDIA_ID}/comments
{"message": "First comment text"}
```

### Key Rule
Instagram fetches media from the URL you provide — the URL must be **publicly accessible**. Local/private URLs won't work. Use S3/R2/CDN with public access.

---

## REST API

### Authentication
All endpoints require: `Authorization: Bearer <API_KEY>`

API key format: `bb_` + 32-char random token. Compared against `settings.API_KEY`.

### Upload Media

```
POST /api/v1/media/upload/
Content-Type: multipart/form-data

file=<binary>
workspace_id=<uuid>
```

- Detects media type from file magic bytes (not Content-Type header)
- Saves to storage backend (S3/R2)
- Returns:

```json
{
  "id": "uuid",
  "filename": "image.png",
  "media_type": "image",
  "file_size": 102400,
  "url": "https://ig.tinym.ca/media_library/2026/04/image.png"
}
```

### Create & Schedule Post

```
POST /api/v1/posts/
Content-Type: application/json

{
  "workspace_id": "uuid",
  "caption": "Post caption",
  "first_comment": "Hashtags here",
  "tags": ["launch"],
  "media_ids": ["uuid1", "uuid2"],
  "account_ids": ["social-account-uuid"],
  "scheduled_at": "2026-04-20T14:00:00Z"
}
```

- `media_ids` order = carousel position
- `scheduled_at` omitted = publish immediately
- Creates: Post + PostMedia (per media) + PlatformPost (per account, status=`scheduled`)

### List Posts

```
GET /api/v1/posts/?workspace_id=uuid&status=scheduled&limit=50&offset=0
```

### Get Post Detail

```
GET /api/v1/posts/{post_id}/
```

### Delete Post

```
DELETE /api/v1/posts/{post_id}/
```
Deletes post, all platform posts, and all attached media assets + files.

### Retry Failed Post

```
POST /api/v1/posts/{post_id}/retry/
```
Resets all failed PlatformPosts back to `scheduled` with `retry_count=0`.

---

## Publish Engine (Background Worker)

### How It Runs

```bash
python manage.py run_publisher --interval 15
```

Polls every 15 seconds. Catches SIGINT/SIGTERM for graceful shutdown.

### Poll Cycle

1. Query PlatformPosts where `status=scheduled` AND `effective_at <= now()`:
   ```sql
   SELECT * FROM platform_post
   WHERE status = 'scheduled'
   AND COALESCE(scheduled_at, post.scheduled_at) <= NOW()
   ORDER BY effective_at
   LIMIT 10
   ```

2. Group by parent Post ID

3. For each group (parallel, max 4 workers):
   - Lock PlatformPosts with `SELECT FOR UPDATE`
   - Set status → `publishing`
   - For each PlatformPost (parallel, max 5 workers):
     - Resolve app credentials (PlatformCredential → decrypt)
     - Refresh token if expiring soon
     - Download media to temp files, collect public URLs
     - Determine PostType: video → REEL, multiple images → CAROUSEL, single image → IMAGE
     - Build `PublishContent` and call `provider.publish_post()`
     - On success: status → `published`, save `platform_post_id`
     - On failure: schedule retry
   - Clean up temp files
   - Schedule first comment (2 min delay) if present

4. Process retries: find PlatformPosts with `retry_count > 0` and `next_retry_at <= now()`

### Retry Logic

- Max 3 retries
- Backoff: 1 min, 5 min, 30 min
- On failure: status stays `scheduled` with incremented `retry_count` and future `next_retry_at`
- After 3 failures: status → `failed`

### PostType Resolution

Priority:
1. Explicit `platform_extra.post_type` hint
2. Multi-media on Instagram → `CAROUSEL`
3. Single video on Instagram → `REEL`
4. Single image → `IMAGE`
5. No media → `TEXT`

---

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `API_KEY` | required | REST API bearer token |
| `APP_URL` | `""` | Base URL for making local media paths absolute |
| `STORAGE_BACKEND` | `local` | `local` or `s3` for R2/S3 |
| `S3_CUSTOM_DOMAIN` | `""` | Public CDN domain for media (e.g. `ig.tinym.ca`) |
| `PUBLISHER_FIRST_COMMENT_DELAY` | `120` | Seconds after publish before first comment |
| `ENCRYPTION_KEY_SALT` | required | Salt for AES-256-GCM key derivation |
| `SECRET_KEY` | required | Django secret key (also used for encryption) |

---

## End-to-End Example

```bash
# 1. Upload image
IMG_ID=$(curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -F "file=@photo.png" \
  -F "workspace_id=$WORKSPACE_ID" \
  https://app.example.com/api/v1/media/upload/ | jq -r '.id')

# 2. Schedule post for tomorrow at 10am UTC
curl -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"caption\": \"Hello world!\",
    \"first_comment\": \"#hashtags #here\",
    \"media_ids\": [\"$IMG_ID\"],
    \"account_ids\": [\"$ACCOUNT_ID\"],
    \"scheduled_at\": \"2026-04-21T10:00:00Z\"
  }" \
  https://app.example.com/api/v1/posts/

# 3. The background worker picks it up at 10:00 UTC and publishes automatically
# 4. First comment is posted 2 minutes after successful publish
```
