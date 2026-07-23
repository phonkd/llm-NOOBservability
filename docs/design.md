# UI design notes

Theme: **Everforest**, light and dark, both *selected* (dark is not an
auto-flip). Page plane is `bg0`, cards/chart surface `bg1`, text `fg`,
accent green.

## Chart series palette

Six categorical slots, same hue order in both modes (color follows the
entity). Everforest's stock dark pastels fail colorblind-separation and
chroma checks, so the dark steps are deepened variants of the same hues,
validated with the dataviz six-checks script against the actual card
surfaces:

| slot | hue | light (`#f4f0d9`) | dark (`#343f44`) |
|---|---|---|---|
| 1 | green | `#8da101` | `#8da101` |
| 2 | blue | `#3a94c5` | `#3a94c5` |
| 3 | orange | `#f57d26` | `#e2632a` |
| 4 | purple | `#df69ba` | `#d066b0` |
| 5 | yellow | `#dfa000` | `#bd8400` |
| 6 | red | `#f85552` | `#e64845` |

Validation results: light worst adjacent CVD ΔE 30.8, dark 20.9 (target
≥ 12); all slots inside the lightness band and above the chroma floor in
their mode. Several slots sit below 3:1 contrast against the surface
(inherent to Everforest's soft look); the mandated relief is applied:
uPlot's live legend always names every series, values are readable in the
legend on hover, and the full data is one click away (JSON/CSV download,
log table for streams).

Charts cap at the **top 6 series by mean |value|** — slots are never cycled;
the remainder is noted and available in the JSON download.

## Layout

Fresh state: full viewport, centered rounded card with the question input.
After the first question the card docks to the bottom; each exchange stacks
above it in the scroll area as: question bubble → attempt steps (monospace,
the executed query always visible) → summary text → chart/log-table card
with download buttons.
