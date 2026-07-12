.PHONY: smoke lint ruff test-drift install-hooks help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

smoke: ## Run the 6 drift-guarded smoke tests (~15s) — same as pre-commit
	cd backend && python -m pytest \
		tests/test_admin_users_multicurrency_display.py \
		tests/test_iter27_auth_refactor.py::test_openapi_path_count_unchanged \
		tests/test_multicurrency_and_stats.py::TestVipBalancesEndpoint::test_vip_legacy_plus_dict_usdt_conversion \
		tests/test_p2p_backend.py::TestUsersAdmin::test_list_and_update_user \
		tests/test_p2p_backend.py::TestOrders::test_orders_mine_isolation \
		tests/test_iter55_19g_notification_explorer_link.py \
		-q

lint: ## Frontend eslint (react-hooks + syntax)
	cd frontend && yarn lint

ruff: ## Backend ruff — undefined names + literal comparisons
	python -m ruff check --select F821,F822,F632 backend/

test-drift: smoke ## Alias for `smoke`

install-hooks: ## Wire up .git/hooks/pre-commit (one-time per clone)
	pip install pre-commit
	pre-commit install
	@echo "✓ pre-commit installed. Every commit now runs smoke + ruff + eslint."
