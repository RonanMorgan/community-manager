from backend.categorization import detect_category, is_admin_suffixed, strip_admin_suffix
from backend.models import Category


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


def test_is_admin_suffixed():
    assert is_admin_suffixed("Projet Refonte Site Admin") is True
    assert is_admin_suffixed("Projet Refonte Site admin") is True
    assert is_admin_suffixed("Projet-Refonte-Site-Admin") is True
    assert is_admin_suffixed("Projet Refonte Site") is False
    assert is_admin_suffixed("Projet Administratif") is False  # "Administratif" != "Admin" suffix


def test_strip_admin_suffix():
    assert strip_admin_suffix("Projet Refonte Site Admin") == "Projet Refonte Site"
    assert strip_admin_suffix("Projet-Refonte-Site-Admin") == "Projet-Refonte-Site"
    assert strip_admin_suffix("Projet Refonte Site admin") == "Projet Refonte Site"
