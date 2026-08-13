"""
Single source of truth for the inspection section structure.

Everything downstream reads from here:
  - the order sections appear in the capture wizard
  - the progress indicator ("4 of 10")
  - which fields render in each section
  - the valid section keys for photos and SectionProgress
  - the column order in the Excel export

When the engineers change the field list, change it HERE (plus the
matching model field) and the UI, progress tracking and export follow
automatically.

Each section is a dict:
    key      unique slug, stored in SectionProgress.section_key and
             InspectionPhoto.section_key. Never reuse or rename a key
             once data exists - add a new one instead.
    label    heading shown to the user
    icon     Bootstrap Icons class (matches the PRI app's icon set)
    fields   model field names, in display order
    photos   max photos allowed for this section (0 = no photo control)
"""

# Max photos allowed on any one section unless overridden below.
DEFAULT_SECTION_PHOTO_LIMIT = 3


# ---------------------------------------------------------------------
# STR - bridges and other structures
# ---------------------------------------------------------------------
STR_SECTIONS = [
    {
        "key": "carriageway",
        "label": "Carriageway",
        "icon": "bi-signpost-split",
        "fields": [
            "carriageway_width_mm",
            "carriageway_rhs_verge_width_mm",
            "carriageway_lhs_verge_width_mm",
            "carriageway_notes",
        ],
        "photos": 3,
    },
    {
        "key": "parapet",
        "label": "Parapet",
        "icon": "bi-bricks",
        "fields": [
            "parapet_rhs_length_mm",
            "parapet_rhs_width_mm",
            "parapet_rhs_height_mm",
            "parapet_lhs_length_mm",
            "parapet_lhs_width_mm",
            "parapet_lhs_height_mm",
            "parapet_notes",
        ],
        "photos": 3,
    },
    {
        "key": "soffit_arch",
        "label": "Soffit / arch",
        "icon": "bi-bezier2",
        "fields": [
            "soffit_span_mm",
            "soffit_thickness_mm",
            "soffit_notes",
        ],
        "photos": 3,
    },
    {
        "key": "abutments_pier",
        "label": "Abutments / pier",
        "icon": "bi-building",
        "fields": [
            "abutment_height_mm",
            "abutment_thickness_mm",
            "abutment_notes",
        ],
        "photos": 3,
    },
    {
        "key": "headwall",
        "label": "Headwall",
        "icon": "bi-square",
        "fields": [
            "headwall_height_mm",
            "headwall_notes",
        ],
        "photos": 3,
    },
    {
        "key": "wingwalls",
        "label": "Wingwalls",
        "icon": "bi-arrows-angle-expand",
        "fields": [
            "wingwall_notes",
        ],
        "photos": 3,
    },
    {
        "key": "concrete",
        "label": "Concrete",
        "icon": "bi-box",
        "fields": [
            "concrete_reinforced",
            "concrete_notes",
        ],
        "photos": 3,
    },
    {
        "key": "masonry",
        "label": "Masonry",
        "icon": "bi-grid-3x3",
        "fields": [
            "masonry_block_size_mm",
            "masonry_joint_thickness_mm",
            "masonry_arch_barrel_block_size_mm",
            "masonry_arch_barrel_joint_thickness_mm",
            "masonry_notes",
        ],
        "photos": 3,
    },
    {
        "key": "overall_condition",
        "label": "Overall condition",
        "icon": "bi-clipboard-check",
        "fields": [
            "overall_condition",
            "overall_condition_notes",
        ],
        "photos": 3,
    },
    {
        "key": "general_notes",
        "label": "General notes",
        "icon": "bi-journal-text",
        "fields": [
            "general_notes",
        ],
        "photos": 3,
    },
]


# ---------------------------------------------------------------------
# CUL - culverts
# ---------------------------------------------------------------------
# Note: Box and Pipe are mutually exclusive in reality, but per the
# agreed approach both are shown and the inspector fills whichever
# applies. If that changes, add a culvert_type field and gate here.
CUL_SECTIONS = [
    {
        "key": "carriageway",
        "label": "Carriageway",
        "icon": "bi-signpost-split",
        "fields": [
            "carriageway_width_mm",
            "carriageway_rhs_verge_width_mm",
            "carriageway_lhs_verge_width_mm",
            "carriageway_notes",
        ],
        "photos": 3,
    },
    {
        "key": "headwall",
        "label": "Headwall",
        "icon": "bi-square",
        "fields": [
            "headwall_rhs_length_mm",
            "headwall_rhs_width_mm",
            "headwall_rhs_height_mm",
            "headwall_lhs_length_mm",
            "headwall_lhs_width_mm",
            "headwall_lhs_height_mm",
            "headwall_notes",
        ],
        "photos": 3,
    },
    {
        "key": "box",
        "label": "Box",
        "icon": "bi-bounding-box",
        "fields": [
            "box_span_mm",
            "box_abutment_height_mm",
            "box_slab_depth_mm",
            "box_slab_width_mm",
            "box_cover_depth_mm",
            "box_notes",
        ],
        "photos": 3,
    },
    {
        "key": "pipe",
        "label": "Pipe",
        "icon": "bi-circle",
        "fields": [
            "pipe_diameter_mm",
            "pipe_thickness_mm",
            "pipe_cover_depth_mm",
            "pipe_notes",
        ],
        "photos": 3,
    },
    {
        "key": "overall_condition",
        "label": "Overall condition",
        "icon": "bi-clipboard-check",
        "fields": [
            "overall_condition",
            "overall_condition_notes",
        ],
        "photos": 3,
    },
    {
        "key": "general_notes",
        "label": "General notes",
        "icon": "bi-journal-text",
        "fields": [
            "general_notes",
        ],
        "photos": 3,
    },
]


SECTIONS_BY_TYPE = {
    "STR": STR_SECTIONS,
    "CUL": CUL_SECTIONS,
}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def get_sections(asset_type):
    """Ordered section list for 'STR' or 'CUL'. Empty list if unknown."""
    return SECTIONS_BY_TYPE.get(asset_type, [])


def get_section(asset_type, key):
    """One section dict by key, or None."""
    for section in get_sections(asset_type):
        if section["key"] == key:
            return section
    return None


def section_keys(asset_type):
    """Ordered list of section keys for an asset type."""
    return [s["key"] for s in get_sections(asset_type)]


def section_count(asset_type):
    """How many sections make up a complete inspection."""
    return len(get_sections(asset_type))


def section_fields(asset_type, key):
    """Field names belonging to one section, in display order."""
    section = get_section(asset_type, key)
    return list(section["fields"]) if section else []


def all_fields(asset_type):
    """Every field for an asset type, in section then display order.

    This is the canonical column order for the Excel export.
    """
    fields = []
    for section in get_sections(asset_type):
        fields.extend(section["fields"])
    return fields


def photo_limit(asset_type, key):
    """Max photos allowed on a section."""
    section = get_section(asset_type, key)
    if section is None:
        return 0
    return section.get("photos", DEFAULT_SECTION_PHOTO_LIMIT)


def is_valid_section(asset_type, key):
    """Guard for anything arriving from the client."""
    return get_section(asset_type, key) is not None


def all_section_key_choices():
    """Django choices covering every key across both types.

    Used on SectionProgress and InspectionPhoto, which are shared
    across asset types. Keys common to both (carriageway, headwall,
    overall_condition, general_notes) appear once.
    """
    seen = {}
    for sections in SECTIONS_BY_TYPE.values():
        for section in sections:
            seen.setdefault(section["key"], section["label"])
    return sorted(seen.items())
