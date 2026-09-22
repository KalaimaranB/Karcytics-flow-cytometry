"""Compatibility layer for Matplotlib Qt backends.

``LockedFigureCanvas`` now lives in the SDK
(``karcytics_sdk.plugin.rendering.mpl_canvas``), next to
``LayeredMatplotlibCanvas`` which uses the same lock-guarded paint/draw
pattern — this module just re-exports it so existing call sites in this
plugin keep working unchanged.
"""

try:
    from karcytics_sdk.plugin.rendering.mpl_canvas import LockedFigureCanvas  # noqa: F401
except ImportError:
    pass
