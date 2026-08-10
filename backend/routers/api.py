import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import config
from backend import mattermost_service, outline_service
from backend.auth import CurrentUser, require_admin
from backend.database import get_db
from backend.models import AuditLog, Group, GroupResource, ResourceStatus, ToolName
from backend.schemas import AddUserRequest, GroupCreate, GroupOut, ResourceRename, ResourceUser, SyncResult

router = APIRouter(prefix="/api", tags=["api"])


def _log(db: Session, actor_email: str, action: str, *, group_id: str | None = None,
         resource_id: str | None = None, details: str | None = None) -> None:
    db.add(AuditLog(actor_email=actor_email, action=action, group_id=group_id, resource_id=resource_id, details=details))


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_group(payload: GroupCreate, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    existing = db.query(Group).filter(Group.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Un groupe nommé '{payload.name}' existe déjà.")

    group = Group(name=payload.name, created_by=user.email)
    db.add(group)
    db.flush()  # get group.id without committing yet
    _log(db, user.email, "group.created", group_id=group.id, details=f"name={payload.name}")

    for tool in payload.tools:
        resource = GroupResource(group_id=group.id, tool=tool, display_name=payload.name, status=ResourceStatus.PENDING)
        db.add(resource)
        db.flush()

        provisioner = outline_service.PROVISIONERS.get(tool)
        if provisioner is None:
            # Tool not wired up yet for manual creation (Mattermost/Brevo/Vaultwarden):
            # row stays PENDING. Mattermost can still be filled in later by /api/sync.
            logging.info(f"Tool '{tool}' has no provisioner yet, resource left as PENDING.")
            continue

        try:
            external = provisioner(payload.name)
            resource.external_id = str(external.get("id"))
            resource.status = ResourceStatus.ACTIVE
            _log(db, user.email, "resource.provisioned", group_id=group.id, resource_id=resource.id,
                 details=f"tool={tool.value} external_id={resource.external_id}")
        except outline_service.OutlineError as e:
            resource.status = ResourceStatus.ERROR
            _log(db, user.email, "resource.provision_failed", group_id=group.id, resource_id=resource.id,
                 details=str(e))
            logging.error(f"Failed to provision {tool.value} resource for group '{payload.name}': {e}")

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

    if resource.tool == ToolName.OUTLINE:
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
        elif resource.tool == ToolName.MATTERMOST:
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


# Tools that the sync-from-Authentik flow knows how to discover a matching
# resource for, and how to read its id/display name from the tool's own
# object shape. Add an entry here to make a new tool sync-discoverable.
_SYNC_FINDERS = {
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
}


@router.post("/sync", response_model=SyncResult)
def sync_from_authentik(user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Authentik is the source of truth for groups (see CLAUDE.md §4-bis):
    - every Authentik group gets (or is matched to) a `Group` row here;
    - for each tool in _SYNC_FINDERS, we look for a resource with the EXACT
      same name as the Authentik group. Found -> linked (status=active,
      shown in green). Not found -> status=not_found (no resource created).
    This is read/discovery only: nothing is created in Outline/Mattermost
    by this endpoint.
    """
    from clients.authentik_client import AuthentikClient

    if not config.AUTHENTIK_URL or not config.AUTHENTIK_TOKEN:
        raise HTTPException(status_code=409, detail="Authentik n'est pas configuré (AUTHENTIK_URL / AUTHENTIK_TOKEN).")

    client = AuthentikClient(base_url=config.AUTHENTIK_URL, token=config.AUTHENTIK_TOKEN)
    authentik_groups, _ = client.get_groups_with_users()
    if not authentik_groups:
        raise HTTPException(status_code=502, detail="Aucun groupe récupéré depuis Authentik (voir logs serveur).")

    result = SyncResult()

    for ak_group in authentik_groups:
        ak_pk = str(ak_group["pk"])
        ak_name = ak_group["name"]

        group = db.query(Group).filter(Group.authentik_group_id == ak_pk).first()
        if not group:
            # Might already exist by name (e.g. created manually before sync existed) -> link it.
            group = db.query(Group).filter(Group.name == ak_name).first()

        if group:
            if group.authentik_group_id != ak_pk:
                group.authentik_group_id = ak_pk
            result.groups_updated += 1
        else:
            group = Group(name=ak_name, authentik_group_id=ak_pk, created_by=user.email)
            db.add(group)
            db.flush()
            _log(db, user.email, "group.synced_from_authentik", group_id=group.id, details=f"authentik_pk={ak_pk}")
            result.groups_created += 1

        for tool, finder_conf in _SYNC_FINDERS.items():
            resource = (
                db.query(GroupResource)
                .filter(GroupResource.group_id == group.id, GroupResource.tool == tool)
                .first()
            )
            if not resource:
                resource = GroupResource(group_id=group.id, tool=tool, display_name=ak_name, status=ResourceStatus.PENDING)
                db.add(resource)
                db.flush()

            try:
                found = finder_conf["find"](ak_name)
            except finder_conf["error_type"] as e:
                resource.status = ResourceStatus.ERROR
                result.errors.append(f"{tool.value}/{ak_name}: {e}")
                logging.error(f"Sync error for {tool.value} / group '{ak_name}': {e}")
                continue

            resource.last_synced_at = datetime.now(timezone.utc)
            if found:
                resource.external_id = str(found[finder_conf["id_field"]])
                resource.display_name = found.get(finder_conf["name_field"]) or ak_name
                resource.status = ResourceStatus.ACTIVE
                result.resources_matched += 1
            else:
                resource.external_id = None
                resource.status = ResourceStatus.NOT_FOUND
                result.resources_not_found += 1

    _log(db, user.email, "sync.completed", details=str(result.model_dump()))
    db.commit()
    return result
