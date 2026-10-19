"""Authenticated transport; bounded retrieval and advisory orchestration are services."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai.operations_assistant import answer, read_question
from app.api.auth import Principal, operator
from app.config import get_settings
from app.db.session import get_db
from app.schemas.assistant import AssistantAnswer, AssistantQuestion
from app.services import operations
from app.services.errors import ServiceError

router = APIRouter(tags=["Assistance"])


async def question_body(request: Request):
    if (
        request.headers.get("content-type", "").split(";")[0].strip()
        != "application/json"
    ):
        raise ServiceError(415, "json_required", "Send a JSON operational question")
    return await read_question(request.stream())


@router.post(
    "/api/assistant/ask",
    response_model=AssistantAnswer,
    summary="Ask a scoped operational question with evidence citations",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": AssistantQuestion.model_json_schema()}
            },
        }
    },
)
def ask(
    question: Annotated[AssistantQuestion, Depends(question_body)],
    user: Annotated[Principal, Depends(operator)],
    db: Annotated[Session, Depends(get_db)],
    tenant_id: str | None = None,
):
    return answer(
        db, operations.scope(user.tenant_id, tenant_id), question, get_settings()
    )
