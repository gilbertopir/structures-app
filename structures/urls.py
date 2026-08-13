from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="structure_list", permanent=False)),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("structures/", views.structure_list, name="structure_list"),
    path("culverts/", views.culvert_list, name="culvert_list"),
    path("data/", views.data_view, name="data_view"),
    path("asset/<str:structure_code>/", views.asset_detail, name="asset_detail"),
    path(
        "asset/<str:structure_code>/section/<str:section_key>/commit/",
        views.commit_section,
        name="commit_section",
    ),
    path("export/", views.export_page, name="export_page"),
    path("export/all.xlsx", views.export_full_excel, name="export_full_excel"),
    path(
        "export/asset/<str:structure_code>.zip",
        views.export_asset,
        name="export_asset",
    ),
]
