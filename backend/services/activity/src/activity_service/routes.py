from typing import Annotated
from uuid import UUID

from activityual_common.security import CurrentUser
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from backend.services.activity.src.activity_service import service

from .schemas import ActivityCreate, ActivityPatch


def build_router(get_session, current_user) -> APIRouter:
    router = APIRouter(prefix="/api/activities", tags=["activities"])

    @router.post("", status_code=201)
    def create(
        body: ActivityCreate,
        response: Response,
        user: Annotated[CurrentUser, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict:
        row = service.create_activity(session, user.id, body)
        response.headers["Location"] = f"/api/activities/{row.id}"
        return service.to_api(row)

    @router.get("")
    def list_(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        cursor: str | None = None,
        includeInactive: bool = False,
        user: Annotated[CurrentUser, Depends(current_user)] = current_user,
        session: Annotated[Session, Depends(get_session)] = get_session,
    ) -> dict:
        return service.list_activities(session, user.id, limit, cursor, includeInactive)

    @router.get("/{activity_id}")
    def get_one(
        activity_id: UUID,
        user: Annotated[CurrentUser, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict:
        return service.to_api(service.get_activity(session, user.id, activity_id))

    @router.patch("/{activity_id}")
    def patch(
        activity_id: UUID,
        body: ActivityPatch,
        user: Annotated[CurrentUser, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict:
        return service.to_api(
            service.update_activity(session, user.id, activity_id, body)
        )

    @router.delete("/{activity_id}", status_code=204)
    def delete(
        activity_id: UUID,
        user: Annotated[CurrentUser, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> Response:
        service.deactivate_activity(session, user.id, activity_id)
        return Response(status_code=204)

    return router
