"""Job HTTP schemas."""

from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    case_id: str
    status: str
    progress: int
    stage: str
    message: str
