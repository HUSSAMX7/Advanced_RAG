"""Assistant request models required by FastAPI/Pydantic."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssistantFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=6000)

    @field_validator("name", "description", "instructions")
    @classmethod
    def trim(cls, value, info):
        value = value.strip()
        if info.field_name == "name" and not value:
            raise ValueError("اكتب اسم المساعد.")
        return value
