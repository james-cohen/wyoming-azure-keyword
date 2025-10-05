"""Wyoming server for Microsoft Azure Keyword detection."""

from pydantic import BaseModel


class KeywordDetectionConfig(BaseModel):
    """Keyword detection configuration."""

    model_path: str
    keyword_name: str
