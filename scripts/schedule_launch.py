"""Schedule launch content for Instagram Personal."""
import os
import sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
import django
django.setup()

import os
import json
import glob
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.files.base import ContentFile
from apps.composer.models import Post, PlatformPost, PostMedia
from apps.media_library.models import MediaAsset
from apps.social_accounts.models import SocialAccount

# Get workspace and Instagram account
ig_account = SocialAccount.objects.filter(platform="instagram_personal").first()
if not ig_account:
    print("ERROR: No Instagram Personal account found")
    exit(1)

workspace = ig_account.workspace
org = workspace.organization
print("Workspace:", workspace.name)
print("Instagram:", ig_account.account_name)
print()

# Load calendar
with open("/tmp/launch-content/calendar.json") as f:
    calendar = json.load(f)

# Start date: April 16, 2026 at 10:00 AM UTC
base_date = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)

# Get a user for uploaded_by
from apps.members.models import WorkspaceMembership
membership = WorkspaceMembership.objects.filter(workspace=workspace).first()
user_id = membership.user_id if membership else None

created_count = 0
for day_data in calendar["days"]:
    day_num = day_data["day"]
    day_dir = "/tmp/launch-content/day-%02d" % day_num

    if not os.path.exists(day_dir):
        print("SKIP day-%02d: directory not found" % day_num)
        continue

    # Schedule date
    scheduled_at = base_date + timedelta(days=day_num - 1)
    caption = day_data["ig_caption"]

    # Create the post
    post = Post.objects.create(
        workspace=workspace,
        caption=caption,
        scheduled_at=scheduled_at,
        status="scheduled",
    )

    # Upload images and create media attachments
    image_files = sorted(glob.glob(os.path.join(day_dir, "*.png")))
    for i, img_path in enumerate(image_files):
        filename = os.path.basename(img_path)
        with open(img_path, "rb") as f:
            content = f.read()

        # Create media asset
        asset = MediaAsset(
            workspace=workspace,
            organization=org,
            filename=filename,
            media_type="image",
            file_size=len(content),
            uploaded_by_id=user_id,
        )
        asset.file.save(
            "media_library/launch/day%02d_%s" % (day_num, filename),
            ContentFile(content),
            save=True,
        )

        # Attach to post
        PostMedia.objects.create(
            post=post,
            media_asset=asset,
            position=i,
        )

    # Create platform post for Instagram Personal
    PlatformPost.objects.create(
        post=post,
        social_account=ig_account,
        status="scheduled",
        scheduled_at=scheduled_at,
    )

    created_count += 1
    date_str = scheduled_at.strftime("%b %d %H:%M")
    print("Day %02d | %s | %d images | %s..." % (day_num, date_str, len(image_files), caption[:50]))

print()
print("Done! Created %d scheduled posts." % created_count)
