# Keyboard Shortcuts

Karcytics Flow Cytometry is built around mouse-and-canvas interaction — drawing gates, dragging nodes, checking boxes in a sidebar — rather than a large customized shortcut system. The list below is short on purpose: it covers only the key bindings that actually exist in the app today. If a shortcut you expect isn't listed here, it doesn't exist yet — use the corresponding button in the ribbon or panel instead.

## Plot & canvas

| Shortcut | Action | Where it works |
|---|---|---|
| **F** | Fit / auto-range the view to the current data | The plot canvas, the Pipeline node canvas, and the Gating Hierarchy tree view — press it with the mouse over whichever canvas you want to fit |
| **Ctrl** + mouse wheel | Zoom in/out | The Gating Hierarchy tree view (left sidebar) |
| **Esc** | Cancel an in-progress gate drawing | The plot canvas, while a Polygon/Rectangle/Ellipse/Quadrant/Range tool is active |
| **Esc** | Dismiss the group-samples popup | The "All Samples" group preview popup |

## Pipeline node canvas

| Shortcut | Action |
|---|---|
| **Delete** / **Backspace** | Delete the selected node or connection (edge) |

## Application-wide (provided by the Karcytics host, not the plugin)

These come from the main Karcytics application shell, so they behave the same way in every plugin, not just Flow Cytometry.

| Shortcut | Action |
|---|---|
| **Ctrl+Z** (**Cmd+Z** on macOS) | Undo |
| **Ctrl+Shift+Z** (**Cmd+Shift+Z** on macOS) | Redo |
| **Ctrl+,** (**Cmd+,** on macOS) | Open Preferences |
| **Ctrl+H** | Return to the Project hub view |
| **Ctrl+Q** | Quit Karcytics |

!!! note "No gate-drawing hotkeys yet"
    There's no chorded shortcut (like "press G then R") to switch between the Rectangle, Polygon, Ellipse, Quadrant, and Range gate tools, and no shortcuts for switching plot type, undoing a single gate edit, or exporting statistics/plots. All of those are click-driven — see the [Gating](./04_GATING.md) and [Workspace](./02_WORKSPACE.md) guides for where each control lives. If you rely on keyboard-driven workflows heavily, consider raising it as a feature request.

## Related Documentation

- **[Getting Started](./01_GETTING_STARTED.md)**: Basic workflow tutorial
- **[Troubleshooting](./13_TROUBLESHOOTING.md)**: Common issues and solutions
