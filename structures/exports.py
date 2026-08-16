"""
Export builders: per-asset zip (photos + that asset's Excel) and a
full-database Excel covering every asset.

Column order everywhere comes from sections.py via all_fields(), so an
export never needs editing when the engineers change a field list.

There is deliberately no 'all photos' download. Exports are per asset
because the asset is the unit of work — which also means no archive
ever approaches the size where it would need splitting into volumes.
"""

import os
import tempfile
import zipfile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import Asset, Inspection
from .sections import get_sections

HEADER_FILL = PatternFill("solid", fgColor="0D6EFD")
HEADER_FILL_CUL = PatternFill("solid", fgColor="0D9488")
HEADER_FONT = Font(bold=True, color="FFFFFF")
SECTION_FILL = PatternFill("solid", fgColor="E9ECEF")
SECTION_FONT = Font(bold=True)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _field_label(model, field_name):
    """Human label for a model field, falling back to the name."""
    try:
        return model._meta.get_field(field_name).verbose_name
    except Exception:
        return field_name.replace("_", " ").capitalize()


def _display_value(data, field_name):
    """Value for export, using the display form of choice fields."""
    if data is None:
        return ""
    getter = getattr(data, f"get_{field_name}_display", None)
    if callable(getter):
        return getter() or ""
    value = getattr(data, field_name, None)
    return "" if value is None else value


def _autosize(worksheet, max_width=50):
    for column in worksheet.columns:
        longest = 0
        letter = get_column_letter(column[0].column)
        for cell in column:
            if cell.value is not None:
                longest = max(longest, len(str(cell.value)))
        worksheet.column_dimensions[letter].width = min(longest + 2, max_width)


def _inspection_for(asset, visit):
    return (
        Inspection.objects.filter(asset=asset, visit=visit)
        .prefetch_related("photos", "section_progress")
        .first()
    )


# ---------------------------------------------------------------------
# Per-asset workbook
# ---------------------------------------------------------------------
def build_asset_workbook(asset, visit):
    """One asset laid out vertically: section heading, then field rows.

    Vertical rather than a single wide row because this is read by a
    person looking at one structure, not filtered across thirty.
    """
    inspection = _inspection_for(asset, visit)
    data = inspection.data if inspection else None
    coverage = inspection.section_coverage() if inspection else {}
    model = type(data) if data is not None else None

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = asset.structure_code[:31]

    fill = HEADER_FILL if asset.asset_type == "STR" else HEADER_FILL_CUL

    worksheet["A1"] = asset.structure_code
    worksheet["A1"].font = Font(bold=True, size=14)
    worksheet.merge_cells("A1:C1")

    meta_rows = [
        ("Type", asset.get_asset_type_display()),
        ("Source", "Added on site" if asset.is_user_created else "Asset register"),
        ("Type details", asset.type_details),
        ("Route", f"{asset.route_new} ({asset.route_old})".strip(" ()")),
        ("Batch", asset.batch),
        ("Visit", visit),
        ("Status", inspection.get_status_display() if inspection else "Not started"),
        (
            "Fields recorded",
            f"{inspection.coverage[0]} of {inspection.coverage[1]}"
            if inspection
            else "0",
        ),
        (
            "Inspection complete",
            "Yes" if inspection and inspection.is_complete else "No",
        ),
        ("Latitude", asset.latitude if asset.latitude is not None else ""),
        ("Longitude", asset.longitude if asset.longitude is not None else ""),
        ("Google Maps", asset.google_maps_url),
        (
            "Last updated",
            inspection.updated_at.strftime("%d/%m/%Y %H:%M") if inspection else "",
        ),
    ]

    row = 3
    for label, value in meta_rows:
        worksheet.cell(row=row, column=1, value=label).font = SECTION_FONT
        worksheet.cell(row=row, column=2, value=value)
        row += 1

    row += 1

    for section in get_sections(asset.asset_type):
        heading = worksheet.cell(row=row, column=1, value=section["label"].upper())
        heading.fill = fill
        heading.font = HEADER_FONT
        worksheet.cell(row=row, column=2).fill = fill
        worksheet.cell(row=row, column=3).fill = fill

        filled, total_fields = coverage.get(section["key"], (0, 0))
        status_cell = worksheet.cell(
            row=row,
            column=3,
            value=f"{filled}/{total_fields} recorded" if total_fields else "",
        )
        status_cell.font = HEADER_FONT
        status_cell.alignment = Alignment(horizontal="right")
        row += 1

        for field_name in section["fields"]:
            label = _field_label(model, field_name) if model else field_name
            worksheet.cell(row=row, column=1, value=str(label).capitalize())
            worksheet.cell(row=row, column=2, value=_display_value(data, field_name))
            row += 1

        photos = (
            [p for p in inspection.photos.all() if p.section_key == section["key"]]
            if inspection
            else []
        )
        if photos:
            worksheet.cell(row=row, column=1, value="Photos").font = SECTION_FONT
            worksheet.cell(
                row=row,
                column=2,
                value=", ".join(os.path.basename(p.photo.name) for p in photos),
            )
            row += 1

        row += 1

    _autosize(worksheet)
    return workbook


# ---------------------------------------------------------------------
# Full-database workbook
# ---------------------------------------------------------------------
def build_full_workbook(visit):
    """Every asset, one row each, on a sheet per asset type.

    Wide format here because this one is for filtering and comparing
    across the whole survey.
    """
    workbook = Workbook()
    workbook.remove(workbook.active)

    summary = workbook.create_sheet("Summary")
    summary_headers = [
        "Structure code", "Type", "Type details", "Batch", "New route",
        "Old route", "Status", "Complete", "Fields recorded", "Fields total",
        "Coverage %", "Photos", "Latitude", "Longitude", "Last updated",
        "Updated by",
    ]
    summary.append(summary_headers)
    for index in range(1, len(summary_headers) + 1):
        cell = summary.cell(row=1, column=index)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    for asset_type in ("STR", "CUL"):
        sections = get_sections(asset_type)
        sheet = workbook.create_sheet(
            "Structures" if asset_type == "STR" else "Culverts"
        )

        base_headers = [
            "Structure code", "Type details", "Batch", "New route", "Old route",
            "Status", "Complete", "Coverage %", "Source", "Latitude", "Longitude",
        ]
        field_headers = []
        field_names = []
        model = None

        assets = Asset.objects.filter(asset_type=asset_type, is_active=True)

        for asset in assets:
            inspection = _inspection_for(asset, visit)
            if inspection and inspection.data is not None:
                model = type(inspection.data)
                break

        for section in sections:
            for field_name in section["fields"]:
                label = _field_label(model, field_name) if model else field_name
                field_headers.append(f"{section['label']} — {str(label).capitalize()}")
                field_names.append(field_name)
            field_headers.append(f"{section['label']} — Photos")
            field_names.append(("__photos__", section["key"]))

        headers = base_headers + field_headers
        sheet.append(headers)
        fill = HEADER_FILL if asset_type == "STR" else HEADER_FILL_CUL
        for index in range(1, len(headers) + 1):
            cell = sheet.cell(row=1, column=index)
            cell.fill = fill
            cell.font = HEADER_FONT
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.freeze_panes = "B2"

        for asset in assets:
            inspection = _inspection_for(asset, visit)
            data = inspection.data if inspection else None
            photos = list(inspection.photos.all()) if inspection else []

            row = [
                asset.structure_code,
                asset.type_details,
                asset.batch,
                asset.route_new,
                asset.route_old,
                inspection.get_status_display() if inspection else "Not started",
                "Yes" if inspection and inspection.is_complete else "No",
                inspection.coverage_percent if inspection else 0,
                "Site" if asset.is_user_created else "Register",
                asset.latitude if asset.latitude is not None else "",
                asset.longitude if asset.longitude is not None else "",
            ]

            for field_name in field_names:
                if isinstance(field_name, tuple):
                    key = field_name[1]
                    names = [
                        os.path.basename(p.photo.name)
                        for p in photos
                        if p.section_key == key
                    ]
                    row.append(", ".join(names))
                else:
                    row.append(_display_value(data, field_name))

            sheet.append(row)

            summary.append(
                [
                    asset.structure_code,
                    asset.asset_type,
                    asset.type_details,
                    asset.batch,
                    asset.route_new,
                    asset.route_old,
                    inspection.get_status_display() if inspection else "Not started",
                    "Yes" if inspection and inspection.is_complete else "No",
                    inspection.coverage[0] if inspection else 0,
                    inspection.coverage[1] if inspection else 0,
                    inspection.coverage_percent if inspection else 0,
                    len(photos),
                    asset.latitude if asset.latitude is not None else "",
                    asset.longitude if asset.longitude is not None else "",
                    inspection.updated_at.strftime("%d/%m/%Y %H:%M")
                    if inspection
                    else "",
                    inspection.updated_by.username
                    if inspection and inspection.updated_by
                    else "",
                ]
            )

        _autosize(sheet, max_width=28)

    _autosize(summary)
    summary.freeze_panes = "A2"
    return workbook


# ---------------------------------------------------------------------
# Per-asset zip
# ---------------------------------------------------------------------
def build_asset_zip(asset, visit):
    """Photos plus the asset's own workbook, written to a temp file.

    Returns the path; the caller is responsible for deleting it once
    the response has been sent.
    """
    inspection = _inspection_for(asset, visit)
    photos = list(inspection.photos.all()) if inspection else []

    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    handle.close()

    with zipfile.ZipFile(handle.name, "w", zipfile.ZIP_DEFLATED) as archive:
        workbook = build_asset_workbook(asset, visit)
        excel_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        excel_temp.close()
        workbook.save(excel_temp.name)
        archive.write(excel_temp.name, f"{asset.structure_code}/{asset.structure_code}.xlsx")
        os.unlink(excel_temp.name)

        for photo in photos:
            if not photo.photo:
                continue
            try:
                source = photo.photo.path
            except Exception:
                continue
            if not os.path.isfile(source):
                continue
            archive.write(
                source,
                f"{asset.structure_code}/{photo.section_key}/"
                f"{os.path.basename(photo.photo.name)}",
            )

    return handle.name


def asset_photo_stats(asset, visit):
    """(photo_count, total_bytes) so the page can label the button honestly."""
    inspection = _inspection_for(asset, visit)
    if inspection is None:
        return 0, 0

    count = 0
    total = 0
    for photo in inspection.photos.all():
        if not photo.photo:
            continue
        count += 1
        try:
            total += os.path.getsize(photo.photo.path)
        except Exception:
            pass
    return count, total
