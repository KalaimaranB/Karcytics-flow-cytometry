"""What the compensation matrix editor tells the user: its caption, goal line
and the "What a good matrix looks like" guide.

Kept apart from the editor widget so the wording can be read and changed in
one place.
"""

GOAL_LINE = (
    "<b>Aim:</b> on the After side, events positive for one dye sit level with the "
    "negatives in the other detector — not tilted up, not pushed below."
)
GUIDE_TITLE = "What a good matrix looks like"
GUIDE = (
    "<b>The goal.</b> A dye should only be seen by its own detector. After compensation, "
    "cells that carry dye A but not dye B must read the same in B's detector as cells "
    "that carry neither. Each cell of the matrix is the one number that makes that true "
    "for one dye and one detector.<br><br>"
    "<b>On the scatter plots.</b> Look at the population that is bright on X only. "
    "Before, it climbs diagonally: the brighter the dye, the more leaks into Y. After, "
    "it should lie <b>level</b>, its centre at the same height as the negative "
    "population's centre.<br>"
    "• Still tilted upwards → the cell is too low (under-compensated).<br>"
    "• Bent downwards, below the negatives → the cell is too high (over-compensated).<br>"
    "• Bright events fan out wider than dim ones. That spread is measurement noise and "
    "no value removes it: judge the <b>centre</b> of the cloud, not its edges.<br><br>"
    "<b>On the histograms.</b> In a sample without dye B, the After curve of B's "
    "detector should be one peak centred on the unstained level (around zero), roughly "
    "symmetric. A tail or shoulder left on the right means under-compensated; a peak "
    "pushed left of zero means over-compensated.<br><br>"
    "<b>What the values should be.</b> There is no target number: a value is right when "
    "the plots are. As a sanity check, the diagonal is 1, most cells are between 0 and "
    "about 0.3, neighbouring dyes off the same laser are the large ones, and a value "
    "near or above 1 usually means the wrong pairing or a bad control.<br><br>"
    "<b>Which sample to judge on.</b> Judge a cell on a sample where its row dye is "
    "bright and its column dye is absent: the single-stain control for the row dye is "
    "ideal, an FMO lacking the column dye also works. Don't tune on fully stained "
    "samples alone: cells that really carry both markers look like spill, and "
    "compensating them away removes real biology.<br><br>"
    "<b>Why look across samples.</b> Spill is a property of the dyes and the instrument "
    "settings, not of a tube, so one matrix has to work for every sample of the run. "
    "<i>All samples</i> shows whether a value that fixes one tube tilts another: if it "
    "does, it was fitted to that tube's quirk, not to the spill. Samples that disagree "
    "consistently (tandem dyes that degraded, a tube acquired with other settings) "
    "need their own matrix."
)

MATRIX_CAPTION = (
    "<b>↓ Rows: dye</b> (the signal's source) &nbsp;·&nbsp; "
    "<b>→ Columns: detector</b> (where it spills into)<br>"
    "A cell is the share of the row dye's signal picked up by the column detector, so "
    "the two cells of a pair are separate numbers. Click a cell to plot its pair; "
    "double-click to fine-tune its value."
)
