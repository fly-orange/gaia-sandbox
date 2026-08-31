import base64
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_ATTACHMENT = 20 * 1024 * 1024


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    data_base64: str = Field(max_length=28 * 1024 * 1024)

    @field_validator("name")
    @classmethod
    def safe_name(cls, name):
        if (
            not name
            or name in (".", "..")
            or "\\" in name
            or ":" in name
            or PurePosixPath(name).name != name
            or "\x00" in name
        ):
            raise ValueError("Attachment name must be a plain basename")
        return name

    @field_validator("data_base64")
    @classmethod
    def valid_data(cls, value):
        data = base64.b64decode(value, validate=True)
        if len(data) > MAX_ATTACHMENT:
            raise ValueError("Attachment exceeds 20 MiB")
        return value


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=100000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=1)
    # Deliberately no ground-truth field: answers stay in the scoring client.
