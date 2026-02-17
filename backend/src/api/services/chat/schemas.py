from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


REQUIRED_SLIDERS = [
    "dominance",
    "audacity",
    "sales_tactic",
    "tone",
    "emotion",
    "initiative",
    "vocabulary",
    "emojis",
    "imperfection",
]


def _validate_sliders(v: Dict[str, Any]) -> Dict[str, Any]:
    missing = [s for s in REQUIRED_SLIDERS if s not in v]
    if missing:
        raise ValueError(f"persona_data manque les sliders: {missing}")
    return v


class ChatResponse(BaseModel):
    response: str


class DirectChatRequest(BaseModel):
    message: Optional[str] = None
    prompt: Optional[str] = None
    messages: List[Dict[str, Any]] = Field(default_factory=list)

    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None


class PersonalityChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    persona_data: Dict[str, Any]

    @field_validator("persona_data")
    @classmethod
    def validate_persona_data(cls, v):
        return _validate_sliders(v)


class UnpersonaChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    persona_data: Optional[Dict[str, Any]] = None


class ScriptChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    persona_data: Dict[str, Any]
    script: str = Field(..., min_length=1)

    @field_validator("persona_data")
    @classmethod
    def validate_persona_data(cls, v):
        return _validate_sliders(v)
