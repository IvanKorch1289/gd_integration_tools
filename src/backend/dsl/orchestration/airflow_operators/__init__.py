from __future__ import annotations
"""Airflow operators package (S65 W1 decomp from airflow_operators.py 485 LOC).

6 classes + 1 helper → 7 files (per-class file split):
- ``branchpythonoperator.py``: BranchPythonOperator
- ``shortcircuitoperator.py``: ShortCircuitOperator
- ``latestonlyoperator.py``: LatestOnlyOperator
- ``branchdatetimeoperator.py``: BranchDateTimeOperator
- ``externaltasksensor.py``: ExternalTaskSensor
- ``branchselector.py``: BranchSelector
- ``helpers.py``: 1 top-level helper

Backward-compat: ``from src.backend.dsl.orchestration.airflow_operators import BranchPythonOperator`` works.
"""


from src.backend.dsl.orchestration.airflow_operators.branchpythonoperator import BranchPythonOperator  # S65 W1: re-export
from src.backend.dsl.orchestration.airflow_operators.shortcircuitoperator import ShortCircuitOperator  # S65 W1: re-export
from src.backend.dsl.orchestration.airflow_operators.latestonlyoperator import LatestOnlyOperator  # S65 W1: re-export
from src.backend.dsl.orchestration.airflow_operators.branchdatetimeoperator import BranchDateTimeOperator  # S65 W1: re-export
from src.backend.dsl.orchestration.airflow_operators.externaltasksensor import ExternalTaskSensor  # S65 W1: re-export
from src.backend.dsl.orchestration.airflow_operators.branchselector import BranchSelector  # S65 W1: re-export
from src.backend.dsl.orchestration.airflow_operators.helpers import _default_latest_checker  # S65 W1: helper re-export

__all__ = (
    "BranchPythonOperator",
    "ShortCircuitOperator",
    "LatestOnlyOperator",
    "BranchDateTimeOperator",
    "ExternalTaskSensor",
    "BranchSelector",
    "_default_latest_checker",
)
