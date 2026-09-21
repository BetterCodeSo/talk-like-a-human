PYTHON ?= python3
DOCS   := README.md CHANGELOG.md

.PHONY: all test lint-docs shellcheck check install install-git clean

all: check

test:
	$(PYTHON) -m unittest discover -s tests -v

lint-docs:
	$(PYTHON) prose_lint.py $(DOCS)

shellcheck:
	@command -v shellcheck >/dev/null 2>&1 \
		|| { echo "shellcheck not installed; skipping"; exit 0; }; \
	shellcheck install.sh git-hooks/pre-commit git-hooks/commit-msg

check: test lint-docs shellcheck

install:
	./install.sh

install-git:
	./install.sh --git

clean:
	rm -rf __pycache__ tests/__pycache__ .pytest_cache
