import os
import tempfile

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .exports import (
    _display_value,
    _field_label,
    asset_photo_stats,
    build_asset_zip,
    build_full_workbook,
)
from .forms import build_section_form
from .models import Asset, Inspection, InspectionPhoto, SectionProgress
from .sections import (
    get_sections,
    is_valid_section,
    photo_limit,
)

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

# Runaway guard only — the real constraint is the per-commit-cycle
# allowance in sections.py, applied in the browser.
MAX_PHOTOS_PER_SECTION = 100


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
def _asset_rows(asset_type):
    """Assets with their recorded-field coverage for the current visit."""
    inspections = {
        inspection.asset_id: inspection
        for inspection in Inspection.objects.filter(
            visit=CURRENT_VISIT, asset__asset_type=asset_type
        )
    }
    rows = []
    for asset in Asset.objects.filter(asset_type=asset_type, is_active=True):
        inspection = inspections.get(asset.id)
        if inspection is None:
            rows.append(
                {
                    "asset": asset,
                    "status": "not_started",
                    "filled": 0,
                    "total": 0,
                    "percent": 0,
                    "is_complete": False,
                }
            )
            continue
        filled, total = inspection.coverage
        rows.append(
            {
                "asset": asset,
                "status": inspection.status,
                "filled": filled,
                "total": total,
                "percent": inspection.coverage_percent,
                "is_complete": inspection.is_complete,
            }
        )
    return rows


def _get_or_create_inspection(asset, user):
    """The inspection record exists from the moment an asset is opened.

    That is what makes every later save a small update rather than an
    all-or-nothing submission.
    """
    inspection, _ = Inspection.objects.get_or_create(
        asset=asset,
        visit=CURRENT_VISIT,
        defaults={"created_by": user if user.is_authenticated else None},
    )
    return inspection


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
        "complete_count": sum(1 for r in rows if r["is_complete"]),
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
# Capture — hub and sections, all in one page load
# ---------------------------------------------------------------------
@login_required
def asset_detail(request, structure_code):
    """Every section is rendered up front and switched with JS.

    Loading sections as separate pages would mean two network round
    trips per section — twenty for a structure — each one a chance to
    stall on bad signal. One load, then nothing touches the network
    until a commit.
    """
    asset = get_object_or_404(Asset, structure_code=structure_code.upper())
    inspection = _get_or_create_inspection(asset, request.user)

    saved = {
        record.section_key: record for record in inspection.section_progress.all()
    }

    photos_by_section = {}
    for photo in inspection.photos.all():
        photos_by_section.setdefault(photo.section_key, []).append(photo)

    data_instance = inspection.data

    coverage = inspection.section_coverage()

    sections = []
    for section in get_sections(asset.asset_type):
        key = section["key"]
        record = saved.get(key)
        filled, total_fields = coverage.get(key, (0, 0))
        sections.append(
            {
                "key": key,
                "label": section["label"],
                "icon": section["icon"],
                "photos": section["photos"],
                "filled": filled,
                "countable": total_fields,
                "percent": int(filled / total_fields * 100) if total_fields else None,
                "saved_at": record.saved_at if record else None,
                "existing_photos": photos_by_section.get(key, []),
                "photo_count": len(photos_by_section.get(key, [])),
                "form": build_section_form(
                    asset.asset_type, key, instance=data_instance
                ),
            }
        )

    filled, total_fields = inspection.coverage

    context = {
        "asset": asset,
        "inspection": inspection,
        "sections": sections,
        "filled": filled,
        "total_fields": total_fields,
        "percent": inspection.coverage_percent,
        **ACCENTS.get(asset.asset_type, ACCENTS["STR"]),
    }
    return render(request, "capture.html", context)


@login_required
@require_POST
def commit_section(request, structure_code, section_key):
    """Save one section and mark it complete. Returns JSON.

    Only this section's fields are bound, so committing Parapet can
    never overwrite what Masonry holds.
    """
    asset = get_object_or_404(Asset, structure_code=structure_code.upper())

    if not is_valid_section(asset.asset_type, section_key):
        return JsonResponse(
            {"ok": False, "error": "Unknown section for this asset type."}, status=400
        )

    profile = getattr(request.user, "profile", None)
    if profile is not None and profile.is_reviewer():
        return JsonResponse(
            {"ok": False, "error": "Your account is read only."}, status=403
        )

    inspection = _get_or_create_inspection(asset, request.user)

    with transaction.atomic():
        form = build_section_form(
            asset.asset_type,
            section_key,
            instance=inspection.data,
            data=request.POST,
        )

        if form is None:
            return JsonResponse(
                {"ok": False, "error": "Could not build this section."}, status=400
            )

        if not form.is_valid():
            return JsonResponse({"ok": False, "errors": form.errors}, status=400)

        form.save()

        SectionProgress.objects.update_or_create(
            inspection=inspection,
            section_key=section_key,
            defaults={"saved_by": request.user},
        )

        inspection.updated_by = request.user
        inspection.save(update_fields=["updated_by", "updated_at"])
        inspection.refresh_status()

    coverage = inspection.section_coverage()
    section_filled, section_total = coverage.get(section_key, (0, 0))
    filled, total = inspection.coverage

    return JsonResponse(
        {
            "ok": True,
            "section": section_key,
            "section_filled": section_filled,
            "section_total": section_total,
            "section_percent": (
                int(section_filled / section_total * 100) if section_total else None
            ),
            "filled": filled,
            "total": total,
            "percent": int(filled / total * 100) if total else 0,
            "status": inspection.status,
            "saved_at": timezone.localtime().strftime("%H:%M"),
        }
    )


@login_required
@require_POST
def toggle_complete(request, structure_code):
    """Mark the whole inspection finished, or reopen it.

    Deliberate and asset-level: coverage cannot tell 'no wingwalls on
    this bridge' from 'nobody looked yet', so a person says when the
    structure has been recorded as fully as it warrants.
    """
    asset = get_object_or_404(Asset, structure_code=structure_code.upper())

    rejection = _reject_reviewer(request)
    if rejection is not None:
        return rejection

    inspection = _get_or_create_inspection(asset, request.user)
    inspection.is_complete = not inspection.is_complete
    inspection.completed_at = timezone.now() if inspection.is_complete else None
    inspection.completed_by = request.user if inspection.is_complete else None
    inspection.save(update_fields=["is_complete", "completed_at", "completed_by"])
    inspection.refresh_status()

    return JsonResponse({"ok": True, "is_complete": inspection.is_complete})


# ---------------------------------------------------------------------
# Report — read-only view of everything captured for one asset
# ---------------------------------------------------------------------
@login_required
def asset_report(request, structure_code):
    """One scroll: every section, its values and its photos.

    Empty sections are shown rather than hidden - on a report, knowing
    a section was not inspected is itself information, and hiding it
    would make an incomplete record look finished.
    """
    asset = get_object_or_404(Asset, structure_code=structure_code.upper())
    inspection = Inspection.objects.filter(asset=asset, visit=CURRENT_VISIT).first()

    data = inspection.data if inspection else None
    model = type(data) if data is not None else None
    coverage = inspection.section_coverage() if inspection else {}

    photos_by_section = {}
    if inspection:
        for photo in inspection.photos.all():
            photos_by_section.setdefault(photo.section_key, []).append(photo)

    sections = []
    total_photos = 0
    for section in get_sections(asset.asset_type):
        rows = []
        for field_name in section["fields"]:
            label = _field_label(model, field_name) if model else field_name
            value = _display_value(data, field_name)
            rows.append(
                {
                    "label": str(label).capitalize(),
                    "value": value,
                    "is_blank": value in (None, ""),
                }
            )

        photos = photos_by_section.get(section["key"], [])
        total_photos += len(photos)
        filled, total_fields = coverage.get(section["key"], (0, 0))

        sections.append(
            {
                "key": section["key"],
                "label": section["label"],
                "icon": section["icon"],
                "rows": rows,
                "photos": photos,
                "filled": filled,
                "countable": total_fields,
                "percent": int(filled / total_fields * 100) if total_fields else None,
                "has_values": any(not r["is_blank"] for r in rows),
            }
        )

    filled, total_fields = inspection.coverage if inspection else (0, 0)

    context = {
        "asset": asset,
        "inspection": inspection,
        "sections": sections,
        "filled": filled,
        "total_fields": total_fields,
        "percent": inspection.coverage_percent if inspection else 0,
        "total_photos": total_photos,
        "visit": CURRENT_VISIT,
        **ACCENTS.get(asset.asset_type, ACCENTS["STR"]),
    }
    return render(request, "report.html", context)


# ---------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------
def _reject_reviewer(request):
    """Read-only accounts may browse but not change anything."""
    profile = getattr(request.user, "profile", None)
    if profile is not None and profile.is_reviewer():
        return JsonResponse(
            {"ok": False, "error": "Your account is read only."}, status=403
        )
    return None


@login_required
@require_POST
def upload_photo(request, structure_code, section_key):
    """One photo, one request.

    Photos are sent as soon as they are picked rather than bundled
    with the section commit, so a failure costs a single photo and the
    inspector can carry on while the rest upload behind them.
    """
    asset = get_object_or_404(Asset, structure_code=structure_code.upper())

    rejection = _reject_reviewer(request)
    if rejection is not None:
        return rejection

    if not is_valid_section(asset.asset_type, section_key):
        return JsonResponse(
            {"ok": False, "error": "Unknown section for this asset type."}, status=400
        )

    upload = request.FILES.get("photo")
    if upload is None:
        return JsonResponse({"ok": False, "error": "No photo received."}, status=400)

    inspection = _get_or_create_inspection(asset, request.user)

    # There is no cap on the total number of photos in a section. The
    # per-commit-cycle allowance is enforced in the browser, because it
    # exists to keep any single upload wait short — not to limit how
    # much evidence an inspector can record. The ceiling below is only
    # a runaway guard and should never be reached in normal use.
    existing = inspection.photos.filter(section_key=section_key).count()
    if existing >= MAX_PHOTOS_PER_SECTION:
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    f"This section has reached the safety limit of "
                    f"{MAX_PHOTOS_PER_SECTION} photos."
                ),
            },
            status=400,
        )

    photo = InspectionPhoto.objects.create(
        inspection=inspection,
        section_key=section_key,
        photo=upload,
        order=existing,
        uploaded_by=request.user,
    )

    return JsonResponse(
        {
            "ok": True,
            "id": photo.id,
            "url": photo.photo.url,
            "name": os.path.basename(photo.photo.name),
            "count": existing + 1,
            "batch_limit": photo_limit(asset.asset_type, section_key),
        }
    )


@login_required
@require_POST
def delete_photo(request, structure_code, photo_id):
    asset = get_object_or_404(Asset, structure_code=structure_code.upper())

    rejection = _reject_reviewer(request)
    if rejection is not None:
        return rejection

    photo = get_object_or_404(
        InspectionPhoto,
        id=photo_id,
        inspection__asset=asset,
        inspection__visit=CURRENT_VISIT,
    )
    section_key = photo.section_key
    inspection = photo.inspection
    photo.delete()

    return JsonResponse(
        {
            "ok": True,
            "section": section_key,
            "count": inspection.photos.filter(section_key=section_key).count(),
            "limit": photo_limit(asset.asset_type, section_key),
        }
    )


# ---------------------------------------------------------------------
# Data tab
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
                "percent": inspection.coverage_percent,
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


# ---------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------
def _human_size(num_bytes):
    if num_bytes < 1024:
        return f"{num_bytes} B"
    size = float(num_bytes)
    for unit in ("KB", "MB", "GB"):
        size /= 1024.0
        if size < 1024:
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"


@login_required
def export_page(request):
    """Per-asset downloads plus the full database as one workbook.

    There is no 'all photos' download on purpose - the asset is the
    unit of work, and per-asset archives stay small enough that the
    volume-splitting the PRI app needed never becomes necessary.
    """
    rows = []
    photo_total = 0
    size_total = 0
    started = 0

    for asset in Asset.objects.filter(is_active=True):
        inspection = Inspection.objects.filter(
            asset=asset, visit=CURRENT_VISIT
        ).first()
        count, size = asset_photo_stats(asset, CURRENT_VISIT)
        has_data = bool(inspection and inspection.status != "not_started")

        if has_data:
            started += 1
        photo_total += count
        size_total += size

        rows.append(
            {
                "asset": asset,
                "has_data": has_data,
                "percent": inspection.coverage_percent if inspection else 0,
                "photo_count": count,
                "size_display": _human_size(size),
            }
        )

    context = {
        "rows": rows,
        "visit": CURRENT_VISIT,
        "total_assets": len(rows),
        "started_count": started,
        "photo_total": photo_total,
        "size_total": _human_size(size_total),
    }
    return render(request, "export.html", context)


@login_required
def export_asset(request, structure_code):
    """Zip of one asset: its photos and its own spreadsheet."""
    asset = get_object_or_404(Asset, structure_code=structure_code.upper())
    path = build_asset_zip(asset, CURRENT_VISIT)

    response = FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename=f"{asset.structure_code}_{slugify(CURRENT_VISIT)}.zip",
        content_type="application/zip",
    )
    # Delete the temp file once the response has finished streaming.
    response._resource_closers.append(
        lambda: os.path.exists(path) and os.unlink(path)
    )
    return response


@login_required
def export_full_excel(request):
    """Every asset in one workbook: Summary, Structures, Culverts."""
    workbook = build_full_workbook(CURRENT_VISIT)

    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    handle.close()
    workbook.save(handle.name)

    response = FileResponse(
        open(handle.name, "rb"),
        as_attachment=True,
        filename=f"structures_survey_{slugify(CURRENT_VISIT)}.xlsx",
        content_type=(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        ),
    )
    response._resource_closers.append(
        lambda: os.path.exists(handle.name) and os.unlink(handle.name)
    )
    return response
