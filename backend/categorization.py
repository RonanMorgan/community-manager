"""
Detects a group's category (Projet / Pôle / Antenne) from its Authentik
group name, and handles the special "<Projet name> Admin" naming
convention: an admin-suffixed Projet group is not a group of its own in
this app — it's the admin channel of its parent Projet group.

Kept as a standalone module (no DB/HTTP dependencies) so the naming logic
is easy to unit test in isolation from the sync endpoint.
"""
import re
import unicodedata

from backend.models import Category

# Recognized prefixes, keyed by their normalized (lowercase, no accents) form.
_PREFIX_TO_CATEGORY = {
    "projet": Category.PROJET,
    "pole": Category.POLE,  # matches both "Pole" and "Pôle" once accents are stripped
    "antenne": Category.ANTENNE,
}

_ADMIN_SUFFIX_RE = re.compile(r"[\s_-]*admin$", re.IGNORECASE)


def _normalize(text: str) -> str:
    """Lowercase and strip accents, e.g. 'Pôle' -> 'pole'."""
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return stripped.strip().lower()


def detect_category(group_name: str) -> Category | None:
    """
    Returns the category detected from the group's name prefix (first
    "word", split on space/hyphen/underscore), or None if the name doesn't
    start with a recognized prefix — these are the "uncategorized" groups
    the admin assigns a category to manually.
    """
    normalized = _normalize(group_name)
    first_token = re.split(r"[\s_-]+", normalized, maxsplit=1)[0]
    return _PREFIX_TO_CATEGORY.get(first_token)


def is_admin_suffixed(group_name: str) -> bool:
    """True if the (already Projet-categorized) group name ends with
    "admin" (e.g. 'Projet Refonte Site Admin', 'Projet-Foo-admin')."""
    return bool(_ADMIN_SUFFIX_RE.search(group_name.strip()))


def strip_admin_suffix(group_name: str) -> str:
    """Removes the trailing admin token + its separator, to get the parent
    project's name, e.g. 'Projet Refonte Site Admin' -> 'Projet Refonte Site'."""
    return _ADMIN_SUFFIX_RE.sub("", group_name.strip()).strip()
