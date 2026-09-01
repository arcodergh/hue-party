.PHONY: help install service-install service-uninstall dev run test lint format build clean
help:            ## List available commands
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "%-18s %s\n", $$1, $$2}'
install:         ## Install all dependencies
	uv sync
service-install: ## Install, enable, and start hue-party as a systemd user service
	./scripts/install-service.sh
service-uninstall: ## Stop the service and remove it from startup
	-systemctl --user disable --now hue-party
	rm -f $(HOME)/.config/systemd/user/hue-party.service
	systemctl --user daemon-reload
	@echo "hue-party service removed."
dev: run         ## Alias for run
run:             ## Start the party server
	uv run hue-party run
test:            ## Run test suite
	uv run pytest
lint:            ## Ruff + mypy
	uv run ruff check . && uv run mypy src
format:          ## Format code
	uv run ruff format .
build:           ## Build wheel
	uv build
clean:           ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist **/__pycache__
