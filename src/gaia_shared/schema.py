import base64
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_ATTACHMENT = 20 * 1024 * 1024
MAX_ATTACHMENTS = 128
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


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
    attachments: list[Attachment] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)
    # Deliberately no ground-truth field: answers stay in the scoring client.

    @model_validator(mode="after")
    def bounded_attachments(self):
        total = sum(len(base64.b64decode(item.data_base64)) for item in self.attachments)
        if total > MAX_ATTACHMENT:
            raise ValueError("Combined attachments exceed 20 MiB")
        if len({item.name for item in self.attachments}) != len(self.attachments):
            raise ValueError("Attachment names must be unique")
        return self
