"""Constants for the Tutorials module."""

# ── Tutorial Sample Thresholds ───────────────────────────────────────
# Minimum number of total samples required to pass the 'Import Data' tutorial step.
MIN_TOTAL_SAMPLES = 10

# Minimum number of FMO (Fluorescence Minus One) controls required.
MIN_FMO_CONTROLS = 5

# Minimum number of full panel (fully stained) samples required.
MIN_FULL_PANEL_SAMPLES = 3

# ── Scaling & Gating Validation ──────────────────────────────────────
# Tolerance for checking outlier percentile equivalence.
OUTLIER_PERCENTILE_TOLERANCE = 0.001

# Range gate threshold for identifying the "positive" population.
RANGE_GATE_HIGH_THRESHOLD = 50_000

# Minimum X bound for a gate to be considered appropriately placed.
GATE_MIN_X_BOUND = -1000

# ── Visual Alignment Validation ──────────────────────────────────────
# Minimum Intersection-over-Union (IoU) for a drawn gate to be considered correct.
MIN_GATE_IOU = 0.90

# Tolerance for axis bounds deviation (as a fraction of total axis range).
AXIS_BOUNDS_TOLERANCE = 0.10

# ── Validation Polling ───────────────────────────────────────────────
# Time (in seconds) between log emission when polling for a long-running step.
POLL_LOG_INTERVAL = 5.0

# ── Gate-drawing steps ───────────────────────────────────────────────
# Spotlit alongside the tool and the plot on gate-drawing steps, so the
# right panel (Properties | Histogram switch, Group Preview) stays usable
# while the user draws. Must stay a literal objectName — see
# tests/unit/tutorials/test_target_names.py.
RIGHT_PANEL_TARGET = "PropertiesPanel"
RIGHT_PANEL_HINT = (
    "The panel on the right (highlighted) stays usable while you draw: scroll its "
    "**Group Preview**, or switch it to **Histogram** when the main plot isn't one already."
)

# The Compensation tab's preview choices, as the widgets store them
# (`compensation_editor.ALL_SAMPLES`, `compensation_preview.VIEW_BOTH`). Kept
# here so course modules don't import widget code; a test holds them equal.
PREVIEW_ALL_SAMPLES = "__all__"
PREVIEW_VIEW_BOTH = "both"
