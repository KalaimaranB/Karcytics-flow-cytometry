# Workspace

The **Workspace** ribbon is the foundational control center for your analytical session in Karcytics. It provides all the necessary tools to manage datasets, configure experimental metadata, and organize your analytical hierarchy before diving into computational tasks.

![alt text](../images/01_getting_started/workspace.png)

## 1. Importing Data

To begin an analysis session, you must load your raw event data:
1. Click **➕ Add Samples** in the Workspace ribbon.
2. Select one or more `.fcs` files from your filesystem.
3. If you select files located outside of your current Karcytics project's `assets` directory, Karcytics will automatically prompt you to copy them into the project workspace. 

!!! tip
    We strongly recommend copying files into the project workspace when prompted. This ensures your project remains portable and self-contained, preventing broken links if you move the project folder.

## 2. Experimental Metadata Management

Properly configuring your datasets is critical, as algorithmic workflows (like automated compensation and UMAP) rely heavily on accurate metadata.

### Assigning Sample Roles
By default, newly parsed datasets are assigned the generic role of `Other`. To enable algorithmic workflows, strict taxonomic roles must be assigned:

1. Select a sample node within the **Sample Tree** (left panel).
2. Within the **Properties Panel** (right), locate the **Role** dropdown and assign one of the following:
   - **Unstained Control**: Utilized for autofluorescence baseline calculation.
   - **Single Stain**: Utilized to compute the orthogonal spillover matrix during compensation.
   - **FMO Control**: Fluorescence Minus One; utilized for algorithmic boundary detection and objective gating.
   - **Full Panel / Test**: The primary biological experimental samples.

### Bulk Role Assignment
For large cohorts, manually assigning roles can be tedious. Use the **🏷️ Bulk Assign Roles** tool in the ribbon to open a dialog where you can assign roles to multiple samples simultaneously.

### Dataset Grouping
For longitudinal studies or multi-patient experimental cohorts, organize samples systematically:
1. Click **📁 Create Group** within the Workspace ribbon.
2. Drag and drop targeted samples from the Sample Tree into the newly instantiated group node.
3. Groups can be processed collectively in downstream analysis pipelines, and gates can be easily copied across all samples in a group.

## 3. Workflow Templates

If you routinely process similar panels, you can save your workspace configuration to drastically accelerate future analyses.

- **Save Template**: Exports the current workspace configuration—including defined groups, sample roles, and marker mappings—into a reusable `.json` file.
- **Load Template**: Applies a previously saved template to the current workspace, instantly recreating your group structures and metadata expectations.

## 4. Global Visualization Settings

The Workspace Ribbon provides global configurations to refine the visual aesthetics of the analytical coordinate space across all instantiated plots.

Access the settings menu to perform real-time parameter tuning:
- **Point Size & Opacity**: Modulate geometric marker size and alpha-transparency to emulate the high-density aesthetic characteristic of classical flow cytometry platforms.
- **Population Detail (Bins)**: Dictates the matrix resolution of the underlying hexbin grid. High detail is optimal for vector export; low detail accelerates real-time exploratory panning.
- **Smoothing (Sigma)**: Modulates the standard deviation of the Gaussian kernel applied to population densities, generating smoother, continuous distribution clouds.
- **Background Suppression**: A noise-floor threshold that maps low-density scatter to a pure baseline color, enhancing the signal-to-noise ratio at population boundaries.

!!! tip
    By default, mutating configurations within the dialog applies the new settings globally to **all instantiated plots**, ensuring visual conformity across the entire workspace.
