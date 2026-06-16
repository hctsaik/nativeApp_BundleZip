"""Round 176: join cardinality detection (Phase 1b).

The workspace 🔗 關聯 tab infers a relationship's cardinality from SAMPLES
(resource-safe) so a non-technical user is warned before creating a many-to-many
join that would fan out and inflate their numbers (scenario S7).
"""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.ui.data_model import cardinality_from_keys, detect_cardinality
from ai4bi.ui.upload import infer_block


def _contract(df: pd.DataFrame, bid: str):
    contract, _metrics, _dims = infer_block(df, bid, bid)
    return contract


# --- pure mapping ---------------------------------------------------------

@pytest.mark.parametrize("lu,ru,label,risky", [
    (True, True, "1:1", False),
    (False, True, "N:1", False),
    (True, False, "1:N", False),
    (False, False, "N:N", True),
    (None, True, "未知", True),
    (True, None, "未知", True),
])
def test_cardinality_from_keys(lu, ru, label, risky):
    assert cardinality_from_keys(lu, ru) == (label, risky)


# --- sampled detection over real contracts --------------------------------

def test_detect_many_to_one_is_safe():
    fact = _contract(pd.DataFrame({"store_id": [1, 1, 2, 2, 3], "amt": [10, 20, 30, 40, 50]}), "fact")
    dim = _contract(pd.DataFrame({"store_id": [1, 2, 3], "label": ["a", "b", "c"]}), "dim")
    label, risky = detect_cardinality(fact, "store_id", dim, "store_id")
    assert label == "N:1"
    assert risky is False


def test_detect_one_to_one():
    a = _contract(pd.DataFrame({"id": [1, 2, 3], "x": [1, 2, 3]}), "a")
    b = _contract(pd.DataFrame({"id": [1, 2, 3], "y": [4, 5, 6]}), "b")
    assert detect_cardinality(a, "id", b, "id") == ("1:1", False)


def test_detect_many_to_many_is_risky():
    a = _contract(pd.DataFrame({"k": [1, 1, 2, 2], "v": [1, 2, 3, 4]}), "a")
    b = _contract(pd.DataFrame({"k": [1, 1, 2, 2], "w": [5, 6, 7, 8]}), "b")
    label, risky = detect_cardinality(a, "k", b, "k")
    assert label == "N:N"
    assert risky is True


def test_detect_unknown_when_column_missing():
    a = _contract(pd.DataFrame({"id": [1, 2, 3]}), "a")
    b = _contract(pd.DataFrame({"id": [1, 2, 3]}), "b")
    label, risky = detect_cardinality(a, "nonexistent", b, "id")
    assert label == "未知"
    assert risky is True
