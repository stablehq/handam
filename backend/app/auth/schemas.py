from pydantic import BaseModel, field_validator


def _validate_password(v: str) -> str:
    """비밀번호 정책 검증 (공통 함수)"""
    if not v.strip():
        raise ValueError("비밀번호는 공백만으로 구성할 수 없습니다")
    if len(v) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다")
    return v


class LoginRequest(BaseModel):
    username: str
    password: str


class TenantInfo(BaseModel):
    id: int
    slug: str
    name: str

    class Config:
        from_attributes = True


class UserInfo(BaseModel):
    id: int
    username: str
    name: str
    role: str
    active: bool
    tenants: list[TenantInfo] = []

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

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password(v)


class UserUpdate(BaseModel):
    username: str | None = None
    name: str | None = None
    password: str | None = None
    role: str | None = None
    active: bool | None = None

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_password(v)
