"""
BlockLoader — load, validate, and register DataBlockContracts.

Capabilities
------------
* Load a JSON file and validate it as a DataBlockContract (Pydantic v2).
* Convert InlineDataSource records to a PyArrow Table.
* Register an Arrow Table into an in-process DuckDB connection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pyarrow as pa
import pyarrow.lib  # noqa: F401 — ensures pa.Table is importable
import duckdb

from ai4bi.blocks.contracts import CachedDataSource, DataBlockContract, InlineDataSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _records_to_arrow(records: list[dict]) -> pa.Table:
    """
    Convert a list of row-dicts to a PyArrow Table.

    Handles mixed-type columns and None values correctly by inferring the
    schema from all rows rather than just the first.
    """
    if not records:
        return pa.table({})

    # Collect all keys across all records (some rows may be sparse)
    all_keys: list[str] = list({k for row in records for k in row.keys()})

    columns: dict[str, list] = {k: [] for k in all_keys}
    for row in records:
        for key in all_keys:
            columns[key].append(row.get(key, None))

    arrays: dict[str, pa.Array] = {}
    for key, values in columns.items():
        # Let PyArrow infer the type; this handles int, float, str, bool, None
        arrays[key] = pa.array(values)

    return pa.table(arrays)


# ---------------------------------------------------------------------------
# BlockLoader
# ---------------------------------------------------------------------------

class BlockLoader:
    """
    Stateless loader for DataBlockContract JSON files.

    All methods are instance methods for easy subclassing / mocking, but none
    hold state — you can use a single instance across many calls.
    """

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_json(self, path: str) -> DataBlockContract:
        """
        Read a JSON file from *path* and validate it as a DataBlockContract.

        Parameters
        ----------
        path:
            Absolute or relative file path to the ``.json`` contract file.

        Returns
        -------
        DataBlockContract
            Fully-validated contract instance.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        json.JSONDecodeError
            If the file is not valid JSON.
        pydantic.ValidationError
            If the JSON does not satisfy the DataBlockContract schema.
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Contract file not found: {file_path.resolve()}")

        raw = file_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return DataBlockContract.model_validate(data)

    # ------------------------------------------------------------------
    # Arrow conversion
    # ------------------------------------------------------------------

    def to_arrow(self, contract: DataBlockContract) -> pa.Table:
        """
        Convert an InlineDataSource contract to a PyArrow Table.

        Parameters
        ----------
        contract:
            A validated DataBlockContract whose ``data_source`` is an
            ``InlineDataSource``.

        Returns
        -------
        pa.Table
            Arrow table containing the inline records.

        Raises
        ------
        TypeError
            If the contract's data_source is not an InlineDataSource.
        """
        if isinstance(contract.data_source, InlineDataSource):
            return _records_to_arrow(contract.data_source.records)
        if isinstance(contract.data_source, CachedDataSource):
            # Round 051: rows live in the content-addressed store, not the contract
            from ai4bi.blocks.datastore import get_dataframe
            return pa.Table.from_pandas(
                get_dataframe(contract.data_source.content_hash), preserve_index=False
            )
        raise TypeError(
            f"to_arrow() requires an in-process data source (inline/cached), "
            f"got {type(contract.data_source).__name__} for block '{contract.block_id}'"
        )

    # ------------------------------------------------------------------
    # DuckDB registration
    # ------------------------------------------------------------------

    def register_to_duckdb(
        self,
        contract: DataBlockContract,
        table_name: str,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        """
        Register an InlineDataSource contract as a DuckDB view.

        The Arrow Table produced by :meth:`to_arrow` is registered as a
        DuckDB relation under *table_name*, making it queryable with standard
        SQL via *conn*.

        Parameters
        ----------
        contract:
            Validated contract (must use InlineDataSource).
        table_name:
            Name to use for the DuckDB table/view.
        conn:
            Open DuckDB connection to register the table into.

        Raises
        ------
        TypeError
            If the data_source is not InlineDataSource.
        """
        arrow_table = self.to_arrow(contract)
        # DuckDB can directly query Arrow tables registered as relations
        conn.register(table_name, arrow_table)

    # ------------------------------------------------------------------
    # Convenience: load + register in one call
    # ------------------------------------------------------------------

    def load_and_register(
        self,
        path: str,
        table_name: Optional[str],
        conn: duckdb.DuckDBPyConnection,
    ) -> DataBlockContract:
        """
        Load a contract JSON file and immediately register it into DuckDB.

        Parameters
        ----------
        path:
            Path to the ``.json`` contract file.
        table_name:
            DuckDB table name; defaults to the contract's ``block_id``.
        conn:
            Open DuckDB connection.

        Returns
        -------
        DataBlockContract
            The loaded and validated contract.
        """
        contract = self.load_json(path)
        effective_name = table_name if table_name is not None else contract.block_id
        self.register_to_duckdb(contract, effective_name, conn)
        return contract
