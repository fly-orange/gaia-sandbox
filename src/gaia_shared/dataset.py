import base64
import io
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .schema import IMAGE_SUFFIXES, MAX_ATTACHMENT, MAX_ATTACHMENTS, Attachment, TaskRequest


def read_instances(root: Path, split: str, level: int, limit: int):
    directory = root / "2023" / split
    jsonl, parquet = directory / "metadata.jsonl", directory / "metadata.parquet"
    if jsonl.is_file():
        rows = [
            json.loads(line)
            for line in jsonl.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    elif parquet.is_file():
        import pandas as pd

        rows = pd.read_parquet(parquet).fillna("").to_dict("records")
    else:
        raise FileNotFoundError(f"Missing GAIA metadata.jsonl or metadata.parquet: {directory}")
    if level:
        rows = [
            r
            for r in rows
            if re.search(r"\d+", str(r["Level"]))
            and int(re.search(r"\d+", str(r["Level"])).group()) == level
        ]
    if limit:
        rows = rows[:limit]
    ids = [str(r["task_id"]) for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Dataset has duplicate task_id values")
    return rows


def make_request(row, root: Path, split: str):
    attachments = []
    if row.get("file_name"):
        directory = (root / "2023" / split).resolve()
        path = (directory / row["file_name"]).resolve()
        if not path.is_relative_to(directory):
            raise ValueError("Attachment path escapes dataset split directory")
        if path.stat().st_size > MAX_ATTACHMENT:
            raise ValueError(f"Attachment exceeds 20 MiB: {path.name}")
        data = path.read_bytes()
        suffix = path.suffix.lower()
        if suffix == ".zip":
            total = 0
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                files = [item for item in archive.infolist() if not item.is_dir()]
                if len(files) > MAX_ATTACHMENTS:
                    raise ValueError(f"ZIP contains more than {MAX_ATTACHMENTS} files")
                for item in files:
                    member = PurePosixPath(item.filename.replace("\\", "/"))
                    name = member.name
                    mode = item.external_attr >> 16
                    if (
                        not name
                        or member.is_absolute()
                        or ".." in member.parts
                        or item.flag_bits & 1
                        or stat.S_ISLNK(mode)
                    ):
                        raise ValueError(f"Unsafe ZIP member: {item.filename}")
                    total += item.file_size
                    if total > MAX_ATTACHMENT:
                        raise ValueError("Extracted ZIP exceeds 20 MiB")
                    attachments.append(
                        Attachment(
                            name=name,
                            data_base64=base64.b64encode(archive.read(item)).decode("ascii"),
                        )
                    )
        else:
            name = path.name if suffix in IMAGE_SUFFIXES else f"file{suffix}"
            attachments.append(
                Attachment(name=name, data_base64=base64.b64encode(data).decode("ascii"))
            )
    return TaskRequest(
        task_id=str(row["task_id"]), question=row["Question"], attachments=attachments
    )
