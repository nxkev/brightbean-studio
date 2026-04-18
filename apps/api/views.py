"""REST API views for BrightBean Studio.

Endpoints:
    GET  /api/v1/accounts/                  — list connected social accounts
    POST /api/v1/media/upload/              — upload a media file
    GET  /api/v1/posts/                     — list posts
    POST /api/v1/posts/                     — create & schedule a post
    GET  /api/v1/posts/<id>/                — get post detail
    DELETE /api/v1/posts/<id>/              — delete a post
    POST /api/v1/posts/<id>/retry/          — retry a failed post
"""

import json
import logging
from datetime import timedelta

from django.core.files.uploadedfile import InMemoryUploadedFile
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.composer.models import PlatformPost, Post, PostMedia
from apps.media_library.models import MediaAsset
from apps.social_accounts.models import SocialAccount

from .auth import api_auth_required

logger = logging.getLogger(__name__)


def _serialize_account(account):
    return {
        "id": str(account.id),
        "platform": account.platform,
        "account_name": account.account_name,
        "account_handle": account.account_handle,
        "connection_status": account.connection_status,
        "workspace_id": str(account.workspace_id),
    }


def _serialize_post(post):
    platform_posts = []
    for pp in post.platform_posts.select_related("social_account").all():
        platform_posts.append(
            {
                "id": str(pp.id),
                "platform": pp.social_account.platform if pp.social_account else None,
                "account_name": pp.social_account.account_name if pp.social_account else None,
                "status": pp.status,
                "scheduled_at": pp.scheduled_at.isoformat() if pp.scheduled_at else None,
                "published_at": pp.published_at.isoformat() if pp.published_at else None,
                "platform_post_id": pp.platform_post_id or None,
                "publish_error": pp.publish_error or None,
            }
        )

    media = []
    for pm in post.media_attachments.select_related("media_asset").order_by("position"):
        asset = pm.media_asset
        media.append(
            {
                "id": str(asset.id),
                "filename": asset.filename,
                "media_type": asset.media_type,
                "url": asset.file.url if asset.file else None,
                "position": pm.position,
            }
        )

    return {
        "id": str(post.id),
        "caption": post.caption,
        "title": post.title,
        "status": post.status,
        "tags": post.tags,
        "scheduled_at": post.scheduled_at.isoformat() if post.scheduled_at else None,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "created_at": post.created_at.isoformat(),
        "platform_posts": platform_posts,
        "media": media,
    }


# ------------------------------------------------------------------
# Accounts
# ------------------------------------------------------------------


@csrf_exempt
@api_auth_required
@require_GET
def list_accounts(request):
    """List all connected social accounts."""
    workspace_id = request.GET.get("workspace_id")
    qs = SocialAccount.objects.all()
    if workspace_id:
        qs = qs.filter(workspace_id=workspace_id)
    accounts = [_serialize_account(a) for a in qs.order_by("platform", "account_name")]
    return JsonResponse({"accounts": accounts})


# ------------------------------------------------------------------
# Media Upload
# ------------------------------------------------------------------


@csrf_exempt
@api_auth_required
@require_POST
def upload_media(request):
    """Upload a media file.

    Request: multipart/form-data with 'file' field and 'workspace_id' param.
    Returns: {"id": "...", "filename": "...", "url": "...", "media_type": "..."}
    """
    workspace_id = request.POST.get("workspace_id") or request.GET.get("workspace_id")
    if not workspace_id:
        return JsonResponse({"error": "workspace_id is required"}, status=400)

    if "file" not in request.FILES:
        return JsonResponse({"error": "No file provided. Use 'file' field."}, status=400)

    uploaded = request.FILES["file"]

    # Detect media type from file magic bytes (not browser-supplied Content-Type)
    from apps.media_library.validators import _detect_mime_from_bytes, determine_file_type

    detected_mime = _detect_mime_from_bytes(uploaded)
    if detected_mime:
        media_type = determine_file_type(detected_mime) or "image"
        content_type = detected_mime
    else:
        content_type = uploaded.content_type or ""
        if content_type.startswith("video/"):
            media_type = "video"
        else:
            media_type = "image"

    from apps.workspaces.models import Workspace

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": "Workspace not found"}, status=404)

    asset = MediaAsset(
        workspace=workspace,
        organization=workspace.organization,
        filename=uploaded.name,
        media_type=media_type,
        file_size=uploaded.size,
        mime_type=content_type,
    )
    asset.file.save(uploaded.name, uploaded, save=True)

    url = asset.file.url if asset.file else None

    return JsonResponse(
        {
            "id": str(asset.id),
            "filename": asset.filename,
            "media_type": asset.media_type,
            "file_size": asset.file_size,
            "url": url,
        },
        status=201,
    )


# ------------------------------------------------------------------
# Posts
# ------------------------------------------------------------------


@csrf_exempt
@api_auth_required
@require_http_methods(["GET", "POST"])
def posts(request):
    """List or create posts."""
    if request.method == "GET":
        return _list_posts(request)
    return _create_post(request)


def _list_posts(request):
    """List posts, optionally filtered by workspace_id and status."""
    workspace_id = request.GET.get("workspace_id")
    status = request.GET.get("status")
    limit = min(int(request.GET.get("limit", 50)), 200)
    offset = int(request.GET.get("offset", 0))

    qs = Post.objects.all().order_by("-created_at")
    if workspace_id:
        qs = qs.filter(workspace_id=workspace_id)
    if status:
        # Filter by platform post status since Post.status is derived
        post_ids = PlatformPost.objects.filter(status=status).values_list("post_id", flat=True)
        qs = qs.filter(id__in=post_ids)

    total = qs.count()
    posts_list = [_serialize_post(p) for p in qs[offset : offset + limit]]

    return JsonResponse({"posts": posts_list, "total": total, "limit": limit, "offset": offset})


def _create_post(request):
    """Create a post and optionally schedule it.

    JSON body:
    {
        "workspace_id": "uuid",          (required)
        "caption": "text",               (required)
        "title": "text",                 (optional)
        "first_comment": "text",         (optional)
        "tags": ["tag1", "tag2"],        (optional)
        "media_ids": ["uuid", ...],      (optional - from /api/v1/media/upload/)
        "account_ids": ["uuid", ...],    (required - social account IDs to post to)
        "scheduled_at": "ISO datetime",  (optional - if omitted, publishes immediately)
    }
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    workspace_id = body.get("workspace_id")
    caption = body.get("caption", "")
    title = body.get("title", "")
    first_comment = body.get("first_comment", "")
    tags = body.get("tags", [])
    media_ids = body.get("media_ids", [])
    account_ids = body.get("account_ids", [])
    scheduled_at_str = body.get("scheduled_at")

    if not workspace_id:
        return JsonResponse({"error": "workspace_id is required"}, status=400)
    if not account_ids:
        return JsonResponse({"error": "account_ids is required (list of social account UUIDs)"}, status=400)

    from apps.workspaces.models import Workspace

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": "Workspace not found"}, status=404)

    # Parse scheduled_at
    scheduled_at = None
    if scheduled_at_str:
        from django.utils.dateparse import parse_datetime

        scheduled_at = parse_datetime(scheduled_at_str)
        if not scheduled_at:
            return JsonResponse({"error": "Invalid scheduled_at format. Use ISO 8601."}, status=400)
        if not scheduled_at.tzinfo:
            scheduled_at = timezone.make_aware(scheduled_at)

    # Validate social accounts
    accounts = SocialAccount.objects.filter(id__in=account_ids, workspace=workspace)
    if accounts.count() != len(account_ids):
        return JsonResponse({"error": "One or more account_ids not found in this workspace"}, status=400)

    # Determine status
    if scheduled_at:
        status = "scheduled"
    else:
        status = "scheduled"
        scheduled_at = timezone.now()  # Publish immediately

    # Create the post
    post = Post.objects.create(
        workspace=workspace,
        caption=caption,
        title=title,
        first_comment=first_comment,
        tags=tags,
        scheduled_at=scheduled_at,
    )

    # Attach media
    for i, media_id in enumerate(media_ids):
        try:
            asset = MediaAsset.objects.get(id=media_id)
            PostMedia.objects.create(post=post, media_asset=asset, position=i)
        except MediaAsset.DoesNotExist:
            logger.warning("Media asset %s not found, skipping", media_id)

    # Create platform posts
    for account in accounts:
        PlatformPost.objects.create(
            post=post,
            social_account=account,
            status=status,
            scheduled_at=scheduled_at,
        )

    return JsonResponse(_serialize_post(post), status=201)


@csrf_exempt
@api_auth_required
@require_http_methods(["GET", "DELETE"])
def post_detail(request, post_id):
    """Get or delete a single post."""
    try:
        post = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        return JsonResponse({"error": "Post not found"}, status=404)

    if request.method == "DELETE":
        post_data = _serialize_post(post)
        post.delete()
        return JsonResponse({"deleted": True, "post": post_data})

    return JsonResponse(_serialize_post(post))


@csrf_exempt
@api_auth_required
@require_POST
def retry_post(request, post_id):
    """Retry all failed platform posts for a given post."""
    try:
        post = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        return JsonResponse({"error": "Post not found"}, status=404)

    retried = 0
    for pp in post.platform_posts.filter(status="failed"):
        pp.status = "scheduled"
        pp.scheduled_at = timezone.now()
        pp.retry_count = 0
        pp.publish_error = ""
        pp.save()
        retried += 1

    return JsonResponse({"retried": retried, "post": _serialize_post(post)})
