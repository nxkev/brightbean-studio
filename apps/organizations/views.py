import calendar as cal_mod
from collections import defaultdict
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.composer.models import Post
from apps.members.decorators import require_org_role
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.workspaces.models import Workspace


@login_required
@require_org_role(OrgMembership.OrgRole.ADMIN)
def settings_view(request):
    org = request.org
    return render(request, "organizations/settings.html", {"organization": org, "settings_active": "general"})


@login_required
def cross_workspace_calendar(request):
    """Org-level calendar showing all workspaces' posts, color-coded by workspace."""
    org = request.org
    if not org:
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("Organization required.")

    # Get workspaces the user has membership in
    user_workspace_ids = set(
        WorkspaceMembership.objects.filter(user=request.user).values_list("workspace_id", flat=True)
    )
    workspaces = Workspace.objects.filter(
        organization=org,
        id__in=user_workspace_ids,
        is_archived=False,
    ).order_by("name")

    # Workspace filter
    selected_ws_ids = request.GET.getlist("workspace")
    filtered_workspaces = workspaces.filter(id__in=selected_ws_ids) if selected_ws_ids else workspaces

    target_date_str = request.GET.get("date")
    if target_date_str:
        try:
            target_date = date.fromisoformat(target_date_str)
        except (ValueError, TypeError):
            target_date = date.today()
    else:
        target_date = date.today()

    year, month = target_date.year, target_date.month
    cal = cal_mod.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)
    first_day = weeks[0][0]
    last_day = weeks[-1][6]

    # Get posts across all filtered workspaces
    posts = (
        Post.objects.filter(
            workspace__in=filtered_workspaces,
            scheduled_at__date__gte=first_day,
            scheduled_at__date__lte=last_day,
        )
        .select_related("workspace", "author")
        .prefetch_related("platform_posts__social_account")
        .order_by("scheduled_at")
    )

    # Group by date
    posts_by_date = defaultdict(list)
    for post in posts:
        if post.scheduled_at:
            posts_by_date[post.scheduled_at.date()].append(post)

    # Workspace colors for legend
    workspace_colors = {}
    for ws in workspaces:
        workspace_colors[str(ws.id)] = ws.primary_color or "#F97316"

    calendar_weeks = []
    for week in weeks:
        week_data = []
        for day in week:
            day_posts = posts_by_date.get(day, [])
            week_data.append(
                {
                    "date": day,
                    "is_current_month": day.month == month,
                    "is_today": day == date.today(),
                    "posts": day_posts[:5],
                    "total_posts": len(day_posts),
                    "overflow": max(0, len(day_posts) - 5),
                }
            )
        calendar_weeks.append(week_data)

    prev_month = (date(year, month, 1) - timedelta(days=1)).replace(day=1)
    next_month = (date(year, month, 28) + timedelta(days=4)).replace(day=1)

    context = {
        "organization": org,
        "workspaces": workspaces,
        "selected_workspace_ids": selected_ws_ids,
        "workspace_colors": workspace_colors,
        "calendar_weeks": calendar_weeks,
        "period_label": date(year, month, 1).strftime("%B %Y"),
        "prev_date": prev_month.isoformat(),
        "next_date": next_month.isoformat(),
        "target_date": target_date,
        "day_names": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "settings_active": "calendars",
    }
    return render(request, "organizations/cross_calendar.html", context)
