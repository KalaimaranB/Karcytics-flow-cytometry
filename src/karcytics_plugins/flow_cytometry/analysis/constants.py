"""Constants for the Flow Cytometry module."""

# ── Group Preview / Thumbnail Rendering ──────────────────────────────
# Default number of events for main plot (Optimized mode)
MAIN_PLOT_MAX_EVENTS_OPTIMIZED = 100_000

# Default number of events for thumbnails (Single pass)
PREVIEW_LIMIT_DEFAULT = 100_000

# Visual size of the thumbnail in pixels (width, height)
PREVIEW_THUMBNAIL_SIZE = (160, 160)

PREVIEW_BG_COLOR = "#FFFFFF"
PREVIEW_THROTTLE_MS = 300  # Throttle real-time previews to ~3 FPS for stability

# ── Rendering Constraints ────────────────────────────────────────────
DEFAULT_NBINS_MIN = 512
DEFAULT_NBINS_MAX = 8192
NBINS_SCALING_FACTOR = 1.5
SIGMA_MIN = 0.1
SIGMA_SCALING_FACTOR = 2.2

DENSITY_THRESHOLD_MIN = 0.05
DENSITY_THRESHOLD_PCT = 0.02

VIBRANCY_MIN = 0.15
VIBRANCY_RANGE = 0.85

DEFAULT_DENSITY_FACTOR = 0.1
PSEUDOCOLOR_MAX_EVENTS = 150_000

# ── Gate Overlay Colors ──────────────────────────────────────────────
# Single source of truth for gate colors, so a given gate renders identically
# on the main plot, subplot thumbnails, and node-graph previews.
GATE_COLOR_PALETTE = [
    "#FF0000",  # Red
    "#0000FF",  # Blue
    "#008000",  # Green
    "#FF8C00",  # Dark Orange
    "#8B008B",  # Dark Magenta
]
GATE_SELECTED_COLOR = "#2188FF"  # Blue for the selected gate
GATE_DRAWING_COLOR = "#333333"  # In-progress/temp gate preview (main + subplot)

OVERLAY_COLORS = {
    "default": "#000000",  # Black
    "selected": GATE_SELECTED_COLOR,
    "inactive": "#888888",  # Gray
}

# ── Logicle Defaults ─────────────────────────────────────────────────
LOGICLE_T_DEFAULT = 262144.0
LOGICLE_W_DEFAULT = 1.0
LOGICLE_M_DEFAULT = 4.5
LOGICLE_A_DEFAULT = 0.0

# ── Scaling / Auto-Range ─────────────────────────────────────────────
# Maximum magnitude of a physically plausible FCS channel value.
# Real cytometers never exceed ±1 GFU — values beyond this are artefacts.
PHYSICAL_SIGNAL_MAX = 1e9

# Logicle scale: auto-range will snap to LOGICLE_T_DEFAULT when p_max is in
# the range (LINEAR_SNAP_LO, LOGICLE_T_DEFAULT) for linear mode, and
# (BIEXP_SNAP_LO, LOGICLE_T_DEFAULT) for biexponential mode.
LINEAR_SNAP_LO = 200_000.0
BIEXP_SNAP_LO = 20_000.0

# Logicle W estimation: minimum fraction of events that must be negative
# before we bother estimating W from the negative tail (below this → W=0.5).
LOGICLE_NEG_FRACTION_MIN = 0.005

# Logicle A estimation: below this raw value the negative tail is considered
# negligible and A is set to 0.0.
LOGICLE_A_NEG_THRESHOLD = -10.0

# Minimum number of negative events required to estimate W.
LOGICLE_NEG_COUNT_MIN = 10

# Outlier percentile validation bounds (0–50 is the allowed range).
OUTLIER_PERCENTILE_MAX = 50.0

# ── FCS I/O ──────────────────────────────────────────────────────────
# If acquiring the FCS file lock takes longer than this (seconds) we log a warning.
FCS_LOCK_WARN_SECONDS = 0.5

# If more than this fraction of claimed events is stripped during load we warn.
FCS_STRIP_RATIO_WARN = 0.05

# ── Daemon / IPC ─────────────────────────────────────────────────────
# Minimum header fields expected in a daemon message.
DAEMON_HEADER_MIN_FIELDS = 4

# ── Biology Services ─────────────────────────────────────────────────
HTTP_OK = 200
FPBASE_MAX_MATCHES = 20  # Stop after this many fuzzy matches from FPbase.

# ── Compensation ─────────────────────────────────────────────────────
# Need at least 2 single-stain controls to build a spill matrix.
MIN_SINGLE_STAINS = 2

# Minimum off-diagonal spillover ratio considered non-trivial.
SPILLOVER_SIGNIFICANCE_THRESHOLD = 0.005

# ── Animation ────────────────────────────────────────────────────────
# Minimum number of events needed to proceed with a UMAP animation.
ANIMATION_MIN_EVENTS = 50

# Maximum number of KNN edges to draw in the animation preview (performance cap).
ANIMATION_MAX_KNN_EDGES = 3_000

# Fraction of animation progress at which the "fade-in" phase completes.
ANIMATION_FADE_THRESHOLD = 0.8

# ── UMAP Analysis ────────────────────────────────────────────────────
# Minimum number of events required to run UMAP on a gate population.
UMAP_MIN_EVENTS = 50

# ── Gate Mutation Service ────────────────────────────────────────────
# A logic (AND/OR) gate requires at least 2 real parents.
LOGIC_GATE_MIN_PARENTS = 2

# ── Modifier ─────────────────────────────────────────────────────────
# A polygon gate must have at least 3 vertices.
POLYGON_MIN_VERTICES = 3

# ── Derived Parameters ───────────────────────────────────────────────
# Column-key prefix for user-defined per-event formulas (see analysis/derived/).
# Any channel key with this prefix is computed, never read from the FCS file.
DERIVED_PREFIX = "derived:"
MAX_DERIVED_PARAMETERS = 20
