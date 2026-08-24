"""
Loads config/resource_templates.yml: the single source of truth for how
many resources (Outline collections, Mattermost channels...) a group of a
given category gets, and what they're named.

This exists so that changing a naming convention, adding/removing a
resource "slot" for a category, or tweaking which prefixes map to which
category is a YAML edit, not a code change + redeploy. It replaces
config/permissions_matrix.yml from the pre-V0 bot (moved to
docs/legacy_reference/ during the initial cleanup, when nothing loaded it
any more) — same spirit, reintroduced to fit the V0 data model
(Category, ToolName, GroupResource). See CLAUDE.md.

Terminology: a "base_name" is the group's own name with no category
prefix logic applied — for the main Projet/Pôle/Antenne resources this is
just the Authentik group's name itself; for the Projet admin channel,
it's the Authentik group's name MINUS the rendered admin suffix (see
match_admin_template()).
"""
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from backend.models import Category, ToolName

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "resource_templates.yml"

_NAME_PLACEHOLDER = "{base_name}"


@dataclass(frozen=True)
class ResourceSpec:
    tool: ToolName
    name_template: str  # contains "{base_name}" exactly once
    # True for a resource that isn't offered as its own checkbox in the
    # "create group" UI: it's created automatically alongside `trigger_tool`
    # (see CLAUDE.md §6-octies/§6-nonies). During sync, groups matching this
    # resource's rendered name pattern are attached to their base group
    # instead of becoming a Group of their own — see match_admin_template().
    is_admin: bool = False
    trigger_tool: ToolName | None = None  # only meaningful when is_admin=True


@dataclass(frozen=True)
class CategoryConfig:
    category: Category
    detect_prefixes: tuple[str, ...]
    resources: tuple[ResourceSpec, ...]


@dataclass(frozen=True)
class ResourceTemplatesConfig:
    categories: dict[Category, CategoryConfig]
    uncategorized_resources: tuple[ResourceSpec, ...] = field(default_factory=tuple)


def _normalize_token(text: str) -> str:
    """Lowercase and strip accents, e.g. 'Pôle' -> 'pole'."""
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return stripped.strip().lower()


def _parse_resource(raw: dict) -> ResourceSpec:
    template = raw["name_template"]
    if _NAME_PLACEHOLDER not in template:
        raise ValueError(f"resource_templates.yml: name_template '{template}' must contain '{_NAME_PLACEHOLDER}'.")
    return ResourceSpec(
        tool=ToolName(raw["tool"]),
        name_template=template,
        is_admin=bool(raw.get("is_admin", False)),
        trigger_tool=ToolName(raw["trigger_tool"]) if raw.get("trigger_tool") else None,
    )


def _load_from_disk() -> ResourceTemplatesConfig:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    categories: dict[Category, CategoryConfig] = {}
    for category_key, category_data in (raw.get("categories") or {}).items():
        category = Category(category_key)
        categories[category] = CategoryConfig(
            category=category,
            detect_prefixes=tuple(_normalize_token(p) for p in category_data.get("detect_prefixes", [])),
            resources=tuple(_parse_resource(r) for r in category_data.get("resources", [])),
        )

    uncategorized_resources = tuple(_parse_resource(r) for r in raw.get("uncategorized_resources", []))

    return ResourceTemplatesConfig(categories=categories, uncategorized_resources=uncategorized_resources)


_cache: ResourceTemplatesConfig | None = None


def get_config() -> ResourceTemplatesConfig:
    global _cache
    if _cache is None:
        _cache = _load_from_disk()
    return _cache


def reload_config() -> None:
    """Clears the in-memory cache so the next get_config() call re-reads
    config/resource_templates.yml from disk. Used by tests (to point at a
    fixture file) and available for an admin action later if a "reload
    config without restarting" workflow is ever wanted."""
    global _cache
    _cache = None


def render_name(template: str, base_name: str) -> str:
    return template.replace(_NAME_PLACEHOLDER, base_name)


def match_template(candidate_name: str, template: str) -> str | None:
    """If `candidate_name` matches `template` (of the form
    'PREFIX{base_name}SUFFIX'), returns the extracted base_name; otherwise
    None. Matching is a plain substring check (not a regex), so templates
    should stick to literal prefixes/suffixes around the placeholder."""
    prefix, suffix = template.split(_NAME_PLACEHOLDER, 1)
    if not candidate_name.startswith(prefix):
        return None
    if suffix:
        if not candidate_name.endswith(suffix) or len(candidate_name) < len(prefix) + len(suffix):
            return None
        base_name = candidate_name[len(prefix): len(candidate_name) - len(suffix)]
    else:
        base_name = candidate_name[len(prefix):]
    return base_name if base_name else None


def detect_category(group_name: str) -> Category | None:
    """Returns the category detected from the group's name prefix (first
    "word", split on space/hyphen/underscore, accents/case ignored), or
    None if the name doesn't start with any category's configured
    prefixes — these are the "uncategorized" groups an admin assigns a
    category to manually."""
    normalized = _normalize_token(group_name)
    first_token = re.split(r"[\s_-]+", normalized, maxsplit=1)[0]
    for category_config in get_config().categories.values():
        if first_token in category_config.detect_prefixes:
            return category_config.category
    return None


def get_resources_for_category(category: Category | None) -> tuple[ResourceSpec, ...]:
    """Resources expected for a group of this category — or the fallback
    list for uncategorized groups (category=None)."""
    config = get_config()
    if category is None:
        return config.uncategorized_resources
    category_config = config.categories.get(category)
    return category_config.resources if category_config else ()


def match_admin_resource(category: Category, candidate_name: str) -> tuple[ResourceSpec, str] | None:
    """If `candidate_name` matches one of this category's `is_admin`
    resource templates, returns (that ResourceSpec, extracted base_name).
    Used by the sync's second pass to recognize e.g. "<Projet name> Admin"
    Authentik groups and attach them to their base group instead of
    creating a Group of their own."""
    for resource in get_resources_for_category(category):
        if not resource.is_admin:
            continue
        base_name = match_template(candidate_name, resource.name_template)
        if base_name:
            return resource, base_name
    return None
