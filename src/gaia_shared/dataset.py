import base64
import json
import re
from pathlib import Path

from .schema import MAX_ATTACHMENT, Attachment, TaskRequest


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
        attachments.append(
            Attachment(
                name=path.name, data_base64=base64.b64encode(path.read_bytes()).decode("ascii")
            )
        )
    return TaskRequest(
        task_id=str(row["task_id"]), question=row["Question"], attachments=attachments
    )
