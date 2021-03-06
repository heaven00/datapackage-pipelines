.PHONY: all install list lint release test version


PACKAGE := $(shell grep '^PACKAGE =' setup.py | cut -d "'" -f2)
VERSION := $(shell head -n 1 $(PACKAGE)/VERSION)


all: list

install:
	pip install --upgrade -e .[develop]

install-speedup:
	pip install --upgrade -e .[develop,speedup]

list:
	@grep '^\.PHONY' Makefile | cut -d' ' -f2- | tr ' ' '\n'

lint:
	pylama $(PACKAGE)

release:
	bash -c '[[ -z `git status -s` ]]'
	git tag -a -m release $(VERSION)
	git push --tags

test:
	tox && tests/exit-codes/test_cli_exit_codes.sh

version:
	@echo $(VERSION)
