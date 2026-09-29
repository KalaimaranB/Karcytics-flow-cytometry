Not run by pre-commit (which only runs `tests/unit/`) — run explicitly when a change touches cross-module behavior:

```bash
uv run pytest tests/integration/ -q
```

- `test_ui_daemon.py` — spawns the *real* `ui_daemon.py` subprocess under this plugin's own interpreter and speaks the actual msgpack-over-stdio protocol, with nothing mocked. This is the test that actually proves `process_model = "isolated"` works standalone, not just that imports resolve — if you change the daemon handshake/dispatch protocol in the SDK's `ui_daemon_runtime.py` or this plugin's `ui_daemon.py`, this is the test that will catch a break.
- `test_sample_c_complete_pipeline.py` / `test_workflows.py` — realistic multi-step, real-data pipelines (load FCS → gate → compensate → compute stats) rather than isolated-unit assertions; use these as the reference for what a full user workflow actually exercises.
- `test_stress.py` — 1M-synthetic-event performance/correctness checks; expect this one to be slower.
- `test_axis_sync.py` — cross-component state sync (axis/scale changes propagating through `FlowState`/`CentralEventBus`).
