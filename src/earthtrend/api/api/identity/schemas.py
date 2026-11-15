"""Identity HTTP schemas."""

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=128)
    password: str = Field(max_length=200)


class SessionResponse(BaseModel):
    token: str
    expires_at: int = Field(description="Unix seconds when the token stops working; refresh before then.")


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=4096)


class SessionReadResponse(BaseModel):
    user_id: str
    role: str


class IssueKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: str = Field(min_length=1, max_length=64)


class KeyResponse(BaseModel):
    id: str
    secret: str
    revoked: bool


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(min_length=1, max_length=64)
    note: str = Field(min_length=1, max_length=4000)


class ReviewResponse(BaseModel):
    id: str
    case_id: str
    actor_id: str
    note: str
