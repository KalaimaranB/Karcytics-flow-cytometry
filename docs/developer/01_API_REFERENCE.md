# API Reference

This is a bookmarkable reference to the plugin's public API surface: the gate classes, the gating DAG model, `GateCoordinator`'s facade methods, and the key service method signatures a developer will actually call. It is generated from the source under `src/karcytics_plugins/flow_cytometry/`, not from prose recollection — every signature below was read from the current tree.

For *how* gate evaluation and compensation actually work internally, see [05_GATING_AND_COMPENSATION_DEEP_DIVE.md](05_GATING_AND_COMPENSATION_DEEP_DIVE.md). For how the services below are constructed and wired together, see [04_SERVICES_AND_DEPENDENCY_INJECTION.md](04_SERVICES_AND_DEPENDENCY_INJECTION.md).

!!! note "Module map"
    Gate classes live in `analysis/gating/`. The DAG evaluator lives in `analysis/compute/dag_evaluator.py`. Compensation lives in `analysis/compensation.py` — **not** under `compute/` or `gating/`, despite being closely related to both.

---

## 1. Gate classes (`analysis/gating/`)

Every gate type subclasses the abstract `Gate` base (`analysis/gating/base.py`). All bounds/vertices/centers are stored in **raw (untransformed) data space**; `contains()` projects both the stored geometry and the incoming events into **display space** (via `apply_transform`) before testing, so a gate always tracks correctly under axis-scale changes.

### `Gate` (abstract base) — `gating/base.py`

```python
class Gate(ABC):
    def __init__(
        self,
        x_param: str,
        y_param: str | None = None,
        *,
        adaptive: bool = False,
        gate_id: str | None = None,
    ) -> None: ...
```

| Member | Signature | Notes |
|---|---|---|
| `gate_id` | `str` | UUID4 by default; stable identity used for serialization, `find_nodes_by_gate`, and cross-node sharing (quadrant sub-gates, split populations). |
| `x_param`, `y_param` | `str`, `str \| None` | Channel names. `y_param=None` marks a 1-D gate. |
| `adaptive` | `bool` | Opt-in flag; see `adapt()`. |
| `contains(events: pd.DataFrame) -> np.ndarray` | abstract | Boolean mask, shape `(n_events,)`. Subclasses implement the geometry test. |
| `apply(events) -> pd.DataFrame` | concrete | `events.loc[self.contains(events)].copy()`. |
| `adapt(events) -> None` | concrete no-op | Only fires when `self.adaptive`; base implementation just logs — no subclass currently overrides it with real repositioning logic. |
| `copy() -> Gate` | abstract | Deep copy with the **same** `gate_id` (used for cloning across samples where identity should be preserved, e.g. `GatingService._clone_dag`, which forces a new id itself). |
| `to_dict() / from_dict(data)` | concrete / classmethod | Base handles `type`, `gate_id`, `x_param`, `y_param`, `adaptive`; subclasses extend both. |
| `create_nodes(parent_node, name=None) -> list[GateNode]` | concrete, overridable | Default: creates **one** `GateNode` child. `QuadrantGate` overrides this to create **four**. |

### `RectangleGate` — `gating/rectangle.py`

2-D rectangular (or effectively 1-D range, if `y_param=None`) gate defined by raw-space min/max bounds.

```python
RectangleGate(
    x_param: str,
    y_param: str | None = None,
    *,
    x_min: float = -np.inf,
    x_max: float = np.inf,
    y_min: float = -np.inf,
    y_max: float = np.inf,
    adaptive: bool = False,
    gate_id: str | None = None,
    x_scale: AxisScale | None = None,
    y_scale: AxisScale | None = None,
)
```

`contains()`: projects `x`/`y` raw values and the raw bounds through `apply_transform(..., x_type, **x_kwargs)` (biexponential params pulled from `x_scale`/`y_scale` when applicable), then tests `x_min_disp <= x_disp <= x_max_disp` (and the same for `y` if `y_param` is set).

### `PolygonGate` — `gating/polygon.py`

```python
PolygonGate(
    x_param: str,
    y_param: str,
    vertices: list[tuple[float, float]],
    x_scale: AxisScale | None = None,
    y_scale: AxisScale | None = None,
    name: str = "Polygon Gate",
    adaptive: bool = False,
    gate_id: str | None = None,
    **_kwargs,
)
```

`contains()` projects vertices and events into display space, then uses `matplotlib.path.Path(vertices).contains_points(...)` — a standard even-odd point-in-polygon test, not a hand-rolled winding-number algorithm.

!!! note
    `PolygonGate` carries its own `name` attribute (used as a fallback display label) in addition to the `GateNode.name` that actually drives the UI — the two are set independently.

### `EllipseGate` — `gating/ellipse.py`

```python
EllipseGate(
    x_param: str,
    y_param: str,
    *,
    center: tuple[float, float] = (0.0, 0.0),
    width: float = 1.0,
    height: float = 1.0,
    angle: float = 0.0,          # degrees, counter-clockwise
    adaptive: bool = False,
    gate_id: str | None = None,
    x_scale=None,
    y_scale=None,
)
```

`contains()`: projects center and events to display space, translates to the center, rotates by `-angle` (i.e. rotates the *point*, not the ellipse, into the ellipse's own frame), then tests the standard ellipse inequality `(x_rot/width_disp)^2 + (y_rot/height_disp)^2 <= 1`.

!!! warning "`width`/`height` are semi-axes here, not full axis lengths"
    Unlike some other flow tools, this implementation treats `width`/`height` as already the axis half-lengths used directly in the ellipse equation (`x_rot/width`, not `x_rot/(width/2)`). Confirm against `contains()` before assuming a convention — do not guess based on other codebases.

### `RangeGate` — `gating/range.py`

1-D range gate (used for histogram gating). `y_param` is always `None`.

```python
RangeGate(
    x_param: str,
    *,
    low: float = -np.inf,
    high: float = np.inf,
    adaptive: bool = False,
    gate_id: str | None = None,
    x_scale=None,
)
```

### `QuadrantGate` / `QuadrantSubGate` — `gating/quadrant.py`

```python
QuadrantGate(
    x_param: str,
    y_param: str,
    *,
    x_mid: float = 0.0,
    y_mid: float = 0.0,
    adaptive: bool = False,
    gate_id: str | None = None,
    x_scale: AxisScale | None = None,
    y_scale: AxisScale | None = None,
)
```

`QuadrantGate.contains()` always returns all-`True` — the parent gate itself holds no population. The actual per-quadrant test is `get_quadrant(events, quadrant: str) -> np.ndarray`, where `quadrant` is one of `"Q1"`/`"Q2"`/`"Q3"`/`"Q4"` (matched case-insensitively on the first word):

| Quadrant | Region (display space) |
|---|---|
| `Q1` | upper-left: `x < x_mid, y >= y_mid` |
| `Q2` | upper-right: `x >= x_mid, y >= y_mid` |
| `Q3` | lower-left: `x < x_mid, y < y_mid` |
| `Q4` | lower-right: `x >= x_mid, y < y_mid` |

`create_nodes(parent_node, _name=None)` **overrides** the base and creates **four** `GateNode`s (one per quadrant), each wrapping a `QuadrantSubGate(self, q_name)`. This is the one gate type where `GateCoordinator.add_gate` / `GateMutationService.add_gate` returns/publishes multiple node ids in one call (see `GateEventPublisher.publish_gates_created`).

`QuadrantSubGate(parent: QuadrantGate, quadrant: str, gate_id=None)` — `contains()` delegates to `parent.get_quadrant(events, quadrant)`. Its `gate_id` defaults to `f"{parent.gate_id}_{quadrant}"`. `GateModifier.modify_gate` special-cases this: mutating a `QuadrantSubGate`'s geometry (`x_mid`/`y_mid`) actually redirects the mutation onto `gate.parent`, so editing any one quadrant's crosshair moves all four.

### `SubsetGate` — `gating/subset.py`

Explicit index-based population, used for populations that cannot be described by 2-D geometry (e.g. UMAP cluster exports).

```python
SubsetGate(indices: list[int], gate_id: str | None = None)
```

`contains(events)` returns `events.index.isin(self.indices)` — membership is by **DataFrame index label**, not positional row number. `x_param` is hardcoded to `"Subset"` and `y_param=None` (dummy values; this gate type has no axis geometry).

### Gate reconstruction — `gating/gate_factory.py`

```python
def gate_from_dict(data: dict) -> Gate
```

Looks up `data["type"]` in a fixed registry (`RectangleGate`, `PolygonGate`, `EllipseGate`, `QuadrantGate`, `QuadrantSubGate`, `RangeGate`, `SubsetGate`) and dispatches to that class's `from_dict()`. Raises `ValueError` for an unknown `type`.

---

## 2. `GateNode` — `gating/gate_node.py`

The hierarchical/DAG node that wraps a `Gate` and carries population identity, statistics, and tree structure. `@dataclass`, not built via a constructor with validation — fields are set directly.

```python
@dataclass
class GateNode:
    node_id: str = <uuid4>
    name: str = "All Events"
    negated: bool = False
    gate: Gate | None = None
    children: list[GateNode] = []
    parents: list[GateNode] = []          # repr=False
    logic_operator: str = "AND"           # "AND" | "OR" | "NOT"
    statistics: dict = {}
    creation_view: dict = {}
    is_umap_parent: bool = False
    is_logic_node: bool = False
```

| Property/Method | Signature | Behavior |
|---|---|---|
| `is_root` | `bool` (property) | `True` only for the sentinel "All Events" root: `gate is None and not parents and not is_logic_node`. |
| `is_incomplete` | `bool` (property) | `True` for a logic node without enough **non-root** parents wired in yet — `< 1` real parent for `NOT`, `< LOGIC_GATE_MIN_PARENTS` (2) otherwise. Always `False` for non-logic nodes. |
| `add_child(gate, name=None)` | `-> GateNode` | Creates+attaches a single-parent child. |
| `remove_child(node_id)` | `-> bool` | Removes by id from `self.children` only (does not touch `parents` on the removed node). |
| `find_node_by_id(node_id)` | `-> GateNode \| None` | Recursive DFS from this node down. |
| `find_nodes_by_gate(gate_id)` | `-> list[GateNode]` | All nodes (recursively) whose `.gate.gate_id == gate_id` — e.g. all 4 quadrant sub-nodes share one parent `QuadrantGate.gate_id`-derived family. |
| `apply_hierarchy(events)` | `-> pd.DataFrame` | Applies the full AND/OR/NOT + gate chain from this node up to root, returns the filtered events (see `_get_mask`, which is the single-node equivalent of `DagEvaluator.evaluate` — used for one-off queries rather than full-tree stats). |
| `adapt_all(events)` | `-> None` | Recursively calls `gate.adapt()` on every adaptive gate in the subtree, feeding each gate the already-filtered parent events. |
| `to_dict()` / `from_dict(data)` | | Serializes/deserializes the **entire reachable DAG** as a flat `{"type": "dag", "nodes": [...]}` list (not a nested tree) — required because logic nodes can have multiple parents. `from_dict` requires the `"nodes"` key; anything else raises `ValueError("Invalid serialized DAG format")`. |

---

## 3. DAG evaluation — `analysis/compute/dag_evaluator.py`

```python
class DagEvaluator:
    @staticmethod
    def evaluate(root: GateNode, events: pd.DataFrame) -> dict[str, NodeStatistics]
```

Evaluates the **entire** gate DAG in one topological pass (Kahn's algorithm over in-degree = parent count) and returns a `node_id -> NodeStatistics` map. `NodeStatistics` is a `TypedDict`: `{"count": int, "pct_parent": float, "pct_total": float}` (percentages rounded to 2 dp). As a side effect it also writes `node.statistics` on every visited node. See [05_GATING_AND_COMPENSATION_DEEP_DIVE.md](05_GATING_AND_COMPENSATION_DEEP_DIVE.md) for the full mask-combination algorithm.

---

## 4. Compensation — `analysis/compensation.py`

### `CompensationMatrix` (dataclass)

```python
@dataclass
class CompensationMatrix:
    matrix: np.ndarray  # N×N, rows=detector, cols=fluorophore
    channel_names: list[str] = []
    source: str = "computed"  # "computed" | "imported" | "cytometer"

    @property
    def inverse(self) -> np.ndarray: ...  # np.linalg.inv(self.matrix)
    @property
    def n_channels(self) -> int: ...
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> CompensationMatrix: ...
```

### Module functions

| Function | Signature | Purpose |
|---|---|---|
| `calculate_spillover_matrix` | `(single_stains: list[FCSData], unstained: FCSData \| None = None, fluorescence_channels: list[str] \| None = None) -> CompensationMatrix` | Computes a spillover matrix from single-stain controls (median-ratio algorithm). Requires ≥ `MIN_SINGLE_STAINS` (2) samples or raises `ValueError`. |
| `extract_spill_from_fcs` | `(data: FCSData) -> CompensationMatrix \| None` | Parses `$SPILL`/`$SPILLOVER` (or lowercase/no-`$` variants) out of `FCSData.metadata`. Returns `None` if absent or malformed. `source="cytometer"`. |
| `import_matrix_from_csv` | `(path: Path) -> CompensationMatrix` | Reads a CSV/TSV; raises `ValueError` if non-square. `source="imported"`. |
| `export_matrix_to_csv` | `(comp: CompensationMatrix, path: Path) -> None` | Writes matrix with channel names as both row/column labels. |
| `apply_compensation` | `(data: FCSData, comp: CompensationMatrix \| None) -> pd.DataFrame` | Returns compensated events (`raw_events` preferred over `events` as the source). `comp=None` returns the data unchanged. Only channels present in **both** `comp.channel_names` and `data`'s columns are compensated; the submatrix for those channels is inverted directly (not sliced from the full inverse — see the deep-dive doc for why that distinction matters). |

`FCSData` (from `analysis/fcs_io.py`) is the input type throughout: a dataclass with `file_path: Path`, `channels: list[str]`, `markers: list[str]`, `events: pd.DataFrame | None`, `raw_events: pd.DataFrame | None`, `metadata: dict[str, str]`, `is_compensated: bool`.

Called from `main_panel.py._on_samples_loaded`: if `state.data.compensation is None`, the panel auto-calls `extract_spill_from_fcs` on newly loaded samples and adopts the first embedded matrix it finds.

---

## 5. `GateCoordinator` — `analysis/gate_coordinator.py`

The facade every UI surface (ribbons, canvas, hierarchy tree) calls into for gating operations. Constructed once by `ServiceFactory.build_all()` and exposed on `main_panel.py` as both `self._gate_coordinator` and `self._gate_controller` (same object — `main_panel.py` line 156: `self._gate_controller = self._gate_coordinator`).

```python
class GateCoordinator:
    def __init__(
        self,
        state: FlowState,
        axis_manager: AxisManager,
        population_service: PopulationService,
        task_scheduler: Any | None = None,
    ): ...
```

Internally owns a `GatePropagator` (`self._propagator`, exposed via the `propagator` property) and a `GateSelectionService` (`self._selection_service`), and constructs one `GateMutationService` that most facade methods delegate straight to.

| Method | Signature | Delegates to |
|---|---|---|
| `add_gate` | `(gate: Gate, sample_id: str, name: str \| None = None, parent_node_id: str \| None = None) -> str \| None` | `GateMutationService.add_gate` — returns the **first** created node's id (quadrant gates create 4; only the first id is returned by the facade). |
| `remove_population` | `(sample_id: str, node_id: str) -> bool` | `GateMutationService.remove_population` |
| `select_gate` | `(sample_id: str, node_id: str \| None) -> None` | `GateSelectionService.select_gate` |
| `add_logic_node` | `(sample_id: str, operator: str, name: str \| None = None) -> str \| None` | `GateMutationService.add_logic_node` — creates an AND/OR/NOT node with **no parents wired**; user must wire it via `add_connection`. |
| `add_connection` | `(sample_id: str, source_node_id: str, target_node_id: str) -> bool` | `GateMutationService.add_connection` — rejects cycles and wiring into root. |
| `remove_connection` | `(sample_id: str, source_node_id: str, target_node_id: str) -> bool` | `GateMutationService.remove_connection` |
| `rename_population` | `(sample_id: str, node_id: str, new_name: str) -> bool` | `GateMutationService.rename_population` — does **not** trigger propagation or stats recompute (pure label change). |
| `modify_gate` | `(gate_id: str, sample_id: str, **kwargs) -> bool` | `GateMutationService.modify_gate` → `GateModifier.modify_gate` (validated). |
| `split_population` | `(sample_id: str, node_id: str) -> str \| None` | `GateMutationService.split_population` → `PopulationSplitter` |
| `copy_gates_to_group` | `(source_sample_id: str) -> int` | `GateMutationService.copy_gates_to_group` → `GatingService.copy_gates_to_group`; returns count of samples updated. |
| `get_gates_for_display` | `(sample_id: str, parent_node_id: str \| None = None) -> tuple[list[Gate], list[GateNode]]` | `GateMutationService.get_gates_for_display` |
| `recompute_all_stats` | `(sample_id: str, sync: bool = False) -> None` | Runs `StatisticsAnalysis` — synchronously if `sync=True` or `self.sync_stats` is truthy, otherwise submitted via `StatsService.recompute_all_stats` on the background `TaskScheduler`, with `self._on_stats_finished` as the completion callback (publishes `GATE_STATS_UPDATED` per node then `ALL_STATS_UPDATED`). |
| `set_propagation_enabled` | `(enabled: bool) -> None` | Sets `self._propagation_enabled` (defaults `True` via `getattr`). |
| `request_propagation` | `(gate_id: str, source_sample_id: str) -> None` | No-ops if propagation is disabled; otherwise forwards to `self._propagator.request_propagation`. |
| `propagate_to_all_groups` | `(sample_id: str, node_id: str) -> None` | Forwards to `self._propagator.request_cross_group_propagation` — bypasses the active group filter. |
| `cleanup` | `() -> None` | Cancels the propagator's pending debounce timer. |

!!! note "Method-name mismatch to watch for"
    `GateCoordinator.propagate_to_all_groups(sample_id, node_id)` calls `self._propagator.request_cross_group_propagation(node_id, sample_id)` — the **argument order is swapped** between the two method signatures (`node_id` becomes the propagator's `gate_id` positional argument). This is intentional per the propagator's signature (`request_cross_group_propagation(self, gate_id, source_sample_id)`) but easy to get backwards when calling either method directly.

This class matches the `IGateCoordinator` `Protocol` defined in `analysis/protocols.py` method-for-method (`add_gate`, `remove_population`, `add_logic_node`, `add_connection`, `remove_connection`, `rename_population`, `modify_gate`, `split_population`, `copy_gates_to_group`, `get_gates_for_display`, `recompute_all_stats`, `set_propagation_enabled`) — UI code should type-hint against the protocol where practical.

---

## 6. Key service signatures

Full responsibility/dependency descriptions are in [04_SERVICES_AND_DEPENDENCY_INJECTION.md](04_SERVICES_AND_DEPENDENCY_INJECTION.md); this section is the quick call-signature lookup.

### `PopulationService` — `analysis/population_service.py`

```python
class PopulationService:
    def __init__(self, state: FlowState): ...
    def get_sample(self, sample_id: str) -> Sample | None
    def get_root_node(self, sample_id: str) -> GateNode | None
    def find_node(self, sample_id: str, node_id: str) -> GateNode | None
    def find_nodes_by_gate(self, sample_id: str, gate_id: str) -> list[GateNode]
    def get_gated_events(self, sample_id: str, node_id: str | None = None) -> pd.DataFrame | None
    def add_population(self, sample_id: str, gate: Gate, parent_id: str | None = None, name: str | None = None) -> GateNode | list[GateNode] | None
    def remove_population(self, sample_id: str, node_id: str) -> bool
```

### `AxisManager` — `analysis/axis_manager.py`

```python
class AxisManager:
    def __init__(self, state: FlowState, inference_strategy: ChannelInferenceStrategy | None = None): ...
    def get_scale(self, channel: str | None, sample_id: str | None = None, default_transform: TransformType | None = None) -> AxisScale
    def set_scale(self, channel: str, scale: AxisScale, notify: bool = True, sample_id: str | None = None) -> None
    def calculate_range(self, data: pd.Series, channel: str, sample_id: str | None = None) -> tuple[float, float]
    def update_auto_range(self, sample_id: str, channel: str, _axis_id: str = "x") -> tuple[float, float] | None
```

Scales are stored per-**group** (`Group.channel_scales`), keyed off the sample's first `group_ids` entry — not per-sample. If a sample has no group, scales fall back to `state.view.fallback_scales`, keyed by channel only. `set_scale` publishes `events.AXIS_UPDATED` unless `notify=False`.

### `GateModifier` — `analysis/services/modifier.py`

```python
class GateModifier:
    @staticmethod
    def modify_gate(experiment: Experiment, gate_id: str, sample_id: str, **kwargs) -> bool
```

Validates the merged (current + candidate) attribute state before mutating anything — a rejected edit never partially applies. Per-type invariants: `RectangleGate` requires `x_min < x_max` and `y_min < y_max`; `RangeGate` requires `low < high`; `EllipseGate` requires `width > 0` and `height > 0`; `PolygonGate` requires `len(vertices) >= POLYGON_MIN_VERTICES` (3). `QuadrantGate` has no geometric invariant on `x_mid`/`y_mid`. `QuadrantSubGate` targets are redirected to `gate.parent` before validation/mutation.

### `NamingService` — `analysis/services/naming.py`

```python
class NamingService:
    @staticmethod
    def generate_unique_name(experiment: Experiment, sample_id: str, prefix: str = "Gate") -> str
```

Collects every non-root node name in the sample's tree, then returns the first `f"{prefix} {n}"` (n starting at 1) not already used.

### `PopulationSplitter` — `analysis/services/splitter.py`

```python
class PopulationSplitter:
    @staticmethod
    def split_population(experiment: Experiment, sample_id: str, node_id: str) -> tuple[str, str, str] | None
```

Returns `(new_node_id, new_name, gate_id)`. Creates an inverse sibling (`negated = not node.negated`) sharing the **same** `Gate` instance and wired to all of the original node's parents, named `f"{node.name} (Outside)"` (or `(Inside)` if the source was already negated).

### `GatingService` — `analysis/services/gating_service.py`

```python
class GatingService:
    @staticmethod
    def get_gates_for_display(sample: Sample, parent_node_id: str | None = None) -> tuple[list[Gate], list[GateNode]]
    @staticmethod
    def clone_gate_tree(source_root: GateNode, target: Sample) -> None
    @staticmethod
    def copy_gates_to_group(experiment: Experiment, source_sample_id: str) -> int
```

`clone_gate_tree` deep-clones **every** reachable node (including multi-parent logic nodes) and gives each cloned physical gate a fresh `gate_id`. `copy_gates_to_group` copies to all samples sharing a group with the source (or to every other sample if the source is ungrouped), returns the count copied to.

### `DataLoaderService` — `analysis/services/data_loader_service.py`

```python
class DataLoaderService:
    def __init__(self, scheduler: object | None = None, plugin_id: str = "flow_cytometry"): ...
    def reload_sample(self, sample: Sample, path: Path, compensation_matrix: CompensationMatrix | None = None) -> bool
    def reload_samples_batch(self, samples_with_paths: list[tuple[Sample, Path]], compensation_matrix: CompensationMatrix | None = None) -> dict[str, list[str]]
    def load_samples_async(self, paths, state, on_done, on_error_cb, on_progress=None, project_manager=None, copy_all=False) -> None
```

`reload_samples_batch` is preferred over N `reload_sample()` calls: `load_fcs()` serializes through a single process-wide daemon IPC lock, so per-sample reloads from a thread pool collapse into sequential loads anyway; batching sends one request to the daemon and lets it parse concurrently.

### `UmapService` / `UmapParams` — `analysis/services/umap_service.py`

```python
@dataclass
class UmapParams:
    target_sample_id: str
    target_node_id: str | None = None
    name: str = ""
    percentage: float = 10.0
    n_neighbors: int = 15
    min_dist: float = 0.1
    n_events: int = 10000
    metric: str = "euclidean"
    random_seed: int = 42
    run_hdbscan: bool = False
    hdbscan_space: str = "high_dim"
    min_cluster_size: int = 100
    channels: list[str] | None = None

class UmapService:
    def __init__(self, state: FlowState, scheduler: Any): ...
    def run_analysis(self, params: UmapParams, on_done, on_error_cb, on_progress=None) -> None
    def cancel(self) -> None
```

`run_analysis` always calls `self.cancel()` first — only one UMAP task can be in flight per `UmapService` instance.

### `WorkflowService` — `ui/services/workflow_service.py`

```python
class WorkflowService(QObject):
    def __init__(self, state: FlowState, data_loader_service, attachment_manager, parent=None): ...
    def export_workflow(self, context=None, project_dir: Path | None = None) -> dict
    def load_workflow(self, payload: dict, context=None, on_complete=None, project_dir: Path | None = None, **kwargs) -> bool
    def reload_fcs_data(self, sample_paths: dict[str, str], project_dir: Path | None = None, on_complete=None) -> None
```

`export_workflow` stores each sample's FCS path **relative to `project_dir`** (POSIX style) when it lives inside the project, else as an absolute path — so a project directory copied to another machine/OS still resolves its data.

---

## 7. Event topics — `analysis/events.py`

All cross-component notification goes through the Karcytics SDK's `CentralEventBus.publish(topic, payload_dict)`. Full topic list:

| Category | Constant | Topic string |
|---|---|---|
| Gate | `GATE_CREATED` | `flow.gate.created` |
| Gate | `LOGIC_NODE_CREATED` | `flow.gate.logic_node_created` |
| Gate | `GATES_CREATED` | `flow.gate.batch_created` |
| Gate | `GATE_RENAMED` | `flow.gate.renamed` |
| Gate | `GATE_DELETED` | `flow.gate.deleted` |
| Gate | `GATE_MODIFIED` | `flow.gate.modified` |
| Gate | `GATE_PROPAGATED` | `flow.gate.propagated` |
| Gate | `GATE_SELECTED` | `flow.gate.selected` |
| Gate | `GATE_PREVIEW` | `flow.gate.preview` |
| Sample | `SAMPLE_SELECTED` / `SAMPLE_DESELECTED` / `SAMPLE_LOADED` | `flow.sample.*` |
| Canvas | `RENDER_MODE_CHANGED`, `RENDER_CONFIG_CHANGED`, `AXIS_PARAMS_CHANGED`, `AXIS_RANGE_CHANGED`, `AXIS_RANGE_AUTO_UPDATED`, `TRANSFORM_CHANGED`, `DISPLAY_MODE_CHANGED`, `FMO_CHANGED` | `flow.render.*` / `flow.axis.*` / `flow.transform.changed` / `flow.display.mode_changed` / `flow.fmo.changed` |
| Statistics | `STATS_COMPUTED`, `STATS_INVALIDATED` | `flow.stats.*` |
| Compensation | `COMPENSATION_APPLIED` | `flow.compensation.applied` |
| UMAP | `UMAP_COMPLETED` | `flow.umap.completed` |
| Internal | `AXIS_UPDATED`, `GATE_STATS_UPDATED`, `ALL_STATS_UPDATED`, `PROPAGATION_REQUESTED`, `PROPAGATION_COMPLETE`, `SAMPLE_UPDATED` | `flow.axis.updated`, `flow.gate.stats_updated`, `flow.gate.all_stats_updated`, `flow.gate.propagation_requested`, `flow.gate.propagation_complete`, `flow.gate.sample_updated` |
| Experiment | `EXPERIMENT_DATA_CHANGED` | `flow.experiment.data_changed` |

Two topic strings are published as raw literals rather than named constants: `"flow.pipeline.connection_added"` and `"flow.pipeline.connection_removed"`, emitted by `GateMutationService.add_connection`/`remove_connection` when a logic node is still `is_incomplete` (under-wired) — a cheap "draw the wire" signal that intentionally skips the full stats-recompute + `GATE_STATS_UPDATED` path those methods otherwise take.
