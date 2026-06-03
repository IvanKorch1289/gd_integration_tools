"""Tests for dsl/transforms/dataframes.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

import polars as pl
import pytest

from src.backend.dsl.transforms.dataframes import read_csv, read_excel, write_parquet


class TestDataframeTransforms:
    def test_read_csv(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            f.write("a,b\n1,2\n3,4\n")
            path = f.name
        try:
            df = read_csv(path)
            assert isinstance(df, pl.DataFrame)
            assert df.shape == (2, 2)
        finally:
            Path(path).unlink()

    def test_read_excel(self) -> None:
        pytest.importorskip("xlsxwriter")
        df = pl.DataFrame({"x": [1, 2], "y": [3, 4]})
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name
        try:
            df.write_excel(path)
            result = read_excel(path)
            assert isinstance(result, pl.DataFrame)
            assert result.shape == (2, 2)
        finally:
            Path(path).unlink()

    def test_write_parquet(self) -> None:
        df = pl.DataFrame({"a": [1, 2]})
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            path = f.name
        try:
            write_parquet(df, path)
            read = pl.read_parquet(path)
            assert read.shape == (2, 1)
        finally:
            Path(path).unlink()
