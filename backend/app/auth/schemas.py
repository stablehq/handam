from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: int
    username: str
    name: str
    role: str
    is_active: bool

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo


class UserCreate(BaseModel):
    username: str
    password: str
    name: str
    role: str


class UserUpdate(BaseModel):
    username: str | None = None
    name: str | None = None
    password: str | None = None
    role: str | None = None
    is_active: bool | None = None
