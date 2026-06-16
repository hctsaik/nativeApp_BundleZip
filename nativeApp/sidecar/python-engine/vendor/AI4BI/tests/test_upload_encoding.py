"""Round 168r: upload robustness — non-UTF-8 CSVs (Big5/CP950) and Excel.

Regression for two real-world upload failures:
  * 'utf-8' codec can't decode byte 0xa6 … (a Big5-encoded Taiwanese CSV)
  * Import xlrd failed … (legacy .xls / Excel support)
"""
from __future__ import annotations

import io

import pandas as pd

from ai4bi.ui.upload import _load_file, _read_csv_any_encoding


class _Fake:
    """Minimal stand-in for a Streamlit UploadedFile (name + read())."""
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def read(self) -> bytes:
        return self._data


def test_read_csv_big5_is_decoded():
    df = pd.DataFrame({"機台": ["ETCH-01", "ETCH-02"], "等待時間": [2.0, 4.0]})
    raw = df.to_csv(index=False).encode("big5")  # byte 0xa6-class content
    out = _read_csv_any_encoding(raw)
    assert list(out.columns) == ["機台", "等待時間"]
    assert out["機台"].tolist() == ["ETCH-01", "ETCH-02"]


def test_load_file_big5_csv():
    df = pd.DataFrame({"縣市": ["臺北", "臺中"], "件數": [10, 20]})
    raw = df.to_csv(index=False).encode("big5")
    out = _load_file(_Fake("查緝經濟犯罪績效.csv", raw))
    assert out is not None
    assert out["縣市"].tolist() == ["臺北", "臺中"]


def test_load_file_utf8_csv_still_works():
    df = pd.DataFrame({"city": ["A"], "rev": [1]})
    out = _load_file(_Fake("x.csv", df.to_csv(index=False).encode("utf-8")))
    assert out is not None and out["rev"].tolist() == [1]


def test_load_file_xlsx():
    df = pd.DataFrame({"科目": ["國文", "數學"], "分數": [90, 85]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    out = _load_file(_Fake("月考成績單.xlsx", buf.getvalue()))
    assert out is not None
    assert out["分數"].tolist() == [90, 85]
