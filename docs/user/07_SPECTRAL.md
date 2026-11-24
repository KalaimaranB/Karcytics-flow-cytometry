# Spectral

The **Spectral** tab is a self-contained workspace for evaluating fluorophore spectra — independent of any loaded sample's gating hierarchy. It answers the question you should ask *before* you run a panel, not after: "will these dyes' emission spectra bleed into each other badly enough to cause a problem?"

The tab has no ribbon toolbar; every control lives inside the workspace itself, split across two inner tabs: **Spectral Analysis** and **Learning Compensation**.

![alt text](../images/07_spectral/spectral_view.png)

## Spectral Analysis

### Adding fluorophores to the plot

There are three ways to add a dye's spectrum to the plot:

- **Double-click** a channel in the **Available Channels** list, which is auto-populated from every currently loaded sample's real detector panel (channels are de-duplicated across samples, and scatter/time channels are excluded).
- **Drag** a channel from that same list directly onto the plot area.
- **Search FPbase** by typing a dye name (e.g. "APC/Cy7", "Alexa Fluor 488") into the search box — an autocomplete list appears as you type, and clicking a result adds it.

The first time you open the tab with real channel data available, every detected channel is plotted automatically so you're never staring at an empty canvas — clearing the plot afterward with **Clear All** won't trigger that auto-fill again.

Each added dye appears in the **Active Spectra** list with a colour swatch and, where FPbase provides the data, **QY** (Quantum Yield) and **EC** (Extinction Coefficient) chips — both relevant to how bright a dye will actually appear on your instrument. Double-click an entry in that list to remove it.

![alt text](../images/07_spectral/channel_view.png)

!!! tip
    Common naming mismatches between your FCS channel names and FPbase's dye names (e.g. "APC-Cy7" vs "APC/Cy7", "PerCP-Cy5-5" vs "PerCP-Cy5.5") are resolved automatically when you drag or double-click from the channel list.

### Reading the curves

Three curve types can be toggled independently with the **AB / EX / EM** buttons above the plot:

- **AB (Absorbance)** — the wavelengths of light the dye absorbs; mostly a chemistry detail, shown dotted and faint.
- **EX (Excitation)** — the wavelengths that make the dye fluoresce; use this curve to pick which laser line to excite it with. Shown dashed.
- **EM (Emission)** — the wavelengths the dye emits back; use this curve to pick which detector should capture it. Shown solid, and this is the curve used for the overlap analysis below. On by default alongside EX.

![alt text](../images/07_spectral/button_toggle.png)

### Spectral overlap evaluation

Whenever two or more dyes have their Emission curves visible, the plot automatically shades every pairwise region where both curves are meaningfully above zero, and drops a callout at the peak of the shaded region reporting the overlap as a percentage. The percentage comes from the emission curves alone. The Learning Compensation deck goes one step further and also counts the lasers (see below), so its numbers can be smaller.

Click a callout to dismiss it if it's blocking your view of the curves underneath — this only hides that one annotation, and it reappears if you reopen the tab.


!!! tip "Panel design"
    Use this view before you commit to a panel, not after you've already stained cells. Two dyes with peaks 50 nm apart can still overlap 20–30% or more — if the overlap is heavy, either accept that compensation will be doing real work on that pair, or put the two dyes on markers you're confident will never both be positive on the same cell.


!!! tip "The Golden Rule of panel design"
    Compensation can correct the *average* leakage between two dyes, but heavy spectral overlap still increases noise (spreading error) in the corrected data. The best fix for two heavily overlapping dyes is not a bigger compensation matrix — it's assigning them to markers that are never expected to be positive on the same cell.


## Learning Compensation

A seven-slide interactive deck that teaches compensation with numbers worked out from the dyes you have loaded (at least two with spectra). Each slide has a task; **Next Step →** unlocks when it's done.

| Slide | What you do |
| --- | --- |
| 1. The Physics of Overlap | Drag a detector's filter onto a dye's peak, then click the marker of the dye that reaches highest inside it. Only dyes that detector's laser lights up get a marker. |
| 2. Setting the Zero | Choose where an unstained control's threshold belongs, then drag the crosshair just past the unstained cloud. |
| 3. Measure the Spillover | After a worked example, drag a ruler along a single-stain cloud and turn its Rise and Run into "for every 100 units of the first dye, the second detector reads __ extra". |
| 4. Find the Level | Drag a "% subtracted" slider until the single-stain cloud lies level with the unstained cells: too little and it climbs (under-compensated), too much and it dips (over-compensated). |
| 5. Same Rule, Every Cell | Three cells shown as bars of their second-detector reading: one worked example, one rule question, one half-done calculation, and one you do alone. |
| 6. Gate the Cleaned Data | Draw a rectangle around the double-positive population. |
| 7. Building the Matrix | Pick the control tube that measures one dye's spillover, and count the tubes a full matrix needs. |

On every slide:

- **👉 Your turn** (above the explanation) always says what to do next, what went wrong on your last try, and when the slide is done.
- **💡 Show me** draws the move on the plot (a target zone, a line to trace, a drag arrow) or outlines the answer box. On the maths slides it gives the next step of the sum, not the answer. After 30 seconds on a slide, the Your turn box suggests it.
- **🧮** (on the maths slides) works out what you type: numbers, + − × ÷, brackets and %, as in `750 × 20%`.

**How the deck estimates spillover.** A dye's spillover into another dye's detector is its emission at that detector's peak, scaled by how well that detector's laser excites it compared with the dye's own best laser. The deck assumes a common three-laser cytometer (405, 488 and 640 nm). The deck teaches with the largest such spillover among your dyes; Slide 7's heatmap shows the whole estimate, dyes as rows and detectors as columns. Real values come from single-stain controls on your own instrument.

