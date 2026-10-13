"""Guest HTTP input models required by Pydantic."""

from pydantic import BaseModel, ConfigDict, SecretStr


class GuestToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr
