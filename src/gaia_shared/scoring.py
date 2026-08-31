"""GAIA answer normalization, matching the public numeric/list/string protocol.

Reference: https://github.com/OpenHands/benchmarks/blob/main/benchmarks/gaia/scorer.py
This module is an independent implementation; scoring remains outside the agent service.
"""

import re
import string


def numeric(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def normalized(value, punctuation=True):
    result = re.sub(r"\s", "", value).lower()
    return result.translate(str.maketrans("", "", string.punctuation)) if punctuation else result


def number_answer(value):
    return numeric(value.translate(str.maketrans("", "", "$%,")))


def score(answer: str, truth: str | None):
    if truth is None or not truth.strip() or truth.strip() == "?":
        return None
    if numeric(truth) is not None:
        return number_answer(answer) == numeric(truth)
    if "," in truth or ";" in truth:
        expected, actual = re.split("[,;]", truth), re.split("[,;]", answer)
        if len(expected) != len(actual):
            return False
        return all(
            number_answer(a) == numeric(t)
            if numeric(t) is not None
            else normalized(a, False) == normalized(t, False)
            for a, t in zip(actual, expected)
        )
    return normalized(answer) == normalized(truth)


def summarize(rows):
    scored = [r for r in rows if r.get("score") is not None]
    correct = sum(r["score"] is True for r in scored)
    return {
        "instances": len(rows),
        "scored": len(scored),
        "correct": correct,
        "accuracy": correct / len(scored) if scored else None,
        "errors": sum(r.get("status") != "completed" for r in rows),
    }
