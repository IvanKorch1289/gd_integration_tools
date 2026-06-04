# Minimal makefile for Sphinx (S40 W4 — auto-generated API reference).
#
#   make html         — собрать HTML в _build/html/
#   make clean        — удалить _build/ и _apidoc/
#   make apidoc       — только sphinx-apidoc (регенерация RST-файлов)
#   make help         — список целей

SPHINXOPTS    ?= -W --keep-going
SPHINXBUILD   ?= sphinx-build
SPHINXAPIDOC  ?= sphinx-apidoc
SOURCEDIR     = .
BUILDDIR      = _build
APIDOCDIR     = _apidoc
PROJECTDIR    = ../..
APISRC        = $(PROJECTDIR)/src/backend/dsl

# Prefer local .venv/bin binaries if present.
ifneq ($(wildcard $(PROJECTDIR)/.venv/bin/sphinx-build),)
SPHINXBUILD := $(PROJECTDIR)/.venv/bin/sphinx-build
endif
ifneq ($(wildcard $(PROJECTDIR)/.venv/bin/sphinx-apidoc),)
SPHINXAPIDOC := $(PROJECTDIR)/.venv/bin/sphinx-apidoc
endif

.PHONY: help clean apidoc html

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

clean:
	rm -rf "$(BUILDDIR)" "$(APIDOCDIR)"

apidoc:
	@mkdir -p "$(APIDOCDIR)"
	$(SPHINXAPIDOC) -f -e -M -T -d 2 --module-first --implicit-namespaces \
		-o "$(APIDOCDIR)" "$(APISRC)"

html: apidoc
	@mkdir -p "$(BUILDDIR)/html"
	$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS) $(O)
	@echo "Build finished. HTML pages in $(BUILDDIR)/html/."

# Proxy any other standard Sphinx target.
%:
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
