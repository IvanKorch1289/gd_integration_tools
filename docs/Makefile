# Minimal Sphinx Makefile for gd_integration_tools.
#
# Targets:
#   html   — сборка HTML-документации в _build/html
#   clean  — очистка артефактов сборки
#   serve  — локальный HTTP-сервер для просмотра html
#
# Требуется python с установленным `sphinx`, `sphinx-autoapi`, `myst-parser`.

SPHINXBUILD   ?= sphinx-build
SPHINXOPTS    ?=
SOURCEDIR     = .
BUILDDIR      = _build

.PHONY: help html clean serve

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

html:
	$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS)

clean:
	rm -rf "$(BUILDDIR)"
	rm -rf api

serve: html
	@echo "Documentation at http://localhost:8765"
	@python -m http.server 8765 --directory "$(BUILDDIR)/html"
