"""User Pydantic schemas."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, ConfigDict
from src.models.user import UserRole


class UserBase(BaseModel):
    """Base user schema with common fields."""
    email: EmailStr
    name: str


class UserCreate(UserBase):
    """Schema for creating a new user."""
    external_id: str
    role: UserRole = UserRole.STUDENT


class UserUpdate(BaseModel):
    """Schema for updating a user."""
    name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserResponse(UserBase):
    """Schema for user response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    external_id: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
