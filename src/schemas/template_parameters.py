"""Template parameter schemas for Heat template parameter extraction."""
from pydantic import BaseModel, Field, ConfigDict
from typing import Any


class TemplateParameterSchema(BaseModel):
    """Schema for a single Heat template parameter definition.
    
    Extracted from template config.yaml parameters section.
    """
    name: str = Field(..., description="Parameter name (e.g., 'instance_name', 'flavor')")
    type: str = Field(..., description="Parameter type (string, int, number, boolean)")
    required: bool = Field(..., description="Whether this parameter is required")
    default: Any = Field(None, description="Default value if not required")
    description: str = Field(..., description="Human-readable description for UI")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "instance_name",
                "type": "string",
                "required": True,
                "default": None,
                "description": "Eindeutiger Name der Instanz/Stacks (z.B. kursX-grp1-db)."
            }
        }
    )


class TemplateParametersResponse(BaseModel):
    """Schema for template version parameters response.
    
    Returns all parameters defined in the template's config.yaml.
    """
    template_version_id: str = Field(..., description="Template version ID")
    parameters: list[TemplateParameterSchema] = Field(..., description="List of parameter definitions")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_version_id": "version-123",
                "parameters": [
                    {
                        "name": "instance_name",
                        "type": "string",
                        "required": True,
                        "default": None,
                        "description": "Eindeutiger Name der Instanz/Stacks"
                    },
                    {
                        "name": "flavor",
                        "type": "string",
                        "required": True,
                        "default": "gp1.small",
                        "description": "OpenStack Flavor"
                    }
                ]
            }
        }
    )
