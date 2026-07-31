# Deferred work — self-dogfood S0–S7 matrix

Items surfaced during review that are NOT caused by this change, or are acceptable
tradeoffs deferred by design. Surfaced again at step-05. None block this spec.

## From step-03b self-review (defer — not caused by this change / acceptable tradeoff)

- **[perf] `scenarios/test_s4b_mcp.py` subprocess-per-test (~2–4s).**
  Each S4b test spawns a full `pytest` subprocess (interpreter startup + collection +
  plugin import) to exercise a thin RPC wrapper; `build_server` is re-created per test
  with no session-scoped fixture. Acceptable at current suite size; revisit with a shared
  server fixture + `tmp_path`-scoped scenario project if the dogfood suite grows.
  *Why deferred:* pre-existing cost shape of `mcp.run_scenario` (it subprocess-invokes
  pytest by design); not a regression introduced here.

- **[error-handling] `scenarios/conftest.py` `pytest_collect_file` hook ordering vs plugin.**
  The conftest's collection-time guard against a leaked `known-failures.yaml` may be
  shadowed by `testvibe.plugin.pytest_collect_file` depending on hook registration order,
  so the "clear collection-time error" may not fire; the session-scoped `_isolation_guard`
  fixture is the real backstop (runs regardless). *Why deferred:* defense-in-depth is
  weaker than documented but still functional via the session fixture; pinning hook order
  is a pytest-internals concern outside this spec.

- **[test-coverage] `scenarios/test_s3_canary.py` backoff timing not asserted.**
  The successful-retry test uses `base=0.0` (suppresses delays) for speed, so a regression
  removing the `time.sleep` / `2**attempt` scaling is invisible. *Why deferred:* keeping
  the canary test fast was an intentional tradeoff; a timing assertion would couple the
  dogfood gate to wall-clock. Could add a `monkeypatch` spy on `time.sleep` later.

## Out-of-spec production finding (surfaced incidentally — NOT addressed; src/testvibe frozen)

- **[bug] `.github/actions/testvibe-gate/action.yml:30` runs bare `mypy` with no target.**
  `run: mypy` errors `Missing target module, package, files, or command.` unless a files
  target is configured. This is a latent bug in testvibe's own S0 CI gate (pre-existing,
  at baseline). Not caused by this spec (src/testvibe untouched). Candidate follow-up:
  `run: mypy src` (or add `files = ["src"]` under `[tool.mypy]`).
