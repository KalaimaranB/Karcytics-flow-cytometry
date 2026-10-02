# Transforms & Scaling Deep Dive

Mathematical details on axis transformations (Linear, Log, Biexponential), auto-ranging algorithms, and coordinate system mapping.

---

## 1. Transform Types & Mathematical Formulations

### LINEAR Transform

**Definition:** Identity transformation; no scaling applied.

$$y = x$$

**Use:** Scatter channels (FSC-A, SSC-A) where data is already on linear scale.

**Implementation:**
```python
def linear_transform(x: np.ndarray) -> np.ndarray:
    return x  # No-op
```

---

### LOG10 Transform

**Definition:** Base-10 logarithmic scaling.

$$y = \frac{\log_{10}(\max(x, \epsilon))}{\text{decades}}$$

where $\epsilon$ is a small floor value (default: 0.01) to prevent $\log(0)$ or $\log(\text{negative})$.

**Parameters:**
- `decades`: Number of orders of magnitude to display (typically 4). Display range: $[10^{-\epsilon}, 10^{\text{decades}}]$
- `min_value`: Floor below which data is clipped. Default: 0.01

**Use:** Channels with wide dynamic range (100s to millions), scattered marker expression.

**Example:**
```
Raw data:    1, 10, 100, 1000, 10000
decades=4    Log transform
min_value=0.01
         ↓
Display: 0.0, 1.0, 2.0, 3.0, 4.0  (log scale, 4 decades)
```

**Implementation:**
```python
def log_transform(data: np.ndarray, decades: float = 4.0, min_value: float = 0.01) -> np.ndarray:
    clipped = np.maximum(data, min_value)
    return np.log10(clipped) / decades
```

---

### BIEXPONENTIAL Transform (Parks 2006 Logicle)

**Motivation:** Modern flow cytometry needs simultaneous visualization of:
1. **Negative populations** (e.g., autofluorescence-subtracted data)
2. **Positive populations** (typical fluorescence, millions of intensity)
3. **Low positive** (transition zone near zero)

Log transform fails for negative values; linear fails for wide dynamic range.

**Mathematical Definition:**
The Logicle transform blends linear near zero with logarithmic for large values:

$$y = \begin{cases}
\frac{M + A}{w} x & \text{if } x \leq x_0 \\
\frac{M}{w} \left( \ln(x) - \ln(x_0) \right) + y_0 & \text{if } x > x_0
\end{cases}$$

where transition point $x_0$ and blending parameters are computed from:
- **T** (`logicle_t`): Top value; maximum data (e.g., 262,144 for 18-bit ADC)
- **W** (`logicle_w`): Width of linear region (in decades), default 1.0
- **M** (`logicle_m`): Positive decades displayed, default 4.5
- **A** (`logicle_a`): Negative decades, default 0.0 (for positive-only data)

**Parameters Explained:**
- **T** = 262,144 (18-bit ADC range; adjust for 12-bit=4096 or 16-bit=65536)
- **W** = 1.0 (linear width of ~1 decade, smooth transition)
- **M** = 4.5 (display 4.5 positive decades; typical for publication quality)
- **A** = 0.0 (no negative decades; use 0.5+ for negative populations)

**Visual Representation:**
```
Display Space (y)
     ^
4.5  ├─ Log (compressed)
 2.0 ├───── Log region
     │     /
 1.0 ├───/
     │  /
 0.0 ├─────── Linear region (blend)
     │  \
-0.5 ├───\
     │     \
     └──────────────────────► Data Space (x)
     -100    0    100   1000  262144
```

**Implementation (via flowutils C-extension):**
```python
def biexponential_transform(
    data: np.ndarray,
    top: float = 262144.0,
    width: float = 1.0,
    positive: float = 4.5,
    negative: float = 0.0,
) -> np.ndarray:
    """
    Apply Parks 2006 Logicle transform using flowutils C-extension.
    Fallback to asinh approximation if unavailable.
    """
    try:
        # High-performance C implementation
        return flowutils.Logicle(top=top, w=width, m=positive, a=negative).transform(data)
    except ImportError:
        # Fallback: inverse hyperbolic sine approximation
        # asinh ≈ logicle for large values, but not identical
        return np.arcsinh(data / (2 * top)) * positive
```

**Why Use Biexponential?**
- **Publication Standard:** Major journals require Logicle per modern flow cytometry consensus (Spidlen et al., 2008).
- **Interpretability:** Evenly displays dynamic range from negative to positive populations.
- **Symmetry:** Negative/positive regions treated equally (with appropriate A parameter).

### Dithering (jitter) and its effect on gating

> [!WARNING]
> **Known issue:** biexponential gate membership is currently non-deterministic
> near gate edges. Events within about ±0.5 raw units of a boundary can land
> inside on one evaluation and outside on the next.

**What dithering is.** `biexponential_transform` (`analysis/transforms.py`)
takes `enable_dithering: bool = True`. When on, it adds uniform random noise
in `[-0.5, 0.5)` to every raw value before transforming. That's a display fix:
cytometers often emit integer-valued channels, and near zero the Logicle
curve spreads adjacent integers far apart. Without jitter, a density plot shows
discrete "barcode" stripes instead of a continuous population.

**Where it's turned off, and where it isn't.**

| Code path | Dithered? | Effect |
|---|---|---|
| Density/pseudocolor rendering of event arrays | Yes (intended) | Removes barcode banding |
| `CoordinateMapper` (`ui/graph/flow_services.py`): axis limits, gate outlines, click coordinates | No (forces `enable_dithering=False`) | What you see and click is exact |
| Axis tick generation (`transforms.py`) | No | Ticks stay put |
| `project_to_display` (`analysis/_utils.py`), used by **every gate's `contains()`** | **Yes (unintended)** | Gate membership is randomized near edges |

`project_to_display` builds its kwargs from `BiexponentialParameters(scale)`,
which defaults `enable_dithering` to `True`. `AxisScale` has no
`enable_dithering` field, so that default always applies. Both the event
values *and* the gate's own bounds are jittered independently on each call,
so the effective edge moves by up to ±0.5 raw units every evaluation.

**Measured impact.** On `tests/data/fcs/Specimen_001_Sample A.fcs`
(302,017 events), 20 evaluations of the same biexponential gate gave:

| Gate | Count spread across 20 runs | Events that switched in/out at least once |
|---|---|---|
| `RangeGate` FITC-A ≥ 500 | 244 (≈0.4% of ~65.6k) | 393 |
| `RangeGate` PE-A ≥ 5,000 | 27 (≈0.01% of ~224.6k) | 39 |
| `RectangleGate` FITC-A 0–1,000 × PE-A 0–8,000 | 209 (≈0.1% of ~204.8k) | 440 |

The effect is largest when a boundary sits in a dense part of the
distribution close to zero, which is exactly where biexponential scaling is
normally used.

**When users will notice.** Within a session, `GateNode`'s mask cache keeps a
population's result stable, so the same gate doesn't visibly flicker. The
count can shift slightly whenever the mask is recomputed: after editing any
ancestor gate, changing compensation, reloading samples, reopening a
project, or propagating a gate tree to another sample. Consequences:

- A reopened project can report counts and percentages a few tenths of a
  percent different from when it was saved.
- Two samples with *identical* data can get slightly different counts for
  the same propagated gate.
- Linear and log gates are not affected; only axes on a biexponential scale.

**Likely fix.** Gating needs exact, repeatable projection, like
`CoordinateMapper`. Pass `enable_dithering=False` in `project_to_display`,
leaving dithering on only for rendering. Until then, tests avoid asserting
membership at biexponential boundaries (see
[03_TESTING_AND_QA.md](03_TESTING_AND_QA.md#known-issues)).

---

## 2. Coordinate Mapper (Forward & Inverse Transforms)

The `CoordinateMapper` handles transformations between **data space** and **display space**.

```python
class CoordinateMapper:
    """Maps between data and display coordinate systems."""

    def __init__(self, axis_scales: dict[str, AxisScale]):
        self.axis_scales = axis_scales

    def data_to_display(self, param: str, values: np.ndarray) -> np.ndarray:
        """Transform data space → display space (for plotting)."""
        scale = self.axis_scales[param]

        if scale.transform_type == TransformType.LINEAR:
            return values
        elif scale.transform_type == TransformType.LOG:
            return np.log10(np.maximum(values, 0.01)) / 4.0
        elif scale.transform_type == TransformType.BIEXPONENTIAL:
            return logicle_transform(
                values,
                top=scale.logicle_t,
                width=scale.logicle_w,
                positive=scale.logicle_m,
                negative=scale.logicle_a,
            )

    def display_to_data(self, param: str, display_values: np.ndarray) -> np.ndarray:
        """Transform display space → data space (for gate boundaries)."""
        scale = self.axis_scales[param]

        if scale.transform_type == TransformType.LINEAR:
            return display_values
        elif scale.transform_type == TransformType.LOG:
            return 10 ** (display_values * 4.0)
        elif scale.transform_type == TransformType.BIEXPONENTIAL:
            return logicle_inverse(
                display_values,
                top=scale.logicle_t,
                width=scale.logicle_w,
                positive=scale.logicle_m,
                negative=scale.logicle_a,
            )
```

**Example Workflow:**

```
User draws gate on display at: (3.0, 2.5) [display space]
                                    ↓
CoordinateMapper.display_to_data('CD4-PE', [3.0, 2.5])
                                    ↓
Apply inverse Logicle with M=4.5, T=262144
                                    ↓
Result: (50000, 20000) [data space]
                                    ↓
Store in gate.x_min=50000, gate.y_min=20000
```

---

## 3. Auto-Range Calculation (Robust Percentile Bounding)

Computes display axis ranges based on event distribution, excluding outliers.

### Algorithm

```python
def calculate_auto_range(
    data: np.ndarray, axis_scale: AxisScale, outlier_percentile: float = 0.1
) -> tuple[float, float]:
    """
    Compute robust display range excluding outliers.

    Args:
        data: N-element array of event values
        axis_scale: Transformation parameters
        outlier_percentile: Threshold (0.1 = exclude 0.1% tails)

    Returns:
        (display_min, display_max) in transformed display space
    """

    # Step 1: Compute percentile boundaries (exclude tails)
    lower_pct = outlier_percentile / 2  # Typically 0.05%
    upper_pct = 100 - lower_pct  # Typically 99.95%

    p_lower = np.percentile(data, lower_pct)
    p_upper = np.percentile(data, upper_pct)

    # Step 2: Transform to display space
    transform = lambda x: CoordinateMapper({axis_scale.param: axis_scale}).data_to_display(
        axis_scale.param, np.array([x])
    )[0]

    display_min = transform(p_lower)
    display_max = transform(p_upper)

    # Step 3: Extend range slightly for padding
    display_range = display_max - display_min
    display_min -= 0.05 * display_range
    display_max += 0.05 * display_range

    return display_min, display_max
```

### Example: Lymphocyte Gating

```
Raw FSC-A values: [0, 1000, 5000, ..., 250000] (100,000 events)

1. Percentile-based bounds:
   p0.05 = 8000
   p99.95 = 230000

2. Transform (Logicle, M=4.5, T=262144):
   display_min = logicle(8000) ≈ 1.5
   display_max = logicle(230000) ≈ 4.4

3. Apply padding (5%):
   display_min ≈ 1.4
   display_max ≈ 4.5

Result: Plot displays FSC-A from ~1.4 to ~4.5 (display units)
        Captures 99.9% of events; outliers don't compress central populations
```

### Biexponential-Specific Range Extension

For biexponential transforms with negative data, extend range to include negative decades:

```python
if axis_scale.transform_type == TransformType.BIEXPONENTIAL and axis_scale.logicle_a > 0:
    # Add negative decades
    display_min -= axis_scale.logicle_a
```

---

## 4. AxisScale Dataclass

```python
@dataclass
class AxisScale:
    """Persistent axis transformation & display configuration."""

    # Core transform type
    transform_type: TransformType  # LINEAR, LOG, BIEXPONENTIAL

    # Manual override (if set, auto-ranging disabled)
    min_val: float | None = None
    max_val: float | None = None

    # Logicle parameters (Parks 2006)
    logicle_t: float = 262144.0  # Top value (18-bit ADC default)
    logicle_w: float = 1.0  # Linear width (decades)
    logicle_m: float = 4.5  # Positive decades
    logicle_a: float = 0.0  # Negative decades (for negative populations)

    # Auto-ranging configuration
    outlier_percentile: float = 0.1  # Threshold (0.1% tails excluded)
```

### Usage

```python
# Fluorescence channel (CD4-PE)
cd4_scale = AxisScale(
    transform_type=TransformType.BIEXPONENTIAL,
    logicle_m=4.5,
    logicle_t=262144.0,
    outlier_percentile=0.1,
)

# Scatter channel (FSC-A, linear)
fsc_scale = AxisScale(transform_type=TransformType.LINEAR)

# Unstained control (includes negative population)
unstained_scale = AxisScale(
    transform_type=TransformType.BIEXPONENTIAL,
    logicle_a=0.5,  # Include negative decades
)
```

---

## 5. Integration with FlowKit

All transforms delegate to **FlowKit** (wrapper around `flowutils` C-extension):

```python
import flowkit

# Create FlowKit Sample
fk_sample = flowkit.Sample(fcs_path)

# FlowKit handles transforms internally
logicle_params = {"T": 262144, "W": 1.0, "M": 4.5, "A": 0.0}
transformed_data = fk_sample.get_data(transform="logicle", transform_params=logicle_params)
```

This ensures **numerical consistency** across the module; all transforms use the same optimized C code.

---

## 6. Performance Considerations

### Vectorization

All transforms use NumPy vectorization for performance:
```python
# Naive: O(N) with Python loop (slow)
result = [biexponential_transform(x) for x in data]

# Optimized: O(N) with NumPy (100x faster)
result = biexponential_transform(data)  # Operates on arrays
```

### Caching

Axis scales cached per-group to avoid recomputation:
```python
# Experiment.channel_scales[detector_name] = AxisScale(...)
# Reused across all samples in group
```

### C-Extension Fallback

```python
try:
    result = flowutils.Logicle(...).transform(data)  # Fast
except ImportError:
    result = np.arcsinh(data / (2 * top)) * positive  # Slow fallback
```

---

## References

- **Parks, D.R., et al. (2006).** "A new 'Logicle' display method." *Cytometry Part A*, 69A(6), 541-551.
- **Spidlen, J., et al. (2008).** "Data standards for flow cytometry." *Nature Immunology* 9(8), 839-840.
- **[Gating & Compensation Deep Dive](./05_GATING_AND_COMPENSATION_DEEP_DIVE.md)**: Detailed gate algorithms.
