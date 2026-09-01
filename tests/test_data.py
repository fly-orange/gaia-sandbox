import base64
import io
import json
import zipfile

import pytest
from pydantic import ValidationError

from gaia_shared.benchmark import instruction
from gaia_shared.dataset import make_request, read_instances
from gaia_shared.schema import Attachment
from gaia_shared.scoring import score, summarize


@pytest.mark.parametrize("name", ["../secret", "/etc/passwd", "a/b", "a\\b", "C:x", ".", ".."])
def test_unsafe_attachment_names(name):
    with pytest.raises(ValidationError):
        Attachment(name=name, data_base64="")


def test_dataset_selection_and_no_answer_leak(tmp_path):
    directory = tmp_path / "2023" / "validation"
    directory.mkdir(parents=True)
    rows = [
        {
            "task_id": str(i),
            "Level": 1,
            "Question": "What?",
            "Final answer": "secret",
            "file_name": "input.txt",
        }
        for i in range(3)
    ]
    (directory / "metadata.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    (directory / "input.txt").write_text("hello")
    selected = read_instances(tmp_path, "validation", 1, 1)
    assert len(selected) == 1
    request = make_request(selected[0], tmp_path, "validation")
    assert "secret" not in request.model_dump_json()
    assert base64.b64decode(request.attachments[0].data_base64) == b"hello"
    rows[0]["file_name"] = "../../../outside"
    with pytest.raises(ValueError):
        make_request(rows[0], tmp_path, "validation")


def test_gaia_attachment_layout_matches_upstream(tmp_path):
    directory = tmp_path / "2023" / "validation"
    directory.mkdir(parents=True)
    (directory / "report.PDF").write_bytes(b"pdf")
    request = make_request(
        {"task_id": "file", "Question": "read", "file_name": "report.PDF"},
        tmp_path,
        "validation",
    )
    assert [item.name for item in request.attachments] == ["file.pdf"]
    assert "/workspace/file.pdf" in instruction(request)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("folder/a.txt", "a")
        zipped.writestr("b.csv", "b")
    (directory / "files.zip").write_bytes(archive.getvalue())
    request = make_request(
        {"task_id": "zip", "Question": "read", "file_name": "files.zip"},
        tmp_path,
        "validation",
    )
    assert [item.name for item in request.attachments] == ["a.txt", "b.csv"]
    assert "/workspace/a.txt, /workspace/b.csv" in instruction(request)


def test_image_is_model_content_not_workspace_file(tmp_path):
    directory = tmp_path / "2023" / "validation"
    directory.mkdir(parents=True)
    (directory / "picture.png").write_bytes(b"png")
    request = make_request(
        {"task_id": "image", "Question": "look", "file_name": "picture.png"},
        tmp_path,
        "validation",
    )
    assert "image shown below" in instruction(request)
    assert "/workspace/picture.png" not in instruction(request)


@pytest.mark.parametrize("member", ["../escape.txt", "/absolute.txt", "..\\escape.txt"])
def test_zip_traversal_rejected(tmp_path, member):
    directory = tmp_path / "2023" / "validation"
    directory.mkdir(parents=True)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(member, "no")
    (directory / "unsafe.zip").write_bytes(archive.getvalue())
    with pytest.raises(ValueError, match="Unsafe ZIP member"):
        make_request(
            {"task_id": "zip", "Question": "read", "file_name": "unsafe.zip"},
            tmp_path,
            "validation",
        )


@pytest.mark.parametrize(
    "answer,truth,expected",
    [
        ("$1,000", "1000", True),
        ("New York!", "new york", True),
        ("b,a", "a,b", False),
        ("2;cat", "2,Cat", True),
        ("a-b,c", "ab,c", False),
        ("42", "", None),
        ("42", "?", None),
        ("42", None, None),
        ("abc", "42", False),
    ],
)
def test_scoring(answer, truth, expected):
    assert score(answer, truth) is expected


def test_hidden_test_answers_not_reported_as_zero_accuracy():
    assert summarize([{"status": "completed", "score": None}])["accuracy"] is None
