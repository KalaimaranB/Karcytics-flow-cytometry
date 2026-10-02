"""NodeTreeEngine — pure Python layout engine for Horizontal Flowcharts.

Calculates the x, y coordinates for a GateNode tree to be rendered
as a horizontal node-link diagram.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode

# Depth-level color palette indices
_DEPTH_COLORS = [
    0,  # depth 0 root  → purple
    1,  # depth 1       → teal
    2,  # depth 2       → blue
    3,  # depth 3       → orange
    4,  # depth 4       → pink
    5,  # depth 5+      → green
]


@dataclass
class TreeNodeRect:
    """Geometry and metadata for one node in the flowchart."""

    node_id: str
    name: str
    depth: int
    x: float  # center x pixel
    y: float  # center y pixel
    width: float  # node width in pixels
    height: float  # node height in pixels
    parent_ids: list[str] = field(default_factory=list)
    color_index: int = 0

    # Statistics for HoverCard
    count: int = 0
    pct_parent: float = 0.0
    pct_total: float = 0.0
    gate_type: str = ""
    x_param: str = ""
    y_param: str = ""


class NodeTreeEngine:
    """Computes a leaf-driven horizontal tree layout."""

    def __init__(self):
        self.node_width = 110
        self.node_height = 50
        self.horizontal_spacing = 10
        self.vertical_spacing = 60

    def compute(  # noqa: PLR0915
        self,
        root: GateNode,
        total_events: int = 0,
        param_labels: dict[str, str] | None = None,
    ) -> list[TreeNodeRect]:
        if not root:
            return []

        # ── Pass 1: BFS to compute max-depth for every reachable node ────────
        depth: dict[str, int] = {root.node_id: 0}
        all_nodes: dict[str, GateNode] = {}
        queue: deque = deque([root])
        visited: set = set()
        # Keep track of parent_ids for each node as we discover them
        parent_ids: dict[str, list[str]] = defaultdict(list)

        while queue:
            node = queue.popleft()
            if node.node_id in visited:
                continue
            visited.add(node.node_id)
            all_nodes[node.node_id] = node
            current_depth = depth[node.node_id]

            for child in node.children:
                # An unwired/under-wired logic node (AND/OR/NOT missing required
                # parents) has no valid population yet — keep it, and any subtree
                # hanging off it, out of the hierarchy view entirely.
                if getattr(child, "is_incomplete", False):
                    continue

                child_depth = current_depth + 1
                if child.node_id not in depth or child_depth > depth[child.node_id]:
                    depth[child.node_id] = child_depth
                # Only append parent if we actually came from this parent via children link
                # Note: node.children is reliable. node.parents can also be reliable.
                # To prevent duplicates if multiple edges exist (rare), use set or check
                if node.node_id not in parent_ids[child.node_id]:
                    parent_ids[child.node_id].append(node.node_id)
                queue.append(child)

        # ── Pass 2: Group nodes by depth ─────────────────────────────────────
        nodes_by_depth: dict[int, list[GateNode]] = defaultdict(list)
        for nid, node in all_nodes.items():
            nodes_by_depth[depth[nid]].append(node)

        # ── Pass 3: Assign X positions column-by-column ───────
        assigned_cross: dict[str, float] = {}

        for d in sorted(nodes_by_depth.keys()):
            nodes = nodes_by_depth[d]

            if d == 0:
                # Root column — single node, center at 0
                for node in nodes:
                    assigned_cross[node.node_id] = 0.0
            else:
                # Sort by mean parent cross-axis
                def parent_cross_key(n: GateNode) -> float:
                    real_parents = [p for p in n.parents if p.node_id in assigned_cross]
                    if not real_parents:
                        return 0.0
                    ys = [assigned_cross[p.node_id] for p in real_parents]
                    return sum(ys) / len(ys)

                nodes = sorted(nodes, key=parent_cross_key)

                # Center the column around the mean parent cross-axis
                all_parent_ys = [parent_cross_key(n) for n in nodes]
                col_center = sum(all_parent_ys) / len(all_parent_ys) if all_parent_ys else 0.0

                n_nodes = len(nodes)
                spacing = self.node_width + self.horizontal_spacing
                total_width = (n_nodes - 1) * spacing
                start_cross = col_center - total_width / 2.0

                for i, node in enumerate(nodes):
                    assigned_cross[node.node_id] = start_cross + i * spacing

        # Create TreeNodeRects
        rects: list[TreeNodeRect] = []
        for nid, node in all_nodes.items():
            d = depth[nid]
            x_center = assigned_cross[nid]
            y_center = d * (self.node_height + self.vertical_spacing) + (self.node_height / 2)

            gate = node.gate
            if gate:
                gate_type = type(gate).__name__.replace("Gate", "")
            elif not node.is_root:
                if getattr(node, "is_umap_parent", False):
                    gate_type = "UMAP Embedding"
                elif getattr(node, "logic_operator", None) is not None:
                    gate_type = f"Logic ({node.logic_operator})"
                else:
                    gate_type = "Cluster"
            else:
                gate_type = ""

            x_param = getattr(gate, "x_param", "") if gate else ""
            y_param = getattr(gate, "y_param", "") if gate else ""
            if param_labels:
                x_param = param_labels.get(x_param, x_param)
                y_param = param_labels.get(y_param, y_param) if y_param else y_param

            count = int(node.statistics.get("count", 0))
            pct_parent = node.statistics.get("pct_parent", 0.0)
            pct_total = node.statistics.get("pct_total", 0.0)

            if node.is_root and count == 0 and pct_total >= 0.0:
                count = total_events
                pct_parent = 100.0
                pct_total = 100.0

            rect = TreeNodeRect(
                node_id=nid,
                name=node.name,
                depth=d,
                x=x_center,
                y=y_center,
                width=self.node_width,
                height=self.node_height,
                parent_ids=parent_ids.get(nid, []),
                color_index=_DEPTH_COLORS[min(d, len(_DEPTH_COLORS) - 1)],
                count=count,
                pct_parent=pct_parent,
                pct_total=pct_total,
                gate_type=gate_type,
                x_param=x_param,
                y_param=y_param,
            )
            rects.append(rect)

        # Apply top padding and shift to make 0-based
        if rects:
            TOP_PADDING = 20
            all_x_left = [r.x - r.width / 2 for r in rects]
            x_min = min(all_x_left)
            x_offset = -x_min

            for r in rects:
                r.x += x_offset
                r.y += TOP_PADDING

        return rects
