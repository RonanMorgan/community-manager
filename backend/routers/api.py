import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import config
from backend import authentik_service, mattermost_service, outline_service, resource_templates
from backend.auth import CurrentUser, require_admin
from backend.database import get_db
from backend.models import AuditLog, Category, Group, GroupResource, ResourceStatus, ToolName
from backend.resource_templates import ResourceSpec
from backend.schemas import (
    AddUserRequest,
    GroupCategoryUpdate,
    GroupCreate,
    GroupOut,
    RelinkRequest,
    ResourceCandidate,
    ResourceRename,
    ResourceUser,
    SyncResult,
)

router = APIRouter(prefix="/api", tags=["api"])


def _log(db: Session, actor_email: str, action: str, *, group_id: str | None = None,
         resource_id: str | None = None, details: str | None = None) -> None:
    db.add(AuditLog(actor_email=actor_email, action=action, group_id=group_id, resource_id=resource_id, details=details))


def _normalize_name_key(name: str) -> str:
    return name.strip().lower()


# Per-tool "how to create a brand new resource" (used by create_group) and
# "how to find an existing one by exact name" (used by sync_from_authentik).
# WHICH resources a category gets, and what they're named, comes from
# config/resource_templates.yml (backend/resource_templates.py) — these
# dicts are only about the mechanics of a given tool, not category rules.
_PROVISIONERS = {
    ToolName.OUTLINE: (outline_service.create_collection, outline_service.OutlineError),
    ToolName.MATTERMOST: (mattermost_service.create_channel, mattermost_service.MattermostError),
    ToolName.MATTERMOST_ADMIN: (mattermost_service.create_channel, mattermost_service.MattermostError),
}
_FINDERS = {
    ToolName.OUTLINE: {
        "find": outline_service.find_collection_by_name,
        "error_type": outline_service.OutlineError,
        "id_field": "id",
        "name_field": "name",
    },
    ToolName.MATTERMOST: {
        "find": mattermost_service.find_channel_by_name,
        "error_type": mattermost_service.MattermostError,
        "id_field": "id",
        "name_field": "display_name",
    },
    ToolName.MATTERMOST_ADMIN: {
        "find": mattermost_service.find_channel_by_name,
        "error_type": mattermost_service.MattermostError,
        "id_field": "id",
        "name_field": "display_name",
    },
}


def _provision_resource(
    db: Session, group: Group, resource_spec: ResourceSpec, base_name: str, user: CurrentUser
) -> None:
    """Creates a brand-new resource (Outline collection, Mattermost channel...)
    for `group`, named per `resource_spec.name_template`. Never raises: a
    provisioning failure is recorded as an ERROR status on the
    GroupResource row rather than aborting the rest of group creation."""
    display_name = resource_templates.render_name(resource_spec.name_template, base_name)
    resource = GroupResource(
        group_id=group.id, tool=resource_spec.tool, display_name=display_name, status=ResourceStatus.PENDING
    )
    db.add(resource)
    db.flush()

    provisioner_entry = _PROVISIONERS.get(resource_spec.tool)
    if provisioner_entry is None:
        # Tool not wired up yet for manual creation (Brevo/Vaultwarden):
        # row stays PENDING. Can still be filled in later by /api/sync once
        # that tool gets discovery support too.
        logging.info(f"Tool '{resource_spec.tool}' has no provisioner yet, resource left as PENDING.")
        return

    provisioner, error_type = provisioner_entry
    try:
        external = provisioner(display_name)
        resource.external_id = str(external.get("id"))
        resource.status = ResourceStatus.ACTIVE
        _log(db, user.email, "resource.provisioned", group_id=group.id, resource_id=resource.id,
             details=f"tool={resource_spec.tool.value} external_id={resource.external_id}")
    except error_type as e:
        resource.status = ResourceStatus.ERROR
        _log(db, user.email, "resource.provision_failed", group_id=group.id, resource_id=resource.id,
             details=str(e))
        logging.error(f"Failed to provision {resource_spec.tool.value} resource '{display_name}': {e}")


def _provision_admin_resource(
    db: Session, group: Group, resource_spec: ResourceSpec, base_name: str, user: CurrentUser
) -> None:
    """
    Admin-style resources (resource_spec.is_admin=True, e.g. a Projet's
    admin channel) need BOTH an Authentik group AND the underlying tool
    resource created, named identically per resource_spec.name_template.
    The Authentik group isn't optional bookkeeping: it's what lets a later
    /api/sync recognize and keep refreshing this resource (see
    sync_from_authentik()'s pass 2 / match_admin_resource()) instead of
    resetting it to not_found because nothing "touched" it that run.
    """
    display_name = resource_templates.render_name(resource_spec.name_template, base_name)
    resource = GroupResource(
        group_id=group.id, tool=resource_spec.tool, display_name=display_name, status=ResourceStatus.PENDING
    )
    db.add(resource)
    db.flush()

    try:
        authentik_service.create_group(display_name)
    except authentik_service.AuthentikError as e:
        resource.status = ResourceStatus.ERROR
        _log(db, user.email, "resource.provision_failed", group_id=group.id, resource_id=resource.id,
             details=f"tool={resource_spec.tool.value} (authentik group '{display_name}') {e}")
        logging.error(f"Failed to provision admin Authentik group '{display_name}': {e}")
        return

    provisioner_entry = _PROVISIONERS.get(resource_spec.tool)
    if provisioner_entry is None:
        logging.info(f"Tool '{resource_spec.tool}' has no provisioner yet (admin Authentik group created).")
        return

    provisioner, error_type = provisioner_entry
    try:
        external = provisioner(display_name)
        resource.external_id = str(external.get("id"))
        resource.status = ResourceStatus.ACTIVE
        _log(db, user.email, "resource.provisioned", group_id=group.id, resource_id=resource.id,
             details=f"tool={resource_spec.tool.value} external_id={resource.external_id}")
    except error_type as e:
        # The Authentik "<name>" admin group WAS created successfully above,
        # only the tool resource failed — leave the resource in ERROR rather
        # than rolling back the Authentik group; an admin can retry via a
        # resync or the manual 🔗 reattach once the resource exists.
        resource.status = ResourceStatus.ERROR
        _log(db, user.email, "resource.provision_failed", group_id=group.id, resource_id=resource.id,
             details=str(e))
        logging.error(f"Failed to provision admin {resource_spec.tool.value} resource '{display_name}': {e}")


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_group(payload: GroupCreate, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    existing = db.query(Group).filter(Group.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Un groupe nommé '{payload.name}' existe déjà.")

    # Authentik is the source of truth for groups (CLAUDE.md §4-bis): a
    # Group here always corresponds to a real Authentik group. Creating it
    # is mandatory, not one of the checkboxes — if it fails, abort entirely
    # rather than create an app-only group with no real identity behind it.
    try:
        authentik_group = authentik_service.create_group(payload.name)
    except authentik_service.AuthentikError as e:
        raise HTTPException(status_code=502, detail=str(e))

    category = resource_templates.detect_category(payload.name)
    group = Group(
        name=payload.name,
        authentik_group_id=str(authentik_group["pk"]),
        category=category,
        created_by=user.email,
    )
    db.add(group)
    db.flush()  # get group.id without committing yet
    _log(db, user.email, "group.created", group_id=group.id, details=f"name={payload.name}")
    _log(db, user.email, "resource.provisioned", group_id=group.id,
         details=f"tool=authentik external_id={group.authentik_group_id}")

    selected_tools = set(payload.tools)
    category_resources = resource_templates.get_resources_for_category(category)

    for resource_spec in category_resources:
        if resource_spec.is_admin or resource_spec.tool not in selected_tools:
            continue
        _provision_resource(db, group, resource_spec, payload.name, user)

    # "is_admin" resources (e.g. a Projet's admin channel) aren't a checkbox
    # of their own: they're created automatically whenever their
    # `trigger_tool` was selected, because the category needs them
    # unconditionally when that tool is in use (see config/resource_templates.yml).
    for resource_spec in category_resources:
        if not resource_spec.is_admin:
            continue
        if resource_spec.trigger_tool is not None and resource_spec.trigger_tool not in selected_tools:
            continue
        _provision_admin_resource(db, group, resource_spec, payload.name, user)

    db.commit()
    db.refresh(group)
    return group


@router.patch("/groups/{group_id}/category", response_model=GroupOut)
def update_group_category(
    group_id: str,
    payload: GroupCategoryUpdate,
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Manually assign a category to a group whose name didn't match a
    Projet/Pole/Antenne prefix (the 'uncategorized' list). See CLAUDE.md.
    A category set here is preserved across future syncs as long as the
    group's Authentik name still doesn't match a recognized prefix."""
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Groupe introuvable.")

    old_category = group.category
    group.category = payload.category
    _log(db, user.email, "group.category_set", group_id=group.id,
         details=f"{old_category.value if old_category else 'none'} -> {payload.category.value}")
    db.commit()
    db.refresh(group)
    return group


@router.patch("/group-resources/{resource_id}", response_model=GroupOut)
def rename_resource(
    resource_id: str,
    payload: ResourceRename,
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    resource = db.get(GroupResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Ressource introuvable.")

    old_name = resource.display_name

    if resource.tool in (ToolName.OUTLINE,):
        if not resource.external_id:
            raise HTTPException(status_code=409, detail="Cette ressource Outline n'a pas encore été provisionnée.")
        try:
            outline_service.rename_collection(resource.external_id, payload.display_name)
        except outline_service.OutlineError as e:
            raise HTTPException(status_code=502, detail=str(e))
    else:
        raise HTTPException(
            status_code=400, detail=f"Le renommage n'est pas encore supporté pour l'outil '{resource.tool.value}'."
        )

    resource.display_name = payload.display_name
    _log(db, user.email, "resource.renamed", group_id=resource.group_id, resource_id=resource.id,
         details=f"{old_name} -> {payload.display_name}")
    db.commit()
    db.refresh(resource.group)
    return resource.group


@router.get("/group-resources/{resource_id}/search-candidates", response_model=list[ResourceCandidate])
def search_resource_candidates(
    resource_id: str,
    q: str = "",
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Type-ahead search used by the "reattach this resource" combobox: given
    a few characters, returns matching collections/channels from the tool
    itself — e.g. lets an admin fix a resource whose real name diverged
    from the Authentik group name (renamed independently in Outline)."""
    resource = db.get(GroupResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Ressource introuvable.")
    if not q or not q.strip():
        return []

    try:
        if resource.tool == ToolName.OUTLINE:
            candidates = outline_service.search_collections(q)
            return [{"id": c["id"], "name": c["name"]} for c in candidates]
        elif resource.tool in (ToolName.MATTERMOST, ToolName.MATTERMOST_ADMIN):
            candidates = mattermost_service.search_channels(q)
            return [{"id": c["id"], "name": c.get("display_name") or c.get("name", "")} for c in candidates]
        raise HTTPException(status_code=400, detail=f"Recherche non supportée pour l'outil '{resource.tool.value}'.")
    except (outline_service.OutlineError, mattermost_service.MattermostError) as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/group-resources/{resource_id}/relink", response_model=GroupOut)
def relink_resource(
    resource_id: str,
    payload: RelinkRequest,
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Manually (re)attaches a resource to a specific collection/channel picked
    from search_resource_candidates — for when the automatic name-based
    match in /api/sync missed it (e.g. the resource was renamed on the
    tool's side after the fact, independently of Authentik)."""
    resource = db.get(GroupResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Ressource introuvable.")

    old_external_id = resource.external_id
    resource.external_id = payload.external_id
    resource.display_name = payload.display_name
    resource.status = ResourceStatus.ACTIVE
    resource.last_synced_at = datetime.now(timezone.utc)
    _log(db, user.email, "resource.relinked", group_id=resource.group_id, resource_id=resource.id,
         details=f"{old_external_id} -> {payload.external_id} ({payload.display_name})")
    db.commit()
    db.refresh(resource.group)
    return resource.group


@router.get("/group-resources/{resource_id}/users", response_model=list[ResourceUser])
def list_resource_users(resource_id: str, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    resource = db.get(GroupResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Ressource introuvable.")
    if not resource.external_id:
        raise HTTPException(status_code=409, detail="Cette ressource n'a pas encore été provisionnée / trouvée.")

    try:
        if resource.tool == ToolName.OUTLINE:
            return outline_service.list_members_with_permission(resource.external_id)
        elif resource.tool in (ToolName.MATTERMOST, ToolName.MATTERMOST_ADMIN):
            return mattermost_service.list_members_with_role(resource.external_id)
        raise HTTPException(status_code=400, detail=f"Outil '{resource.tool.value}' pas encore supporté.")
    except (outline_service.OutlineError, mattermost_service.MattermostError) as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/group-resources/{resource_id}/users", status_code=201)
def add_resource_user(
    resource_id: str,
    payload: AddUserRequest,
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    resource = db.get(GroupResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Ressource introuvable.")
    if resource.tool != ToolName.OUTLINE:
        # Adding users is only wired up for Outline so far (see CLAUDE.md).
        raise HTTPException(status_code=400, detail=f"L'ajout d'utilisateur n'est pas encore supporté pour '{resource.tool.value}'.")
    if not resource.external_id:
        raise HTTPException(status_code=409, detail="Cette ressource n'a pas encore été provisionnée.")

    try:
        outline_service.add_user(resource.external_id, payload.email, payload.permission)
    except outline_service.OutlineError as e:
        # Explicit, user-facing error (e.g. user not yet provisioned in Outline) — required by product decision.
        raise HTTPException(status_code=422, detail=str(e))

    _log(db, user.email, "resource.user_added", group_id=resource.group_id, resource_id=resource.id,
         details=f"email={payload.email} permission={payload.permission}")
    db.commit()
    return {"ok": True}


@router.delete("/group-resources/{resource_id}/users/{external_user_id}", status_code=204)
def remove_resource_user(
    resource_id: str,
    external_user_id: str,
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    resource = db.get(GroupResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Ressource introuvable.")
    if resource.tool != ToolName.OUTLINE:
        raise HTTPException(status_code=400, detail=f"Le retrait d'utilisateur n'est pas encore supporté pour '{resource.tool.value}'.")
    if not resource.external_id:
        raise HTTPException(status_code=409, detail="Cette ressource n'a pas encore été provisionnée.")

    try:
        outline_service.remove_user(resource.external_id, external_user_id)
    except outline_service.OutlineError as e:
        raise HTTPException(status_code=502, detail=str(e))

    _log(db, user.email, "resource.user_removed", group_id=resource.group_id, resource_id=resource.id,
         details=f"external_user_id={external_user_id}")
    db.commit()
    return None


def _sync_tool_resource(
    db: Session,
    group: Group,
    search_name: str,
    tool: ToolName,
    finder_conf: dict,
    result: SyncResult,
    touched_resource_ids: set[str],
) -> None:
    """Finds (or clears) the resource matching `search_name` (the group's
    Authentik name run through this resource's configured name_template —
    see config/resource_templates.yml) in `tool` for `group`, creating the
    GroupResource row on first sight. Records the resource id as "touched"
    so the caller can tell untouched resources apart afterwards (stale —
    no longer confirmed by this sync run)."""
    resource = (
        db.query(GroupResource)
        .filter(GroupResource.group_id == group.id, GroupResource.tool == tool)
        .first()
    )
    if not resource:
        resource = GroupResource(group_id=group.id, tool=tool, display_name=search_name, status=ResourceStatus.PENDING)
        db.add(resource)
        db.flush()

    try:
        found = finder_conf["find"](search_name)
    except finder_conf["error_type"] as e:
        resource.status = ResourceStatus.ERROR
        result.errors.append(f"{tool.value}/{search_name}: {e}")
        logging.error(f"Sync error for {tool.value} / '{search_name}': {e}")
        touched_resource_ids.add(resource.id)
        return

    resource.last_synced_at = datetime.now(timezone.utc)
    if found:
        resource.external_id = str(found[finder_conf["id_field"]])
        resource.display_name = found.get(finder_conf["name_field"]) or search_name
        resource.status = ResourceStatus.ACTIVE
        result.resources_matched += 1
    else:
        resource.external_id = None
        resource.status = ResourceStatus.NOT_FOUND
        result.resources_not_found += 1
    touched_resource_ids.add(resource.id)


@router.post("/sync", response_model=SyncResult)
def sync_from_authentik(user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Authentik is the source of truth for groups (see CLAUDE.md §4-bis):
    - every Authentik group gets (or is matched to) a `Group` row here, and
      is auto-categorized (Projet/Pôle/Antenne) from its name prefix — see
      config/resource_templates.yml / backend/resource_templates.py;
    - a group matching one of its category's "is_admin" resource templates
      (e.g. a Projet's "<name> Admin") is NOT a group of its own: it
      becomes that resource (e.g. MATTERMOST_ADMIN) on its parent group;
    - for each of the category's remaining resources, we look for a match
      with the EXACT name obtained by rendering that resource's
      name_template. Found -> linked (status=active, shown in green). Not
      found -> status=not_found;
    - groups that no longer exist in Authentik (but were previously
      sync-linked here) are DELETED, and resources of surviving groups that
      weren't reconfirmed this run are reset to not_found. Authentik being
      the source of truth cuts both ways: this sync also removes, not just
      adds. Groups created manually (no authentik_group_id) are never
      touched by this reconciliation.
    This is read/discovery only on the tools side: nothing is created in
    Outline/Mattermost by this endpoint.
    """
    from clients.authentik_client import AuthentikClient

    if not config.AUTHENTIK_URL or not config.AUTHENTIK_TOKEN:
        raise HTTPException(status_code=409, detail="Authentik n'est pas configuré (AUTHENTIK_URL / AUTHENTIK_TOKEN).")

    client = AuthentikClient(base_url=config.AUTHENTIK_URL, token=config.AUTHENTIK_TOKEN)
    authentik_groups, _ = client.get_groups_with_users()
    if authentik_groups is None:
        raise HTTPException(status_code=502, detail="Échec de la récupération des groupes depuis Authentik (voir logs serveur).")

    result = SyncResult()
    seen_authentik_pks: set[str] = set()
    touched_resource_ids: set[str] = set()
    name_to_group: dict[str, Group] = {}
    # (authentik_pk, authentik_name, category, resource_spec, base_name), deferred to pass 2
    admin_matches: list[tuple[str, str, Category, ResourceSpec, str]] = []

    # --- Pass 1: every group EXCEPT ones matching an "is_admin" resource template ---
    for ak_group in authentik_groups:
        ak_pk = str(ak_group["pk"])
        ak_name = ak_group["name"]
        seen_authentik_pks.add(ak_pk)

        detected_category = resource_templates.detect_category(ak_name)
        if detected_category is not None:
            admin_match = resource_templates.match_admin_resource(detected_category, ak_name)
            if admin_match:
                resource_spec, base_name = admin_match
                admin_matches.append((ak_pk, ak_name, detected_category, resource_spec, base_name))
                continue

        group = db.query(Group).filter(Group.authentik_group_id == ak_pk).first()
        if not group:
            # Might already exist by name (e.g. created manually before sync existed) -> link it.
            group = db.query(Group).filter(Group.name == ak_name).first()

        if group:
            if group.authentik_group_id != ak_pk:
                group.authentik_group_id = ak_pk
            if detected_category is not None:
                # A recognized prefix always wins. If there's none, we deliberately
                # leave `category` as-is, so a manual assignment (see
                # update_group_category) survives future syncs.
                group.category = detected_category
            result.groups_updated += 1
        else:
            group = Group(name=ak_name, authentik_group_id=ak_pk, category=detected_category, created_by=user.email)
            db.add(group)
            db.flush()
            _log(db, user.email, "group.synced_from_authentik", group_id=group.id, details=f"authentik_pk={ak_pk}")
            result.groups_created += 1

        name_to_group[_normalize_name_key(ak_name)] = group

        for resource_spec in resource_templates.get_resources_for_category(group.category):
            if resource_spec.is_admin:
                continue  # only ever attached to a parent via pass 2, never searched for on the group itself
            search_name = resource_templates.render_name(resource_spec.name_template, ak_name)
            _sync_tool_resource(
                db, group, search_name, resource_spec.tool, _FINDERS[resource_spec.tool], result, touched_resource_ids
            )

    # --- Pass 2: "is_admin" matches -> attach to their parent group ---
    for ak_pk, ak_name, category, resource_spec, base_name in admin_matches:
        seen_authentik_pks.add(ak_pk)  # doesn't own a Group row, but still "seen" this run
        parent = name_to_group.get(_normalize_name_key(base_name))
        if not parent:
            parent = db.query(Group).filter(Group.name == base_name, Group.category == category).first()
        if not parent:
            result.warnings.append(
                f"Groupe '{ak_name}' trouvé dans Authentik mais aucun groupe parent "
                f"'{base_name}' correspondant — ignoré."
            )
            continue
        _sync_tool_resource(
            db, parent, ak_name, resource_spec.tool, _FINDERS[resource_spec.tool], result, touched_resource_ids
        )

    # --- Reconciliation: Authentik is authoritative, so deletions there propagate here too ---
    managed_groups = db.query(Group).filter(Group.authentik_group_id.isnot(None)).all()
    for group in managed_groups:
        if group.authentik_group_id not in seen_authentik_pks:
            _log(db, user.email, "group.deleted_not_in_authentik", group_id=group.id, details=f"name={group.name}")
            db.delete(group)
            result.groups_deleted += 1
        else:
            for resource in group.resources:
                if resource.id not in touched_resource_ids and resource.status != ResourceStatus.NOT_FOUND:
                    resource.status = ResourceStatus.NOT_FOUND
                    resource.external_id = None

    _log(db, user.email, "sync.completed", details=str(result.model_dump()))
    db.commit()
    return result
