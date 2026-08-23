from backend.models import Category, ToolName
from backend.resource_templates import (
    detect_category,
    get_resources_for_category,
    match_admin_resource,
    match_template,
    render_name,
)


def test_detect_category_projet():
    assert detect_category("Projet Refonte Site") == Category.PROJET
    assert detect_category("projet-refonte-site") == Category.PROJET
    assert detect_category("PROJET_Foo") == Category.PROJET


def test_detect_category_pole_with_and_without_accent():
    assert detect_category("Pole Communication") == Category.POLE
    assert detect_category("Pôle Communication") == Category.POLE
    assert detect_category("pole-communication") == Category.POLE


def test_detect_category_antenne():
    assert detect_category("Antenne Rennes") == Category.ANTENNE
    assert detect_category("antenne-lyon") == Category.ANTENNE


def test_detect_category_none_for_unrecognized_prefix():
    assert detect_category("Random Group Name") is None
    assert detect_category("authentik Admins") is None


def test_detect_category_does_not_match_substring_not_at_start():
    # "Projet" appearing later in the name must not count as a prefix match.
    assert detect_category("Ancien Projet Foo") is None


def test_render_name():
    assert render_name("{base_name}", "Projet X") == "Projet X"
    assert render_name("{base_name} Admin", "Projet X") == "Projet X Admin"


def test_match_template_suffix():
    assert match_template("Projet X Admin", "{base_name} Admin") == "Projet X"
    assert match_template("Projet X", "{base_name} Admin") is None
    assert match_template("Admin", "{base_name} Admin") is None  # empty base_name


def test_match_template_identity():
    assert match_template("Projet X", "{base_name}") == "Projet X"


def test_get_resources_for_category_projet_has_admin_channel():
    resources = get_resources_for_category(Category.PROJET)
    tools = {r.tool for r in resources}
    assert ToolName.OUTLINE in tools
    assert ToolName.MATTERMOST in tools
    assert ToolName.MATTERMOST_ADMIN in tools

    admin_resource = next(r for r in resources if r.tool == ToolName.MATTERMOST_ADMIN)
    assert admin_resource.is_admin is True
    assert admin_resource.trigger_tool == ToolName.MATTERMOST


def test_get_resources_for_category_pole_has_no_admin_channel():
    resources = get_resources_for_category(Category.POLE)
    tools = {r.tool for r in resources}
    assert ToolName.MATTERMOST_ADMIN not in tools
    assert not any(r.is_admin for r in resources)


def test_get_resources_for_category_antenne_has_no_admin_channel():
    resources = get_resources_for_category(Category.ANTENNE)
    assert not any(r.is_admin for r in resources)


def test_get_resources_for_uncategorized_falls_back_to_default_list():
    resources = get_resources_for_category(None)
    tools = {r.tool for r in resources}
    assert ToolName.OUTLINE in tools
    assert ToolName.MATTERMOST in tools


def test_match_admin_resource_finds_projet_admin_channel():
    match = match_admin_resource(Category.PROJET, "Projet Refonte Site Admin")
    assert match is not None
    resource_spec, base_name = match
    assert resource_spec.tool == ToolName.MATTERMOST_ADMIN
    assert base_name == "Projet Refonte Site"


def test_match_admin_resource_none_for_non_admin_name():
    assert match_admin_resource(Category.PROJET, "Projet Refonte Site") is None


def test_match_admin_resource_none_for_pole():
    assert match_admin_resource(Category.POLE, "Pole Communication Admin") is None
