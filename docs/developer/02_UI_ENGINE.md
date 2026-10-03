# UI Engine

This is the detailed reference for the plugin's UI layer: the tab/ribbon/
center-stack shell in `main_panel.py`, the two-phase widget construction in
`WorkspaceBuilder`, the `FlowCanvas` rendering engine, the interactive gate
drawing state machine, the node canvas (Pipeline tab), and the render
settings dialog. See [`00_ARCHITECTURE_OVERVIEW.md`](00_ARCHITECTURE_OVERVIEW.md)
for how this fits into the module as a whole, and
[`08_DATA_FLOW_AND_SIGNAL_CONNECTIONS.md`](08_DATA_FLOW_AND_SIGNAL_CONNECTIONS.md)
for how these widgets talk to each other and to the domain layer.

---

## 1. The Workspace Shell: Tabs, Ribbons, Center Stack

`FlowCytometryPanel` (`ui/main_panel.py`) is built by `WorkspaceBuilder`
(`ui/builders/workspace_builder.py`) around three stacked widgets that all
move together when the user switches the top tab bar:

- `_tab_bar` — a `QTabBar` with 8 tabs, built in `build_skeleton()`.
- `_ribbon_stack` — a `QStackedWidget` of per-tab toolbar widgets.
- `_center_stack` — a `QStackedWidget` of the 6 heavy analysis views.

`FlowCytometryPanel._on_tab_changed(index)` is the single place that wires
tab index to ribbon index and center-stack index. Read it directly
(`ui/main_panel.py`) before changing tab ordering — the mapping is *not*
a uniform 1:1 relationship between tab index and either stack's index:

| Tab # | Tab label | Ribbon shown | Center-stack widget | `_ribbon_stack` visible? |
|---|---|---|---|---|
| 0 | Workspace | `WorkspaceRibbon` | `GraphManager` (index 0) | yes |
| 1 | Compensation | `CompensationRibbon` (empty placeholder, hidden) | `CompensationView` (index 6) | no |
| 2 | Gating | `GatingRibbon` | `GraphManager` (index 0) | yes |
| 3 | Pipeline | `PipelineRibbon` | `NodeCanvas` (index 1) | yes |
| 4 | Statistics | `StatisticsRibbon` (empty placeholder) | `StatisticsExplorer` (index 4) | **no — ribbon stack hidden** |
| 5 | Spectral | `SpectralRibbon` | `SpectralViewer` (index 2) | **no — ribbon stack hidden** |
| 6 | Population Analysis | *(none wired)* | `PopulationAnalysisViewer` (index 3) | **no — ribbon stack hidden** |
| 7 | Comparisons | `ComparisonsRibbon` (empty placeholder) | `ComparisonsViewer` (index 5) | **no — ribbon stack hidden** |

For tabs 0 and 2, `_on_tab_changed` falls through to the `else` branch:
`_center_stack.setCurrentIndex(0)` (always `GraphManager` — Workspace and
Gating are two different ribbons over the *same* graph canvas), and it shows
the left sidebar, properties panel, and ribbon stack. Tabs 1 and 3–7 each
hide the sidebar and properties panel and switch to their own full-width
center widget; tabs 1 and 4–7 additionally hide `_ribbon_stack` entirely,
because those render the wrong ribbon (or nothing).

### The Compensation tab is a full view, built from matrix sources

`CompensationView` (`ui/widgets/compensation_view.py`) owns everything the
tab does. Three pieces, kept separate so a new way of getting a matrix
doesn't touch the other two:

- **`MatrixSource`** (`ui/widgets/matrix_sources.py`) — one way to obtain a
  spillover matrix: `obtain(state, parent)` returns a `SourceResult`
  (matrix, undo label, one-line summary), `None` if the user cancelled, or
  raises `MatrixSourceError`. A source never changes state. The view builds
  its **Method** selector from `MATRIX_SOURCES` (one run button, retargeted
  at the selected method), so an estimator ("smart compensate") is a new
  subclass plus one line in that tuple; `advanced = True` lists it under
  the selector's "Advanced algorithms" slot. `key` is the
  `CompensationMatrix.source` the method's matrices carry — the view maps
  it back to `label` to say which method produced the current numbers, and
  selects that method by default (with no matrix: the first whose
  `readiness(state)` is true, in tuple order). Hand edits don't change
  `source`; they set `CompensationMatrix.fine_tuned`.
- **`CompensationEditor`** (`ui/widgets/compensation_editor.py`) — the matrix
  table and `CompensationPreview`, editing a private working copy handed in
  by `load()`. It never writes to the workspace.
- **`CompensationView`** — decides when things reach the workspace. A
  source's matrix becomes the workspace matrix at once (it does not touch
  sample data). Table edits are a *draft* until **Apply to All**, which
  saves them and calls `apply_compensation_to_all(reapply=True)` when the
  matrix changed since it was last applied — without `reapply`, samples
  already compensated with the old matrix would be skipped and keep its
  values. `refresh()` keeps a draft across tab switches and drops it only
  if the workspace matrix was replaced underneath it (undo, workflow load).

### Three ribbons are known-empty placeholders

`CompensationRibbon` (`ui/ribbons/compensation_ribbon.py`),
`StatisticsRibbon` (`ui/ribbons/statistics_ribbon.py`) and
`ComparisonsRibbon` (`ui/ribbons/comparisons_ribbon.py`) are explicitly
documented, intentional empty placeholders — their module docstrings say so
directly ("kept so that the ribbon stack index alignment... remains
intact" / "controls live inside ComparisonsViewer"). `ComparisonsRibbon`
even sets `setFixedHeight(0)`. This is expected: `StatisticsExplorer` and
`ComparisonsViewer` each own their controls internally, and since their
tabs hide `_ribbon_stack` anyway, the placeholder ribbons are pure
bookkeeping to keep index math from shifting.

!!! question "Open question: is `SpectralRibbon` dead code?"
    `SpectralRibbon` (`ui/ribbons/spectral_ribbon.py`) is **not** documented
    as an intentional placeholder the way the other two are — its class
    docstring reads "Toolbar ribbon for spectral intelligence tools" and its
    module docstring says "Access spectral viewing and compensation tools",
    both implying real controls. But `_setup_ui()` only adds a
    `layout.addStretch()` — there is not a single button, combo box, or any
    other widget in it. And because tab 5 (Spectral) hides `_ribbon_stack`
    entirely (`_on_tab_changed`, `index == 5` branch), this ribbon is
    **structurally unreachable even if it did have controls**: it sits at
    `_ribbon_stack` index 5, but nothing ever shows the ribbon stack while
    that tab is active. It defines an unused signal,
    `open_spectral_viewer_requested = pyqtSignal()`, that nothing in the
    codebase connects to or emits (confirmed by search — no other file
    references it).

    This looks like either (a) a half-finished feature — a ribbon that was
    scaffolded before `SpectralViewer` grew its own internal controls and
    was never deleted, or (b) an earlier design where the ribbon stack
    *was* shown for the Spectral tab, later changed. Worth confirming with
    the team whether `SpectralRibbon` and its unused signal can be deleted
    outright, or whether there's a reason it's still constructed and added
    to the stack every startup for no visible effect.

### `WorkspaceBuilder`'s two-phase construction

See [`00_ARCHITECTURE_OVERVIEW.md` §3](00_ARCHITECTURE_OVERVIEW.md#3-two-phase-startup-flowcytometrypanel)
for the full startup sequence diagram. In UI-engine terms: `build_skeleton()`
constructs all 7 ribbons and the sidebar synchronously (cheap — no
matplotlib), then leaves `_center_stack` holding a single placeholder
`QWidget` (object name `_CenterLoadingPlaceholder`). Each `build_step_*`
static method builds exactly one of the six center widgets; `begin_async_init()`
chains them one per `QTimer.singleShot(0, ...)` tick.
`finalize_center_stack()` removes the placeholder and adds the six real
widgets at the fixed index contract documented in its own comment block.
`connect_tab_bar()` is the very last step — it only wires
`_tab_bar.currentChanged` to `_on_tab_changed` once every center-stack
widget is guaranteed to exist, and emits the `"Ready"` status message.

---

## 2. `FlowCanvas` — the 2-D Plot Rendering Engine

`FlowCanvas` (`ui/graph/flow_canvas.py`) is the matplotlib widget embedded
in each `GraphWindow` tab. It extends the SDK's `LayeredMatplotlibCanvas`
(`karcytics_sdk/plugin/rendering/mpl_canvas.py`) and is composed from
several single-purpose collaborators rather than doing everything itself:

| Collaborator | File | Responsibility |
|---|---|---|
| `FlowDataComputeStage` / `FlowDataRasterizeStage` | `ui/graph/canvas/data_layer.py` | Compute/rasterize split for the expensive scatter/density layer — see `00_ARCHITECTURE_OVERVIEW.md` §5. |
| `GateLayerRenderer` | `ui/graph/canvas/gate_layer.py` | Draws/clears gate overlay artists on top of the cached data-layer bitmap. Never touches the data layer. |
| `GateDrawingFSM` | `ui/graph/gate_drawing_fsm.py` | Interactive gate-drawing/-editing state machine (below). |
| `CanvasEventHandler` | `ui/graph/canvas/event_handler.py` | Translates raw matplotlib mouse/keyboard events into FSM calls. |
| `CoordinateMapper`, `GateFactory`, `GateOverlayRenderer` | `ui/graph/flow_services.py` | Transform/inverse-transform data↔display coordinates; construct `Gate` objects from drawn geometry; render a `Gate` as matplotlib artists. |
| `GateEditor` | `ui/graph/gate_editor.py` | Drag-handle geometry math for editing an existing gate (snapshot/diff/restore/apply-drag). |
| `OverlayManager` | `ui/graph/canvas/overlay_manager.py` | Loading spinner, empty-state message, error banner, on-canvas instruction text. |
| `ZoomHandler` | `ui/graph/canvas/zoom_handler.py` | Scroll-wheel zoom. |
| `AxisFormatter` | `ui/graph/canvas/axis_formatter.py` | Tick formatting for transformed (Logicle/log) axes. |

### Rendering strategies

`DisplayMode` (an `Enum` in `flow_canvas.py`: `PSEUDOCOLOR`, `DOT_PLOT`,
`CONTOUR`, `HISTOGRAM`, `CDF`) selects a `DisplayStrategy` implementation
via `RenderStrategyFactory.get_strategy(mode.value)`
(`ui/graph/renderers/factory.py`). Every strategy implements the abstract
`compute()`/`draw()` split from `ui/graph/renderers/base.py`:

```python
class DisplayStrategy(ABC):
    @abstractmethod
    def compute(self, x, y=None, *, xlim=None, ylim=None, **kwargs) -> Any:
        """Pure numpy/scipy. Must not touch a matplotlib Axes/Figure."""

    @abstractmethod
    def draw(self, ax: Axes, data: Any, **kwargs) -> None:
        """matplotlib Axes calls. Must run under MPL_RASTER_LOCK."""
```

Registered strategies: `PseudocolorStrategy`, `DotPlotStrategy`,
`HistogramStrategy`, `ContourStrategy`, `CdfStrategy` (all in
`ui/graph/renderers/`). `RenderStrategyFactory.get_strategy()` falls back to
`"Dot Plot"` for any unregistered mode name.

`FlowDataComputeStage.compute()` (`ui/graph/canvas/data_layer.py`) branches
on `DisplayMode`: `HISTOGRAM`/`CDF` go through `_compute_1d()` (falls back
to `_compute_2d()` if the 1-D strategy raises), everything else through
`_compute_2d()`. Both paths read per-mode settings out of
`FlowRenderState.render_config` (a `RenderConfig` snapshot — see
`analysis/config.py`) into a `render_kwargs` dict passed straight through to
`strategy.compute(...)`.

### Locking discipline

`FlowCanvas` overrides both `paintEvent()` and `draw()` from
`LayeredMatplotlibCanvas` — not to change their locking strategy (both
already acquire `raster_lock` non-blocking via `try_run`), but because a
queued `QTimer` retry firing after the widget is destroyed crashes natively
rather than raising a catchable `RuntimeError`. `FlowCanvas._retry_update()`
/ `_retry_draw()` guard with `sip.isdeleted(self)` before touching `self`
again. Any new lock-guarded entry point added to `FlowCanvas` should follow
the same `sip.isdeleted()` pattern if it can be retried via `QTimer`.

`GateLayerRenderer.render()` and every interactive-preview method on
`GateDrawingFSM` (rubber band, polygon progress, quadrant crosshair, edit
preview) acquire `MPL_RASTER_LOCK` directly rather than through
`LayeredMatplotlibCanvas`'s helpers, because they need the finer-grained
"clear old artist, add new artist, blit" sequence to happen atomically
under one lock acquisition rather than as two separate `try_run` calls.

---

## 3. Interactive Gate Drawing: `GateDrawingFSM`

`GateDrawingFSM` (`ui/graph/gate_drawing_fsm.py`) owns all interactive
drawing/editing state for one `FlowCanvas`. States (`DrawingState` enum):

| State | Meaning |
|---|---|
| `IDLE` | Default. A press either hits an edit handle, hits the selected gate's body, or attempts gate selection. |
| `DRAWING` | Dragging out a Rectangle/Ellipse/Range gate. |
| `POLYGON` | Placing polygon vertices one click at a time; double-click closes it (≥3 vertices required). |
| `EDITING` | Dragging a handle or the body of the currently-selected gate. |

`CanvasEventHandler` is the only caller of `GateDrawingFSM`'s public
`handle_press`/`handle_motion`/`handle_release`/`handle_dblclick` methods —
it adapts matplotlib's `button_press_event`/`motion_notify_event`/
`button_release_event`/`draw_event` callbacks (wired via `mpl_connect` in
`FlowCanvas.__init__`) into FSM calls, including reading `Alt` directly from
`QApplication.keyboardModifiers()` (matplotlib's own modifier tracking is
documented as unreliable across backends for a bare press with no
preceding key event).

### Drawing tools

`GraphWindow._TOOL_MODE_MAP` (`ui/graph/graph_window.py`) maps the
`GatingRibbon`'s tool id strings to `GateDrawingMode` (also in
`flow_canvas.py`): `"select"`→`NONE`, `"rectangle"`→`RECTANGLE`,
`"polygon"`→`POLYGON`, `"ellipse"`→`ELLIPSE`, `"quadrant"`→`QUADRANT`,
`"range"`→`RANGE`. `GraphManager.set_drawing_mode(tool_name)` broadcasts the
active tool to every open `GraphWindow` so switching tools in the ribbon
affects whichever tab the user switches to next, not just the currently
active one.

### Selection: top-most-wins, with Alt-cycle for occluded gates

`CanvasEventHandler.try_select_gate()` hit-tests every gate's overlay artist
in draw order (later == on top) and, absent `Alt`, picks the last (topmost)
hit. Holding `Alt` on click instead cycles to the *next* hit after whatever
is currently selected (wrapping around) — the documented mechanism for
reaching a gate fully occluded by another without moving or deleting
anything first.

### Edit gestures commit exactly once

`GateDrawingFSM._apply_edit_preview()` mutates the live `Gate` object
in-place on every motion frame and redraws only via the cheap blit path —
it never calls `modify_gate()`. The single real backend mutation (recompute
stats, publish `GATE_MODIFIED`, schedule propagation) happens in
`FlowCanvas._commit_gate_edit()`, called from
`GateDrawingFSM._finish_edit()` on release, and *only* if
`gate_editor.changed(gate, anchor)` reports the geometry actually moved. If
`modify_gate()` rejects the edit (validation failure, or the gate/sample
vanished mid-drag), the FSM's already-mutated in-memory gate is restored
via `gate_editor.restore()` and gates are re-fetched from the controller.
This is also why `Escape` (`GateDrawingFSM.cancel()`) during an in-progress
edit must explicitly call `gate_editor.restore()` — the preview mutation
already happened and nothing else will undo it.

---

## 4. `GraphManager` and `GraphWindow`

`GraphManager` (`ui/graph/graph_manager.py`) is the tabbed container living
at `_center_stack` index 0 — the center widget for the Workspace/
Compensation/Gating tabs. Each open plot is a `GraphWindow`
(`ui/graph/graph_window.py`), keyed in `GraphManager._graphs` by
`f"{sample_id}:{node_id or 'root'}"` — reopening the same sample+population
combination focuses the existing tab instead of creating a duplicate.

`GraphManager._on_axis_scale_sync()` propagates an `AxisScale` change from
one `GraphWindow` to every *other* open graph whose sample shares a group
with the sender's sample (`sender_sample.group_ids`) — scale changes do not
propagate across unrelated groups.

`GraphManager.navigate_active_graph(action)` handles the breadcrumb/
next-sample/prev-sample navigation buttons; `next_sample`/`prev_sample`
call `_get_parallel_node()` to find the equivalently-named gate node in the
target sample by walking the *name path* from root (not by node id, since
node ids are per-sample) — falls back to `None` (root population) if no
name match is found at any step.

---

## 5. The Node Canvas (Pipeline Tab)

`NodeCanvas` (`ui/widgets/node_canvas/canvas_view.py`) is a
`QGraphicsView`-based DAG editor, structurally unrelated to `FlowCanvas` —
it renders with Qt's own 2-D scene graph, not matplotlib, except for the
small per-node preview plots.

### Dirty-region tracking

`_CanvasGraphicsView` extends the SDK's `DirtyTrackingGraphicsView`
(`karcytics_sdk/plugin/rendering/graphics_scene.py`), which defaults to
`QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate` instead of Qt's
default `FullViewportUpdate`. `DirtyTrackingGraphicsScene.mark_dirty(item)`
is the drop-in replacement for a bare `item.update()` call, used
everywhere in `CanvasManager` and `NodeItem` (`_mark_dirty()`) instead of
calling `update()` directly.

`NodeItem.set_orientation()` (`ui/widgets/node_canvas/items/node_item.py`)
is the canonical example of the discipline `MinimalViewportUpdate` demands:
it calls `self.prepareGeometryChange()` *before* mutating `_orientation`
(on which `boundingRect()` depends), because under minimal-update mode a
geometry change that skips `prepareGeometryChange()` leaves stale or
clipped pixels on screen — a bug class that Qt's old `FullViewportUpdate`
default silently papered over by repainting everything regardless. Setting
`KARCYTICS_STRICT_DIRTY_TRACKING=1` turns on an opt-in check in
`DirtyTrackingGraphicsScene.mark_dirty()` that remembers each item's last
`boundingRect()` and logs a warning if it changed since the previous
`mark_dirty()` call for that item — an imperfect signal (it can't see
whether `prepareGeometryChange()` was actually called), but a real prompt
to check when it fires.

### `CanvasManager`: model → scene bridge

`CanvasManager` (`ui/widgets/node_canvas/canvas_manager.py`) builds
`NodeItem`/`EdgeItem` graphics objects from a sample's `GateNode` tree via
BFS (`_build_all_nodes`) so a node with multiple parents (a DAG logic node)
is only ever built once. It subscribes to:

- `task_scheduler.task_finished` — `_on_render_task_finished()` applies a
  completed `RenderTask` thumbnail to its `NodeItem` and caches it in the
  module-level `_ThumbnailCache` dict.
- `CentralEventBus` topic `flow.gate.all_stats_updated`
  (`analysis/events.ALL_STATS_UPDATED`) — `_on_stats_updated()` walks the
  tree updating each `NodeItem`'s displayed count/percentage.
- `"flow.pipeline.connection_added"` / `"flow.pipeline.connection_removed"`
  — `_on_connection_pending()` does a **cheap, targeted** update (redraw
  edges + refresh the one affected card) rather than the full scene rebuild
  `load_sample()` does, specifically so wiring/unwiring a logic node's
  inputs doesn't re-submit render tasks for every other node on the canvas.

### Thumbnail rendering

`_request_render()` submits a `RenderTask` (`ui/graph/render_task.py`,
shared with the main `FlowCanvas`'s gate-overlay rendering path) through
`task_scheduler` at 2x the display size (360×360 for a 180×180 card) for
Retina rendering, with `show_gate_labels=False`/`show_axis_labels=False` in
the passed `render_config` so the thumbnail stays uncluttered. Logic nodes
render a fixed FSC-A/SSC-A overview once `node.is_incomplete` is `False`
(i.e. wired enough to evaluate); UMAP-parent nodes skip rendering entirely
(no geometric axes to plot — `NodeItem.paint()` instead draws a static
isometric-cube icon for them).

---

## 6. Render Settings: `RenderSettingsDialog`

`RenderSettingsDialog` (`ui/graph/render_settings_dialog.py`) is a modeless
`QDialog` (`setModal(False)` — the user can keep interacting with the plot
while tuning settings) that shows one tab per relevant `DisplayMode`, via
`_MODE_TAB = {PSEUDOCOLOR: 0, DOT_PLOT: 1, HISTOGRAM: 2, CONTOUR: 3}`. Each
tab is an independent panel class from `ui/graph/render_panels/`
(`PseudocolorSettingsPanel`, `DotPlotSettingsPanel`,
`HistogramSettingsPanel`, `ContourSettingsPanel`) — the dialog itself is
purely a coordinator; all validation/preset logic lives in the panels. On
`accept`, settings are pushed back through `RenderConfig` and applied via
the standard `redraw()` path described in §2 above (no bypass of the
compute/draw split).

---

## 7. See Also

- [`00_ARCHITECTURE_OVERVIEW.md`](00_ARCHITECTURE_OVERVIEW.md) — startup
  sequencing and the full rendering data-flow loop.
- [`08_DATA_FLOW_AND_SIGNAL_CONNECTIONS.md`](08_DATA_FLOW_AND_SIGNAL_CONNECTIONS.md) —
  how the widgets described here are wired to `CentralEventBus` and to each
  other via `MainPanelController.wire()`.
- [`03_TESTING_AND_QA.md`](03_TESTING_AND_QA.md) — UI test patterns
  (not re-verified in this rewrite pass).
