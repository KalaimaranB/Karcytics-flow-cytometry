Not run by pre-commit (which only runs `tests/unit/`) — run explicitly when a change touches cross-module behavior:

```bash
uv run pytest tests/integration/ -q
```

- `test_ui_daemon.py` — spawns the *real* `ui_daemon.py` subprocess under this plugin's own interpreter and speaks the actual msgpack-over-stdio protocol, with nothing mocked. This is the test that actually proves `process_model = "isolated"` works standalone, not just that imports resolve — if you change the daemon handshake/dispatch protocol in the SDK's `ui_daemon_runtime.py` or this plugin's `ui_daemon.py`, this is the test that will catch a break.

Real-data gating coverage lives in `tests/functional/test_gating_pipeline.py`: golden counts for one realistic gate tree on the real Specimen_001 FCS files, driven through `DagEvaluator`, `apply_hierarchy` and `PopulationService`. If a change intentionally moves those counts, re-derive and update its table — don't loosen them into ranges.
