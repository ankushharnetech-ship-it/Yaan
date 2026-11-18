from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import ActiveStatus, Role


class LoginIn(BaseModel):
    username: str
    password: str


class UserMe(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    first_name: str
    last_name: str
    email: str
    role: Role
    vendor_id: int | None
    customer_id: int | None = None
    customer_name: str | None = None
    must_change_password: bool


class LoginOut(BaseModel):
    access_token: str
    user: UserMe


class ForgotIn(BaseModel):
    identifier: str = Field(description="username or email")


class ResetIn(BaseModel):
    token: str
    new_password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class UserCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = None
    last_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    email: EmailStr
    mobile: str | None = Field(default=None, max_length=20)
    gender: str | None = None
    role: Role
    vendor_id: int | None = None
    driver_id: int | None = None  # required when role = driver
    customer_id: int | None = None  # required when role = operator
    address: str = Field(min_length=1)


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name: str | None = None
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    mobile: str | None = Field(default=None, max_length=20)
    gender: str | None = None
    address: str | None = None
    customer_id: int | None = None  # Operators only


class StatusIn(BaseModel):
    status: ActiveStatus


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    first_name: str
    middle_name: str | None
    last_name: str
    username: str
    email: str
    mobile: str | None
    gender: str | None
    address: str | None
    role: Role
    vendor_id: int | None
    vendor_name: str | None = None
    driver_id: int | None = None
    customer_id: int | None = None
    customer_name: str | None = None
    status: ActiveStatus
    credential_status: str = "set"  # temporary | temporary_expired | set (computed in the route)
    temp_password_expires_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime


class OnboardingResult(BaseModel):
    user: UserOut
    temporary_password: str  # shown once; only the hash is stored
    temp_password_expires_at: datetime
    email_status: str  # sent | failed
