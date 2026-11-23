"""The ways to obtain a spillover matrix, in the method selector's order."""

from __future__ import annotations

from .base import MatrixSource
from .csv_import import CsvImportSource
from .fcs_metadata import FcsMetadataSource
from .fmo import FmoSource
from .manual import ManualSource
from .single_stain import SingleStainSource

# In the selector's order. The first method that is ready is the default, so
# the matrix the cytometer recorded wins whenever the files carry one.
MATRIX_SOURCES: tuple[MatrixSource, ...] = (
    FcsMetadataSource(),
    SingleStainSource(),
    FmoSource(),
    CsvImportSource(),
    ManualSource(),
)
