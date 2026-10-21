import csv

import pytest

from blindcode.codebook import Codebook


@pytest.fixture
def codebook():
    return Codebook.load()


def full_values(**over):
    v = {"stance": "pro_stunt", "incivility": "0", "attacks_op": "0", "target": "none", "slur": "0",
         "hate_speech": "0", "political_identity_attack": "0", "threat": "0", "argument_tag": "other", "note": ""}
    v.update(over)
    return v


@pytest.fixture
def source_csv(tmp_path):
    """A source file shaped like analysis_merged.csv, with metadata coders must never see."""
    p = tmp_path / "source.csv"
    rows = [
        {"uid": "parent_1", "full_text": "@AutisticClip money cant buy everything", "thread": "parent",
         "screen_name": "alice", "is_blue_verified": "True", "views_count": "37704", "organic_rank": "1"},
        {"uid": "child_1", "full_text": "@DirtbagLeft1234 @AutisticClip you are an idiot", "thread": "child",
         "screen_name": "bob", "is_blue_verified": "False", "views_count": "12", "organic_rank": "1"},
        {"uid": "child_2", "full_text": "@DirtbagLeft1234 ask @bob about it", "thread": "child",
         "screen_name": "bob", "is_blue_verified": "False", "views_count": "3", "organic_rank": "2"},
    ]
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return p
