"""
File Overview: Base Data Transfer Object using Pydantic for consistent model configuration.

All Functions/Classes:
- base_dto (class): Configures Pydantic to allow attribute-based instantiation and frozen state. Data: Input Attributes -> Frozen DTO.

Endpoints/APIs:
- None.

Database Tables:
- None.
"""
from pydantic import BaseModel, ConfigDict


class BaseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)
