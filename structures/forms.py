"""
Section forms, generated from sections.py rather than hand-written.

There is no per-section form class in here on purpose. Writing them out
would mean every field name existed in two places - sections.py and a
form - and the two would drift the first time the engineers changed a
field. Instead the field list comes from sections.py and the widget is
chosen from the model field's own type.
"""

from django import forms
from django.db import models as db_models
from django.forms import modelform_factory

from .models import CulvertData, StructureData
from .sections import section_fields

MODEL_FOR_TYPE = {
    "STR": StructureData,
    "CUL": CulvertData,
}

NOTES_ROWS = 3


class SectionFormBase(forms.ModelForm):
    """Base for every generated section form.

    Two behaviours matter here:

    - Nothing is required. A field left blank means 'not recorded',
      which is a legitimate survey result, so validation must never
      block a commit.
    - The empty choice is stripped from radio groups, which would
      otherwise render a pointless blank option above Good/Fair/Poor.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False
            if isinstance(field, forms.ChoiceField):
                field.choices = [c for c in field.choices if c[0] not in ("", None)]

    def is_empty(self):
        """True if every field in this section was left blank."""
        for name in self.fields:
            value = self.cleaned_data.get(name)
            if value not in (None, "", []):
                return False
        return True


def _widget_for(model_field):
    """Pick a mobile-friendly widget from the model field's type."""
    if getattr(model_field, "choices", None):
        return forms.RadioSelect

    if isinstance(model_field, db_models.FloatField):
        # inputmode='decimal' brings up the numeric keypad on a phone
        # without blocking a decimal point the way type=number can.
        return forms.NumberInput(
            attrs={
                "class": "form-control",
                "inputmode": "decimal",
                "step": "any",
                "placeholder": "mm",
            }
        )

    if isinstance(model_field, db_models.TextField):
        return forms.Textarea(attrs={"class": "form-control", "rows": NOTES_ROWS})

    return forms.TextInput(attrs={"class": "form-control"})


def build_section_form_class(asset_type, section_key):
    """ModelForm class for one section, or None if the key is unknown."""
    model = MODEL_FOR_TYPE.get(asset_type)
    fields = section_fields(asset_type, section_key)
    if model is None or not fields:
        return None

    widgets = {}
    for name in fields:
        widgets[name] = _widget_for(model._meta.get_field(name))

    return modelform_factory(
        model, form=SectionFormBase, fields=fields, widgets=widgets
    )


def build_section_form(asset_type, section_key, instance=None, data=None):
    """Bound or unbound form for one section."""
    form_class = build_section_form_class(asset_type, section_key)
    if form_class is None:
        return None
    return form_class(data=data, instance=instance)
