import re
from typing import Optional


def slugify(text: str) -> str:
    """
    Simple slugify function:
    - Convert to lowercase
    - Replace spaces and underscores with hyphens
    - Remove characters that are not alphanumeric or hyphens
    - Ensure it doesn't start or end with a hyphen
    - Truncate to 64 characters (Mattermost limit for channel name)
    - Return a default name if the slug becomes empty
    """
    text = str(text).lower()
    # Replace spaces and underscores with hyphens first
    text = re.sub(r"[\s_]+", "-", text)
    # Replace any sequence of non-alphanumeric characters (excluding existing hyphens) with a single hyphen
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    # Remove leading or trailing hyphens that might have been created
    text = text.strip("-")
    # Consolidate multiple hyphens (e.g., "foo---bar" to "foo-bar").
    text = re.sub(r"-+", "-", text)

    if len(text) > 64:
        text = text[:64].strip("-")  # Re-strip if truncation creates leading/trailing hyphen

    if not text or text == "-":  # Handle if slug becomes empty or just a hyphen
        return "default-channel-name"  # Changed default from 'default-channel-name' to be more generic
    return text


def _extract_base_name(actual_name: str, pattern_with_placeholder: str) -> Optional[str]:
    """
    Extracts the base_name from an actual_name given a pattern string like "prefix_{base_name}_suffix".
    Returns the extracted base_name (can be an empty string), or None if the actual_name doesn't match
    the pattern or if {base_name} is not in the pattern.
    """
    placeholder = "{base_name}"
    if placeholder not in pattern_with_placeholder:
        return None

    parts = pattern_with_placeholder.split(placeholder)
    prefix = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""

    if actual_name.startswith(prefix) and actual_name.endswith(suffix):
        if len(actual_name) < len(prefix) + len(suffix):
            return None

        if suffix:
            base_name_part = actual_name[len(prefix) : -len(suffix)]
        else:
            base_name_part = actual_name[len(prefix) :]

        return base_name_part
    return None


def _map_mm_channel_to_entity_and_base_name(
    mm_channel_slug: str, mm_channel_display_name: str, permissions_matrix: dict
) -> tuple[Optional[str], Optional[str]]:
    """
    Attempts to map a Mattermost channel (slug or display name) to an entity key and base_name.
    """
    # Try matching with channel display name first, as it's often more descriptive
    for entity_key, entity_cfg in permissions_matrix.items():
        if entity_cfg.get("admin"):
            mm_adm_pattern = entity_cfg.get("admin", {}).get("mattermost_channel_name_pattern")
            if mm_adm_pattern:
                base_name = _extract_base_name(mm_channel_display_name, mm_adm_pattern)
                if base_name is not None:
                    return entity_key, base_name
        std_pattern = entity_cfg.get("standard", {}).get("mattermost_channel_name_pattern")
        if std_pattern:
            base_name = _extract_base_name(mm_channel_display_name, std_pattern)
            if base_name is not None:
                return entity_key, base_name

    # Fallback to matching with channel slug if display name didn't yield a match
    # (Patterns are usually based on display name conventions, but slug might work for simple cases)
    for entity_key, entity_cfg in permissions_matrix.items():
        if entity_cfg.get("admin"):
            mm_adm_pattern = entity_cfg.get("admin", {}).get("mattermost_channel_name_pattern")
            # Slugifying the pattern to compare with slug might be needed if patterns are complex
            # For simple "{base_name}" or "prefix_{base_name}" it might work directly if base_name is slug-compatible
            if (
                mm_adm_pattern
                and slugify(mm_adm_pattern.format(base_name="test-slug"))
                == mm_adm_pattern.format(base_name="test-slug").lower()
            ):  # Simple pattern check
                base_name = _extract_base_name(
                    mm_channel_slug, mm_adm_pattern.lower()
                )  # Compare with lowercased pattern
                if base_name is not None:
                    return entity_key, base_name
        std_pattern = entity_cfg.get("standard", {}).get("mattermost_channel_name_pattern")
        if (
            std_pattern
            and slugify(std_pattern.format(base_name="test-slug")) == std_pattern.format(base_name="test-slug").lower()
        ):
            base_name = _extract_base_name(mm_channel_slug, std_pattern.lower())
            if base_name is not None:
                return entity_key, base_name

    return None, None
