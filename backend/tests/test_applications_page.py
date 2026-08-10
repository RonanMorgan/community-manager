from backend.routers.pages import _group_applications_by_section, _resolve_icon_url


def test_group_applications_by_section_groups_and_sorts():
    apps = [
        {"name": "Zeta", "group": "Outils internes"},
        {"name": "Alpha", "group": "Outils internes"},
        {"name": "NoGroup App", "group": ""},
        {"name": "Beta", "group": "Communication"},
    ]
    sections = _group_applications_by_section(apps)
    section_names = [name for name, _ in sections]

    # "Autres" (no group) must be last, other sections alphabetical
    assert section_names == ["Communication", "Outils internes", "Autres"]

    outils_apps = dict(sections)["Outils internes"]
    assert [a["name"] for a in outils_apps] == ["Alpha", "Zeta"]  # sorted within a section


def test_resolve_icon_url_prefers_meta_icon_url(monkeypatch):
    import config

    monkeypatch.setattr(config, "AUTHENTIK_URL", "https://authentik.example.org")
    app = {"meta_icon_url": "https://cdn.example.org/icon.png", "meta_icon": "/media/foo.png"}
    assert _resolve_icon_url(app) == "https://cdn.example.org/icon.png"


def test_resolve_icon_url_falls_back_to_relative_meta_icon(monkeypatch):
    import config

    monkeypatch.setattr(config, "AUTHENTIK_URL", "https://authentik.example.org")
    app = {"meta_icon_url": None, "meta_icon": "/media/application-icons/foo.png"}
    assert _resolve_icon_url(app) == "https://authentik.example.org/media/application-icons/foo.png"


def test_resolve_icon_url_none_when_no_icon():
    assert _resolve_icon_url({}) is None


def test_applications_page_shows_error_when_not_configured(client):
    r = client.get("/applications")
    assert r.status_code == 200
    assert "n&#39;est pas configuré" in r.text or "n'est pas configuré" in r.text
