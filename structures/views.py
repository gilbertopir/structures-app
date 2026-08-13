from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from .models import Asset, Inspection
from .sections import get_sections, section_count

# The visit this survey round belongs to. Lives here for now; move to
# settings or a picker when a second round starts.
CURRENT_VISIT = "Visit 2"

# Accent colours per asset type — blue for structures, teal for culverts.
ACCENTS = {
    "STR": {"accent": "#0d6efd", "accent_soft": "#e7f1ff"},
    "CUL": {"accent": "#0d9488", "accent_soft": "#dff5f2"},
}

PAGE_META = {
    "STR": {"title": "Structures", "icon": "bi-bank"},
    "CUL": {"title": "Culverts", "icon": "bi-water"},
}


# ---------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------
def login_view(request):
    if request.user.is_authenticated:
        return redirect("structure_list")

    error = None
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username", "").strip(),
            password=request.POST.get("password", ""),
        )
        if user is not None:
            login(request, user)
            return redirect("structure_list")
        error = "Incorrect username or password."

    return render(request, "login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _inspection_map(asset_type):
    """{asset_id: (status, completed_sections)} for the current visit."""
    inspections = (
        Inspection.objects.filter(visit=CURRENT_VISIT, asset__asset_type=asset_type)
        .annotate(done=Count("section_progress", filter=None, distinct=True))
        .select_related("asset")
    )
    result = {}
    for inspection in inspections:
        result[inspection.asset_id] = (
            inspection.status,
            inspection.completed_section_count,
        )
    return result


def _asset_rows(asset_type):
    """Asset list decorated with inspection status and progress."""
    total = section_count(asset_type)
    statuses = _inspection_map(asset_type)
    rows = []
    for asset in Asset.objects.filter(asset_type=asset_type, is_active=True):
        status, done = statuses.get(asset.id, ("not_started", 0))
        rows.append({"asset": asset, "status": status, "done": done, "total": total})
    return rows


# ---------------------------------------------------------------------
# Asset list tabs
# ---------------------------------------------------------------------
@login_required
def asset_list(request, asset_type):
    rows = _asset_rows(asset_type)
    context = {
        "assets": rows,
        "asset_type": asset_type,
        "visit": CURRENT_VISIT,
        "page_title": PAGE_META[asset_type]["title"],
        "page_icon": PAGE_META[asset_type]["icon"],
        "started_count": sum(1 for r in rows if r["status"] != "not_started"),
        "complete_count": sum(1 for r in rows if r["status"] == "complete"),
        **ACCENTS[asset_type],
    }
    return render(request, "asset_list.html", context)


@login_required
def structure_list(request):
    return asset_list(request, "STR")


@login_required
def culvert_list(request):
    return asset_list(request, "CUL")


# ---------------------------------------------------------------------
# Asset detail — section overview (capture comes next)
# ---------------------------------------------------------------------
@login_required
def asset_detail(request, structure_code):
    asset = get_object_or_404(Asset, structure_code=structure_code.upper())

    inspection = Inspection.objects.filter(asset=asset, visit=CURRENT_VISIT).first()
    complete_keys = inspection.completed_section_keys if inspection else set()

    sections = [
        {
            "key": section["key"],
            "label": section["label"],
            "icon": section["icon"],
            "photos": section["photos"],
            "field_count": len(section["fields"]),
            "is_complete": section["key"] in complete_keys,
        }
        for section in get_sections(asset.asset_type)
    ]

    total = len(sections)
    done = len(complete_keys)

    context = {
        "asset": asset,
        "inspection": inspection,
        "sections": sections,
        "done": done,
        "total": total,
        "percent": int(done / total * 100) if total else 0,
        **ACCENTS.get(asset.asset_type, ACCENTS["STR"]),
    }
    return render(request, "asset_detail.html", context)


# ---------------------------------------------------------------------
# Data tab — only assets with something recorded
# ---------------------------------------------------------------------
@login_required
def data_view(request):
    inspections = (
        Inspection.objects.filter(visit=CURRENT_VISIT)
        .exclude(status="not_started")
        .select_related("asset", "updated_by")
        .annotate(photo_count=Count("photos", distinct=True))
        .order_by("asset__structure_code")
    )

    rows = []
    photo_total = 0
    for inspection in inspections:
        photo_total += inspection.photo_count
        rows.append(
            {
                "asset": inspection.asset,
                "inspection": inspection,
                "done": inspection.completed_section_count,
                "total": inspection.total_section_count,
                "photos": inspection.photo_count,
            }
        )

    context = {
        "rows": rows,
        "visit": CURRENT_VISIT,
        "str_count": sum(1 for r in rows if r["asset"].asset_type == "STR"),
        "cul_count": sum(1 for r in rows if r["asset"].asset_type == "CUL"),
        "photo_count": photo_total,
    }
    return render(request, "data_view.html", context)
