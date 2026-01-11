"""Course schemas for request/response validation."""
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class CourseCreate(BaseModel):
    """Schema for creating a course."""
    name: str = Field(..., description="Course name", max_length=255)
    semester: str = Field(..., description="Semester (e.g., WS2024, SS2025)", max_length=50)
    lecturer_id: str = Field(..., description="Lecturer user ID")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Advanced Web Development",
                "semester": "WS2024",
                "lecturer_id": "user-456"
            }
        }
    )


class CourseUpdate(BaseModel):
    """Schema for updating a course."""
    name: Optional[str] = Field(None, description="Course name", max_length=255)
    semester: Optional[str] = Field(None, description="Semester", max_length=50)
    lecturer_id: Optional[str] = Field(None, description="Lecturer user ID")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Updated Course Name",
                "semester": "SS2025",
                "lecturer_id": "user-789"
            }
        }
    )


class CourseResponse(BaseModel):
    """Schema for course response."""
    id: str = Field(..., description="Course ID")
    name: str = Field(..., description="Course name")
    semester: str = Field(..., description="Semester")
    lecturer_id: str = Field(..., description="Lecturer user ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "course-123",
                "name": "Advanced Web Development",
                "semester": "WS2024",
                "lecturer_id": "user-456",
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )


class CourseMemberCreate(BaseModel):
    """Schema for adding a member to a course."""
    user_id: str = Field(..., description="User ID to add to course")
    course_id: str = Field(..., description="Course ID")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "user-789",
                "course_id": "course-123"
            }
        }
    )


class CourseMemberResponse(BaseModel):
    """Schema for course member response."""
    id: str = Field(..., description="Course member ID")
    user_id: str = Field(..., description="User ID")
    course_id: str = Field(..., description="Course ID")
    joined_at: datetime = Field(..., description="Join timestamp")
    left_at: Optional[datetime] = Field(None, description="Leave timestamp")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "member-123",
                "user_id": "user-789",
                "course_id": "course-123",
                "joined_at": "2024-11-27T10:00:00Z",
                "left_at": None
            }
        }
    )


class CourseGroupCreate(BaseModel):
    """Schema for creating a course group."""
    course_id: str = Field(..., description="Course ID")
    name: str = Field(..., description="Group name", max_length=255)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "course_id": "course-123",
                "name": "Group A"
            }
        }
    )


class CourseGroupResponse(BaseModel):
    """Schema for course group response."""
    id: str = Field(..., description="Group ID")
    course_id: str = Field(..., description="Course ID")
    name: str = Field(..., description="Group name")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "group-123",
                "course_id": "course-123",
                "name": "Group A",
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )
