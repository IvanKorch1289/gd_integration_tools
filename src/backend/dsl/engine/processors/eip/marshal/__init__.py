from __future__ import annotations
"""EIP marshal processors package (S63 W3 decomp from marshal.py 494 LOC).

8 classes + 3 helpers decomposed в 3 files (per concern):
- ``base.py``: DataFormat (base, 4 methods)
- ``formats.py``: 5 data format classes (Json/Xml/Csv/MessagePack/Pickle) + 3 helpers
- ``processors.py``: MarshalProcessor, UnmarshalProcessor

Backward-compat: ``from src.backend.dsl.engine.processors.eip.marshal import MarshalProcessor`` works.
"""


from src.backend.dsl.engine.processors.eip.marshal.base import DataFormat  # S63 W3: re-export
from src.backend.dsl.engine.processors.eip.marshal.formats import JsonDataFormat  # S63 W3: re-export
from src.backend.dsl.engine.processors.eip.marshal.formats import XmlDataFormat  # S63 W3: re-export
from src.backend.dsl.engine.processors.eip.marshal.formats import CsvDataFormat  # S63 W3: re-export
from src.backend.dsl.engine.processors.eip.marshal.formats import MessagePackDataFormat  # S63 W3: re-export
from src.backend.dsl.engine.processors.eip.marshal.formats import PickleDataFormat  # S63 W3: re-export
from src.backend.dsl.engine.processors.eip.marshal.processors import MarshalProcessor  # S63 W3: re-export
from src.backend.dsl.engine.processors.eip.marshal.processors import UnmarshalProcessor  # S63 W3: re-export
from src.backend.dsl.engine.processors.eip.marshal.formats import _json_default  # S63 W3: helper re-export
from src.backend.dsl.engine.processors.eip.marshal.formats import _dict_to_xml  # S63 W3: helper re-export
from src.backend.dsl.engine.processors.eip.marshal.formats import _xml_to_dict  # S63 W3: helper re-export

__all__ = (
    "DataFormat",
    "JsonDataFormat",
    "XmlDataFormat",
    "CsvDataFormat",
    "MessagePackDataFormat",
    "PickleDataFormat",
    "MarshalProcessor",
    "UnmarshalProcessor",
    "_json_default",
    "_dict_to_xml",
    "_xml_to_dict",
)
