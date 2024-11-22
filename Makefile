GIT_COMMIT_MESSAGE ?= "Automatic commit from Makefile"

BRANCH ?= main

.PHONY: pep8-check pep8-fix format lint

format:
	black .
	isort .

lint:
	- flake8 .
	- mypy .

pep8-check:
	- pylint --disable=all --enable=C,E,F,W,R $(shell find . -name "*.py")

pep8-fix:
	- autopep8 --in-place --recursive .

.PHONY: commit
commit:
	git add .
	git commit -m "$(GIT_COMMIT_MESSAGE)"

.PHONY: push
push:
	git push origin $(BRANCH)

.PHONY: all

all: pep8-fix format lint commit push