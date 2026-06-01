"""Banking-namespace unit-тесты для DSL-процессоров.

Wave ``[wave:s6/k3-banking-processors-tests]``.

Содержит 12 unit-тестов на banking-domain процессоры:

* ``document_parsers`` (markitdown через ``ingest_file``)
* ``evaluate_rules`` (simpleeval)
* ``render_docx`` (python-docx)
* ``render_xlsx`` (openpyxl)
* ``mask_pii`` (presidio)
* ``pdf_template`` (reportlab)
* ``regex_extractor``
* ``json_path``
* ``unit_conversion`` (pint)
* ``ics_calendar`` (icalendar)
* ``webdav`` (webdav4)
* ``geo`` (geopy)

Цель: покрытие banking-namespace ≥85% (KYC/AML, document scanning,
credit scoring, financial document OCR).
"""
