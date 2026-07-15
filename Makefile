.PHONY: smoke test-critical test-all lint ruff test-drift install-hooks help

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

test-critical: ## Run critical regression subset (~1 min, 159 tests) — pre-commit safety net
	cd backend && python -m pytest \
		tests/test_iter55_16_permissions.py \
		tests/test_iter55_16b_audit_perm_snapshot.py \
		tests/test_company_fund_adjustments.py \
		tests/test_iter55_18_delete_notifications.py \
		tests/test_iter55_19c_crypto_network_validation.py \
		tests/test_iter55_19h_tx_hash_network_validation.py \
		tests/test_iter14_corrections.py \
		tests/test_totp_2fa.py \
		tests/test_iter55_37_session_regression.py \
		tests/test_iter55_36m_defensive_mode_toggle.py \
		tests/test_iter55_36o_verification_gate.py \
		tests/test_iter55_36q_bulk_approve_kyc.py \
		-q --tb=line

test-all: ## Run the full pytest suite (~8-9 min, 935+ tests)
	cd backend && python -m pytest tests/ -q --tb=line

lint: ## Frontend eslint (react-hooks + syntax)
	cd frontend && yarn lint

ruff: ## Backend ruff — undefined names + literal comparisons
	python -m ruff check --select F821,F822,F632 backend/

test-drift: smoke ## Alias for `smoke`

install-hooks: ## Wire up .git/hooks/pre-commit (one-time per clone)
	git config core.hooksPath .githooks
	@echo "✓ Git hooks pointing to .githooks/. Every commit now runs the secret-scan + critical tests."
