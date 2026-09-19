# Flow Cytometry Knowledge Hub

Welcome to the centralized documentation for the Karcytics Flow Cytometry module. This hub is designed to support both researchers conducting data analysis and engineers extending the software capabilities.

!!! tip "New to the app?"
    The fastest way to learn the workspace is the in-app **Academy** — open it from the tab bar for three guided, hands-on courses that walk you through loading data, gating, and analysis with live validation as you go. See [Academy & Guided Tutorials](./user/10_ACADEMY_TUTORIALS.md) for details.

---

--8<-- "internal/06_Installation.md"

---

## For Scientists & Researchers
Comprehensive guides for data analysis workflows, visual refinement, and publication preparation, organized in the same order as the tabs across the top of the app.

- **[Capabilities Overview](./user/00_OVERVIEW.md)**: Feature summary, tri-pane layout, and the 8 workspace tabs at a glance.
- **[Getting Started Guide](./user/01_GETTING_STARTED.md)**: Tutorial for loading FCS data, configuring the workspace, and creating initial gates.
- **[Workspace](./user/02_WORKSPACE.md)**: Importing FCS files, sample metadata, and everything that comes up once you open a sample — axis controls, plot type, transforms, per-plot settings, the Gating Hierarchy, and Group Preview.
- **[Compensation](./user/03_COMPENSATION.md)**: Spillover matrix generation and the compensation editor.
- **[Gating](./user/04_GATING.md)**: Rectangle, polygon, ellipse, quadrant, and range gates.
- **[Pipeline](./user/05_PIPELINE.md)**: The node-graph view of a sample's gating pipeline.
- **[Statistics](./user/06_STATISTICS.md)**: Analyzing event counts, percentages, and custom population metrics.
- **[Spectral](./user/07_SPECTRAL.md)**: Spectral overlap visualization and the educational compensation wizard.
- **[Population Analysis](./user/08_POPULATION_ANALYSIS.md)**: UMAP dimensionality reduction, clustering, and history.
- **[Comparisons](./user/09_COMPARISONS.md)**: Cross-sample comparison plots.
- **[Academy & Guided Tutorials](./user/10_ACADEMY_TUTORIALS.md)**: The in-app guided courses and what each one teaches.
- **[Scientific Logic & Algorithms](./user/11_SCIENTIFIC_LOGIC.md)**: Mathematical principles behind Logicle transforms, rank-percentile density calculation, and smoothing kernels.
- **[Keyboard Shortcuts & Quick Reference](./user/12_KEYBOARD_SHORTCUTS.md)**: The real, current set of key bindings — this app is mostly mouse-driven.
- **[Troubleshooting Guide](./user/13_TROUBLESHOOTING.md)**: Common issues, error messages, and solutions.

---

## For Developers & Maintainers
Architectural specifications, API references, and contribution guidelines for the module.

- **[Architecture & Design Principles](./developer/00_ARCHITECTURE_OVERVIEW.md)**: Breakdown of the decoupled rendering layers and service-oriented backend structure.
- **[API Reference](./developer/01_API_REFERENCE.md)**: Technical documentation for Gating, Scaling, and Configuration models.
- **[UI Engine & Rendering](./developer/02_UI_ENGINE.md)**: Mechanics of the tab/ribbon/center-stack wiring and asynchronous panel construction.
- **[Testing & Quality Assurance](./developer/03_TESTING_AND_QA.md)**: Test suite architecture, statistical fixtures, and algorithmic verification checklists.
- **[Services & Dependency Injection](./developer/04_SERVICES_AND_DEPENDENCY_INJECTION.md)**: Core service layer architecture and pattern integration.
- **[Gating & Compensation Deep Dive](./developer/05_GATING_AND_COMPENSATION_DEEP_DIVE.md)**: Exhaustive technical details on the gate evaluation engine and spillover matrix compensation algorithm.
- **[Transforms & Scaling Deep Dive](./developer/06_TRANSFORMS_AND_SCALING.md)**: Mathematical details on axis transformations, auto-ranging algorithms, and coordinate mapping.
- **[Rendering & Visualization Architecture](./developer/07_RENDERING_AND_VISUALIZATION.md)**: The compute/draw render pipeline, layered canvas, and rasterization locking.
- **[Data Flow & Signal Connections](./developer/08_DATA_FLOW_AND_SIGNAL_CONNECTIONS.md)**: Complete documentation of data flow through the system, with workflow diagrams for major user operations and signal/event routing.

---

## External References
- **Parks, D.R., et al. (2006)**. A new "Logicle" display method. *Cytometry Part A*.
- **FlowKit Documentation**: [GitHub Repository](https://github.com/whitews/FlowKit)
- **Fast-Histogram**: [Optimized 2D binning implementation](https://github.com/astrofrog/fast-histogram)
