"""What a gating plot shows (display mode) and which gate tool is active."""

from __future__ import annotations

from enum import Enum


class DisplayMode(Enum):
    """Available plot display modes."""

    PSEUDOCOLOR = "Pseudocolor"
    DOT_PLOT = "Dot Plot"
    CONTOUR = "Contour"
    HISTOGRAM = "Histogram"
    CDF = "CDF"


class GateDrawingMode(Enum):
    """Active gate drawing tool."""

    NONE = "none"  # Default — pointer / selection mode
    RECTANGLE = "rectangle"
    POLYGON = "polygon"
    ELLIPSE = "ellipse"
    QUADRANT = "quadrant"
    RANGE = "range"
