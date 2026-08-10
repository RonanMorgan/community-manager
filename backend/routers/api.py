import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import outline_service
from backend.auth import CurrentUser, require_admin
from backend.database import get_db
from backend.models import AuditLog, Group, GroupResource, ResourceStatus, ToolName
from backend.schemas import AddUserRequest, GroupCreate, GroupOut, ResourceRename, ResourceUser

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
            # Tool not wired up yet (Mattermost/Brevo/Vaultwarden): row stays PENDING.
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
        raise HTTPException(status_code=400, detail=f"Le renommage n'est pas encore supporté pour l'outil '{resource.tool.value}'.")

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
    if resource.tool != ToolName.OUTLINE:
        raise HTTPException(status_code=400, detail=f"Outil '{resource.tool.value}' pas encore supporté.")
    if not resource.external_id:
        raise HTTPException(status_code=409, detail="Cette ressource n'a pas encore été provisionnée.")

    try:
        return outline_service.list_members_with_permission(resource.external_id)
    except outline_service.OutlineError as e:
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
        raise HTTPException(status_code=400, detail=f"Outil '{resource.tool.value}' pas encore supporté.")
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


@router.delete("/group-resources/{resource_id}/users/{outline_user_id}", status_code=204)
def remove_resource_user(
    resource_id: str,
    outline_user_id: str,
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    resource = db.get(GroupResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Ressource introuvable.")
    if resource.tool != ToolName.OUTLINE:
        raise HTTPException(status_code=400, detail=f"Outil '{resource.tool.value}' pas encore supporté.")
    if not resource.external_id:
        raise HTTPException(status_code=409, detail="Cette ressource n'a pas encore été provisionnée.")

    try:
        outline_service.remove_user(resource.external_id, outline_user_id)
    except outline_service.OutlineError as e:
        raise HTTPException(status_code=502, detail=str(e))

    _log(db, user.email, "resource.user_removed", group_id=resource.group_id, resource_id=resource.id,
         details=f"outline_user_id={outline_user_id}")
    db.commit()
    return None
