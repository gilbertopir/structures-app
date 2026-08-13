from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html

from .models import (
    Asset,
    CulvertData,
    Inspection,
    InspectionPhoto,
    SectionProgress,
    StructureData,
    UserProfile,
)
from .sections import get_sections


def fieldsets_from_sections(asset_type):
    """Build admin fieldsets from the section definitions.

    Keeps the admin layout in step with sections.py automatically -
    change a section there and this follows, no admin edit needed.
    """
    return [
        (section["label"], {"fields": section["fields"], "classes": ["collapse"]})
        for section in get_sections(asset_type)
    ]


# ---------------------------------------------------------------------
# UserProfile on the User form
# ---------------------------------------------------------------------
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile"


class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]
    list_display = ("username", "email", "get_role", "is_staff", "is_active")

    @admin.display(description="Role")
    def get_role(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.get_role_display() if profile else "-"


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# ---------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------
@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = (
        "structure_code",
        "asset_type",
        "type_details",
        "batch",
        "route_new",
        "route_old",
        "has_coords",
        "maps_link",
        "is_active",
    )
    list_filter = ("asset_type", "batch", "route_new", "is_active")
    search_fields = ("structure_code", "type_details", "route_new", "route_old")
    ordering = ("structure_code",)
    readonly_fields = ("asset_type",)
    fieldsets = (
        (None, {"fields": ("structure_code", "asset_type", "type_details", "is_active")}),
        ("Route", {"fields": ("batch", "route_new", "route_old")}),
        ("Location", {"fields": ("google_maps_url", "latitude", "longitude")}),
    )

    @admin.display(description="Coords", boolean=True)
    def has_coords(self, obj):
        return obj.latitude is not None and obj.longitude is not None

    @admin.display(description="Map")
    def maps_link(self, obj):
        if not obj.google_maps_url:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Open</a>', obj.google_maps_url
        )


# ---------------------------------------------------------------------
# Inspection detail inlines
# ---------------------------------------------------------------------
class StructureDataInline(admin.StackedInline):
    model = StructureData
    can_delete = False
    verbose_name_plural = "Structure data"
    fieldsets = fieldsets_from_sections("STR")


class CulvertDataInline(admin.StackedInline):
    model = CulvertData
    can_delete = False
    verbose_name_plural = "Culvert data"
    fieldsets = fieldsets_from_sections("CUL")


class SectionProgressInline(admin.TabularInline):
    model = SectionProgress
    extra = 0
    fields = ("section_key", "is_complete", "saved_by", "saved_at")
    readonly_fields = ("saved_at",)


class InspectionPhotoInline(admin.TabularInline):
    model = InspectionPhoto
    extra = 0
    fields = ("thumbnail", "section_key", "photo", "caption", "order", "uploaded_at")
    readonly_fields = ("thumbnail", "uploaded_at")

    @admin.display(description="Preview")
    def thumbnail(self, obj):
        if not obj.pk or not obj.photo:
            return "-"
        return format_html(
            '<img src="{}" style="max-height:80px;border-radius:4px" />', obj.photo.url
        )


# ---------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------
@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = (
        "structure_code",
        "asset_type_display",
        "visit",
        "status",
        "progress",
        "updated_by",
        "updated_at",
    )
    list_filter = ("status", "visit", "asset__asset_type", "asset__batch")
    search_fields = ("asset__structure_code", "asset__type_details")
    autocomplete_fields = ("asset",)
    readonly_fields = ("created_at", "updated_at", "progress")
    date_hierarchy = "updated_at"

    @admin.display(description="Asset", ordering="asset__structure_code")
    def structure_code(self, obj):
        return obj.asset.structure_code

    @admin.display(description="Type", ordering="asset__asset_type")
    def asset_type_display(self, obj):
        return obj.asset.asset_type

    @admin.display(description="Sections")
    def progress(self, obj):
        if not obj.pk:
            return "-"
        return f"{obj.completed_section_count} / {obj.total_section_count}"

    def get_inline_instances(self, request, obj=None):
        """Show only the detail inline matching the asset type.

        A new Inspection has no asset yet, so on the add form only the
        progress and photo inlines appear; the data inline shows once
        the record is saved and the type is known.
        """
        inlines = []
        if obj is not None:
            if obj.asset.asset_type == "STR":
                inlines.append(StructureDataInline)
            elif obj.asset.asset_type == "CUL":
                inlines.append(CulvertDataInline)
            inlines.append(SectionProgressInline)
            inlines.append(InspectionPhotoInline)
        return [inline(self.model, self.admin_site) for inline in inlines]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("asset", "updated_by")


# ---------------------------------------------------------------------
# Photos - standalone view, useful for spotting orphans
# ---------------------------------------------------------------------
@admin.register(InspectionPhoto)
class InspectionPhotoAdmin(admin.ModelAdmin):
    list_display = ("thumbnail", "inspection", "section_key", "caption", "uploaded_at")
    list_filter = ("section_key", "inspection__asset__asset_type")
    search_fields = ("inspection__asset__structure_code", "caption")
    readonly_fields = ("uploaded_at",)

    @admin.display(description="Preview")
    def thumbnail(self, obj):
        if not obj.photo:
            return "-"
        return format_html(
            '<img src="{}" style="max-height:60px;border-radius:4px" />', obj.photo.url
        )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("inspection__asset")


admin.site.site_header = "Structures & Culverts Inspection"
admin.site.site_title = "Structures Inspection"
admin.site.index_title = "Survey administration"
