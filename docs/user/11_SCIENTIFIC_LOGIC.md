# Scientific Logic & Algorithms

This document delineates the biological, physical, and mathematical principles underlying the data pipeline of the Karcytics Flow Cytometry Module.

---

## 1. Algorithmic Overview: The System Pipeline

Flow cytometry represents a highly complex physical process converted into a massive digital dataset. The pipeline is conceptually organized as follows:

1. **Cellular Interrogation**: Biological cells traverse a laser interrogation point.
2. **Fluorophore Excitation**: Conjugated fluorophores absorb and re-emit photons at specific wavelengths.
3. **Signal Transduction**: Photomultiplier Tubes (PMTs) or Avalanche Photodiodes (APDs) convert photon impacts into analog voltage pulses.
4. **Digital Conversion**: Analog-to-Digital Converters (ADCs) integrate the voltage pulse area, storing it as an arbitrary digital value (the raw FCS data).

---

## 2. Physical Optics: Scatter Parameters

As a cell traverses the coherent light source, elastic scattering occurs. We measure two primary non-fluorescent physical parameters:

| Parameter | Measurement Basis | Biological Relevance |
| :--- | :--- | :--- |
| **Forward Scatter (FSC)** | Small-angle scattered light. | Proportional to cellular **Volume** or **Size**. |
| **Side Scatter (SSC)** | Orthogonally ($90^\circ$) scattered light. | Proportional to cellular **Granularity** or **Internal Complexity**. |

---

## 3. Spectral Overlap and Compensation Mathematics

The most critical algorithmic correction applied to raw data is **Compensation**.

Fluorophore emission spectra are broad curves, not discrete lines. Consequently, the emission of a "Green" fluorophore (e.g., FITC) will inevitably register in the "Orange" detector (e.g., PE). This phenomenon is termed **Spectral Overlap**.

### Linear Algebra Implementation
To resolve true biological fluorescence, the module computes a spillover matrix $S$ where each element $S_{i,j}$ represents the proportional signal bleed from fluorophore $j$ into detector $i$.

The true, compensated signal vector $C$ for a given event is calculated by multiplying the raw signal vector $R$ by the inverse of the spillover matrix:

$$ C = S^{-1} \cdot R $$

!!! important
    Karcytics computes $S^{-1}$ using `numpy`'s standard matrix inversion routines.

---

## 4. Coordinate Transformation: The Logicle Scale

Standard logarithmic scales are mathematically undefined at zero and cannot display negative values. However, **Compensation** and **Background Subtraction** frequently result in mathematically valid zero or negative event values due to photon counting statistics and baseline subtraction.

### The Parks 2006 Logicle Transform
Karcytics incorporates the **Logicle (BiExponential)** transform to seamlessly handle sub-zero events. It integrates:

1. **Linear Scaling** adjacent to zero, permitting the accurate display of negative values and statistical spread.
2. **Logarithmic Scaling** at high magnitudes, compressing high-intensity positive values.

This biexponential behavior ensures that the "full statistical spread" of a negative population is correctly visualized alongside multi-decade positive populations within a continuous coordinate space.

---

## 5. Density Rendering: Rank-Percentile Normalization

When visualizing high-throughput experiments exceeding 1,000,000 events, canonical scatter plots degrade into indistinguishable clusters. Karcytics utilizes **Pseudocolor Rendering** to project overlapping matrices into interpretable heatmaps.

### The Rank-Percentile Algorithm
Standard log-scaled density mapping frequently produces artefactual visual "spikes" and amplifies background noise. Karcytics resolves this via **Rank Percentile Normalization**:

1. **Matrix Binning**: The two-dimensional coordinate space is divided into a high-resolution hexbin grid.
2. **Gaussian Smoothing**: A computational kernel "blurs" the discrete event counts, converting discontinuous matrices into continuous density functions.
3. **Percentile Ranking**: Rather than mapping absolute event counts to a color scale, each spatial coordinate is assigned its **percentile rank**.
    - The bottom 5th percentile is algorithmically suppressed to the background baseline (noise reduction).
    - The top 1st percentile is mapped to the maximum thermal color value (core identification).
4. **Range Stretching**: The color interpolation is non-linearly stretched to visually emphasize core populations while maintaining continuous, scientifically accurate background gradients.

This normalization guarantees that visual distributions remain scientifically representative regardless of varying event counts between samples.

---

## Technical Guides
- **[Getting Started Guide](./01_GETTING_STARTED.md)**
- **[Workspace](./02_WORKSPACE.md)**
