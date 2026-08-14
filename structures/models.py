import os
import re

from django.contrib.auth.models import User
from django.db import models

from .sections import all_section_key_choices, countable_fields, get_sections


# ---------------------------------------------------------------------
# Shared choices
# ---------------------------------------------------------------------
ASSET_TYPE_CHOICES = [
    ("STR", "Structure"),
    ("CUL", "Culvert"),
]

CONDITION_CHOICES = [
    ("GOOD", "Good"),
    ("FAIR", "Fair"),
    ("POOR", "Poor"),
]

YES_NO_CHOICES = [
    ("Y", "Yes"),
    ("N", "No"),
]

STATUS_CHOICES = [
    ("not_started", "Not started"),
    ("in_progress", "In progress"),
    ("complete", "Complete"),
]

# Matches the suffix that determines which tab an asset belongs to,
# e.g. B0870-CUL01 -> CUL, U3521-STR06 -> STR
ASSET_CODE_RE = re.compile(r"-(STR|CUL)\d+$", re.IGNORECASE)


def mm(verbose_name):
    """A dimension in millimetres. Null means 'not recorded', not zero."""
    return models.FloatField(verbose_name=verbose_name, null=True, blank=True)


def notes(verbose_name="Notes"):
    return models.TextField(verbose_name=verbose_name, blank=True)


def has_value(value):
    """A field counts as recorded if it holds anything at all."""
    return value not in (None, "", [])


# ---------------------------------------------------------------------
# UserProfile
# ---------------------------------------------------------------------
class UserProfile(models.Model):
    ROLE_CHOICES = [
        ("engineer", "Field Engineer"),
        ("reviewer", "Reviewer (Read Only)"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="engineer")

    def is_engineer(self):
        return self.role == "engineer"

    def is_reviewer(self):
        return self.role == "reviewer"

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


# ---------------------------------------------------------------------
# Asset - reference data, seeded from the asset list spreadsheet
# ---------------------------------------------------------------------
class Asset(models.Model):
    """One row of the asset list. Read-only in the app; loaded by import.

    asset_type is stored rather than parsed at query time so that tab
    filtering is a plain indexed lookup and any malformed code is
    caught once, at import, instead of silently disappearing from a
    tab later.
    """

    structure_code = models.CharField(max_length=30, unique=True, db_index=True)
    asset_type = models.CharField(
        max_length=3, choices=ASSET_TYPE_CHOICES, db_index=True
    )
    type_details = models.CharField(max_length=200, blank=True)
    batch = models.CharField(max_length=10, blank=True)
    route_new = models.CharField(max_length=50, blank=True, verbose_name="New route name")
    route_old = models.CharField(max_length=50, blank=True, verbose_name="Old route name")
    google_maps_url = models.URLField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)

    @staticmethod
    def derive_asset_type(structure_code):
        """'B0870-CUL01' -> 'CUL'. Returns '' if the code doesn't match."""
        match = ASSET_CODE_RE.search(structure_code or "")
        return match.group(1).upper() if match else ""

    def save(self, *args, **kwargs):
        self.structure_code = (self.structure_code or "").strip().upper()
        if not self.asset_type:
            self.asset_type = self.derive_asset_type(self.structure_code)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.structure_code

    class Meta:
        ordering = ["structure_code"]


# ---------------------------------------------------------------------
# Inspection - the thin spine
# ---------------------------------------------------------------------
class Inspection(models.Model):
    """One inspection of one asset on one visit.

    Created as soon as the inspector opens an asset, so every save
    afterwards is a small update to a row that already exists. There
    is no state where a part-filled form lives only in the browser.
    """

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="inspections")
    visit = models.CharField(max_length=30, default="Visit 2", db_index=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="not_started", db_index=True
    )
    # Set deliberately by the engineer when the structure has been
    # recorded as fully as it warrants. Coverage cannot express this:
    # a bridge with no wingwalls will never reach 100% of its fields,
    # and that is a correct result rather than an unfinished one.
    is_complete = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="inspections_completed",
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="inspections_created",
    )
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="inspections_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def asset_type(self):
        return self.asset.asset_type

    @property
    def data(self):
        """The type-specific detail row, creating it on first access."""
        if self.asset_type == "STR":
            obj, _ = StructureData.objects.get_or_create(inspection=self)
        elif self.asset_type == "CUL":
            obj, _ = CulvertData.objects.get_or_create(inspection=self)
        else:
            return None
        return obj

    def section_coverage(self):
        """{section_key: (filled, total)} across countable fields.

        Measures what has actually been recorded rather than whether
        someone pressed a button, so a section left blank because the
        structure has no such element reads as 0 rather than as done.
        """
        data = self.data
        result = {}
        for section in get_sections(self.asset_type):
            fields = countable_fields(self.asset_type, section["key"])
            filled = sum(1 for name in fields if has_value(getattr(data, name, None)))
            result[section["key"]] = (filled, len(fields))
        return result

    @property
    def coverage(self):
        """(filled, total) across every countable field on the asset."""
        filled = total = 0
        for section_filled, section_total in self.section_coverage().values():
            filled += section_filled
            total += section_total
        return filled, total

    @property
    def coverage_percent(self):
        filled, total = self.coverage
        return int(filled / total * 100) if total else 0

    @property
    def has_data(self):
        """True if anything at all has been recorded, notes and photos included."""
        data = self.data
        if data is not None:
            for section in get_sections(self.asset_type):
                for name in section["fields"]:
                    if has_value(getattr(data, name, None)):
                        return True
        return self.photos.exists()

    def refresh_status(self, save=True):
        """Status follows the completion flag, then whether anything exists."""
        if self.is_complete:
            self.status = "complete"
        elif self.has_data:
            self.status = "in_progress"
        else:
            self.status = "not_started"
        if save:
            self.save(update_fields=["status", "updated_at"])
        return self.status

    def __str__(self):
        return f"{self.asset.structure_code} - {self.visit}"

    class Meta:
        ordering = ["asset__structure_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "visit"], name="unique_inspection_per_asset_visit"
            )
        ]


# ---------------------------------------------------------------------
# Field data - fields common to both asset types
# ---------------------------------------------------------------------
class BaseInspectionData(models.Model):
    """Sections that appear on both STR and CUL forms."""

    # --- Carriageway ---
    carriageway_width_mm = mm("Carriageway width (mm)")
    carriageway_rhs_verge_width_mm = mm("RHS verge width (mm)")
    carriageway_lhs_verge_width_mm = mm("LHS verge width (mm)")
    carriageway_notes = notes()

    # --- Overall condition ---
    overall_condition = models.CharField(
        max_length=10, choices=CONDITION_CHOICES, blank=True,
        verbose_name="Overall condition",
    )
    overall_condition_notes = notes()

    # --- General notes ---
    general_notes = notes()

    class Meta:
        abstract = True


class StructureData(BaseInspectionData):
    """STR-only fields. One row per Inspection of a structure."""

    inspection = models.OneToOneField(
        Inspection, on_delete=models.CASCADE, primary_key=True, related_name="str_data"
    )

    # --- Parapet ---
    parapet_rhs_length_mm = mm("RHS parapet length (mm)")
    parapet_rhs_width_mm = mm("RHS parapet width (mm)")
    parapet_rhs_height_mm = mm("RHS parapet height (mm)")
    parapet_lhs_length_mm = mm("LHS parapet length (mm)")
    parapet_lhs_width_mm = mm("LHS parapet width (mm)")
    parapet_lhs_height_mm = mm("LHS parapet height (mm)")
    parapet_notes = notes()

    # --- Soffit / arch ---
    soffit_span_mm = mm("Span (mm)")
    soffit_thickness_mm = mm("Thickness (mm)")
    soffit_notes = notes()

    # --- Abutments / pier ---
    abutment_height_mm = mm("Height (mm)")
    abutment_thickness_mm = mm("Thickness (mm)")
    abutment_notes = notes()

    # --- Headwall ---
    headwall_height_mm = mm("Height (mm)")
    headwall_notes = notes()

    # --- Wingwalls ---
    wingwall_notes = notes()

    # --- Concrete ---
    concrete_reinforced = models.CharField(
        max_length=1, choices=YES_NO_CHOICES, blank=True, verbose_name="Reinforced"
    )
    concrete_notes = notes()

    # --- Masonry ---
    masonry_block_size_mm = mm("Block size (mm)")
    masonry_joint_thickness_mm = mm("Joint thickness (mm)")
    masonry_arch_barrel_block_size_mm = mm("Arch barrel block size (mm)")
    masonry_arch_barrel_joint_thickness_mm = mm("Arch barrel joint thickness (mm)")
    masonry_notes = notes()

    def __str__(self):
        return f"STR data - {self.inspection}"

    class Meta:
        verbose_name = "Structure data"
        verbose_name_plural = "Structure data"


class CulvertData(BaseInspectionData):
    """CUL-only fields. One row per Inspection of a culvert.

    Box and Pipe are mutually exclusive on site but both are offered;
    the inspector fills whichever applies.
    """

    inspection = models.OneToOneField(
        Inspection, on_delete=models.CASCADE, primary_key=True, related_name="cul_data"
    )

    # --- Headwall ---
    headwall_rhs_length_mm = mm("RHS headwall length (mm)")
    headwall_rhs_width_mm = mm("RHS headwall width (mm)")
    headwall_rhs_height_mm = mm("RHS headwall height (mm)")
    headwall_lhs_length_mm = mm("LHS headwall length (mm)")
    headwall_lhs_width_mm = mm("LHS headwall width (mm)")
    headwall_lhs_height_mm = mm("LHS headwall height (mm)")
    headwall_notes = notes()

    # --- Box ---
    box_span_mm = mm("Span (mm)")
    box_abutment_height_mm = mm("Abutment height (mm)")
    box_slab_depth_mm = mm("Slab depth (mm)")
    box_slab_width_mm = mm("Slab width (mm)")
    box_cover_depth_mm = mm("Cover depth (mm)")
    box_notes = notes()

    # --- Pipe ---
    pipe_diameter_mm = mm("Diameter (mm)")
    pipe_thickness_mm = mm("Pipe thickness (mm)")
    pipe_cover_depth_mm = mm("Cover depth (mm)")
    pipe_notes = notes()

    def __str__(self):
        return f"CUL data - {self.inspection}"

    class Meta:
        verbose_name = "Culvert data"
        verbose_name_plural = "Culvert data"


# ---------------------------------------------------------------------
# SectionProgress
# ---------------------------------------------------------------------
class SectionProgress(models.Model):
    """Audit trail of section saves: who committed what, and when.

    No completion flag - completeness is measured from the fields that
    actually hold values. This exists so the app can answer 'did my
    save go through' when someone is standing in a field with one bar
    of signal.
    """

    inspection = models.ForeignKey(
        Inspection, on_delete=models.CASCADE, related_name="section_progress"
    )
    section_key = models.CharField(max_length=40, choices=all_section_key_choices())
    saved_at = models.DateTimeField(auto_now=True)
    saved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="section_saves",
    )

    def __str__(self):
        return f"{self.inspection} / {self.section_key}"

    class Meta:
        verbose_name_plural = "Section progress"
        constraints = [
            models.UniqueConstraint(
                fields=["inspection", "section_key"], name="unique_section_per_inspection"
            )
        ]


# ---------------------------------------------------------------------
# InspectionPhoto
# ---------------------------------------------------------------------
def photo_upload_path(instance, filename):
    """photos/<structure_code>/<section_key>/<filename>"""
    code = instance.inspection.asset.structure_code
    return os.path.join("photos", code, instance.section_key, filename)


class InspectionPhoto(models.Model):
    """A photo tagged to both an asset and the section it belongs to.

    Uploaded one at a time, immediately on selection, never bundled
    with the section save - so one failed upload costs one photo.
    """

    inspection = models.ForeignKey(
        Inspection, on_delete=models.CASCADE, related_name="photos"
    )
    section_key = models.CharField(
        max_length=40, choices=all_section_key_choices(), db_index=True
    )
    photo = models.ImageField(upload_to=photo_upload_path)
    caption = models.CharField(max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="photos"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def delete(self, *args, **kwargs):
        if self.photo and os.path.isfile(self.photo.path):
            os.remove(self.photo.path)
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.inspection} / {self.section_key} #{self.order}"

    class Meta:
        ordering = ["section_key", "order", "uploaded_at"]
