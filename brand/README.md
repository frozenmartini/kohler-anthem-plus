# Brand icons

`icon.png` (256×256) and `icon@2x.png` (512×512) are the integration's icons in the
Home Assistant UI — the integrations dashboard, the config-flow dialog, and the device
pages. Both are built from `src/icon-v22.svg` — the violet variant, chosen by the
owner 2026-08-22 from the 24-version workbench (v18, the pink original, shipped
2026-08-21–2026-08-22 and stays in `src/` as the previous mark).

## Why they live here and not in the brands repo

Home Assistant **2026.3** added a brands proxy: brand images are served through the
local API at `/api/brands/integration/{domain}/{image}` instead of being fetched from
the CDN by the browser, and **a custom integration's own `brand/` folder takes priority
over the CDN**. Dropping the PNGs here is the whole setup — no `manifest.json` change,
no PR to anyone. Confirmed working on this install.

This replaces the old route of submitting to `home-assistant/brands` under
`custom_integrations/`. That folder is now marked *legacy* in the brands repo README,
and PRs against it are auto-closed with a pointer to this mechanism.

Filenames the proxy recognises: `icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`,
and a `dark_` prefixed form of each.

Two consequences worth knowing:

- **The icons need a Home Assistant Core restart to appear.** They are read at
  integration load, not on a browser refresh.
- **On Home Assistant older than 2026.3 the folder is simply ignored** and the default
  puzzle-piece icon shows instead. That is a graceful fallback, so `hacs.json` does not
  need its `homeassistant: 2024.2.0` minimum raised on account of these files.

## The mark

A control strip with a dial riding on it, derived from the hub web UI's
`InterfaceIcon.svg`. Three things carry the design:

**The lines are holes, not strokes.** A luminance mask cuts the bar's outline and the
dial's ring clean through the tile, so the card behind shows through them — white on a
light theme, near-black on a dark one. The mask's paint order is load-bearing: it fills
white, cuts the bar outline, **restores white over the dial**, then cuts the ring. That
middle step is what stops the bar's lines slicing across the dial, which the original
drawing got for free by painting the dial last.

**The bar runs off the right edge.** Its left margin and its right overflow are both
exactly one line weight, because the composition is placed flush and then shifted by one
line weight — so the margin and the cut lines are the same thickness. The bar's right
vertical stroke lands precisely outside the canvas, meaning the bar has no right edge at
all; it simply continues out of frame.

**The dial overhangs the bar.** This is what makes it read as a controller rather than a
camera: a camera body encloses its lens, a control strip has the dial riding on it,
breaking the line top and bottom.

## Why there is no `dark_icon.png`

Because the artwork was tuned to look the same on both themes rather than to look best
on one. Only three things about this design change with the card behind it, and two of
them are the same measurement — the tile against the card:

| | light card | dark card | gap |
| --- | --- | --- | --- |
| tile silhouette vs card | 4.15:1 | 4.11:1 | 0.04 |
| bar cut-lines vs tile | 4.15:1 | 4.11:1 | 0.04 |
| dial ring vs dial | 6.09:1 | 2.80:1 | 3.29 |

The tile — the dominant surface, and the ground for the bar's cut lines — keeps the
neutrality discipline: `#A35CD6` lands at relative luminance 0.2030 against the
theme-neutral point of 0.2043 (the geometric mean of Home Assistant's two card grounds),
so both tile rows sit within 0.04 of each other, matching v18's 0.02. The drift lives in
the dial ring: `#6A3DE8` is deeper than v18's `#D81B60`, so the ring pops harder on a
light card (6.09:1) and softens on a dark one (2.80:1, just under the 3:1 UI-component
guideline). Total drift 3.37 against v18's 1.55 — the trade the owner took for the
violet, chosen with both grounds visible in the workbench.

A `dark_` pair earns its keep when a design is markedly better on one ground than the
other. The dominant surfaces are not, and the ring stays legible on both, so it still
ships as a single file — revisit if the dark-card ring ever bothers in practice.

## Palette

| Token | Hex | Use |
| --- | --- | --- |
| Tile | `#A35CD6` | Rounded-square ground; theme-neutral |
| Dial | `#6A3DE8` | Filled ellipse, the subject |
| Lines | — | Not painted: cut through to the card behind |

Corner radius 16 on a 79 grid (20.3%). Outside the rounded corners the PNG is fully
transparent, so it composites cleanly on any card colour, and `-trim` is a no-op — the
brands repo's "minimum empty space on the edges" rule is satisfied.

## Rebuilding

```sh
./src/build.sh              # v22, the shipped mark
./src/build.sh v18          # or any other src/icon-<name>.svg
```

`src/` also holds earlier explorations kept for reference — `icon-v18.svg` (the pink
mark that shipped before v22), `icon-bleed-right.svg` (what shipped before v18), plus `icon-band.svg`, `icon-bleed-both.svg` and `icon-letterbox.svg`
from the first pass. They are square opaque tiles with painted white strokes rather than
knockouts, so they predate everything described above.

## Provenance

`src/_source-InterfaceIcon.svg` is the original mark, extracted from the hub's web UI
asset bundle — a stroked rounded rectangle and a filled ellipse, 78×35.

Since this repository is headed for GitHub: the mark originates in Kohler's own UI
assets, and this is an unofficial third-party integration. The geometry has been
substantially reworked and the colours are no longer Kohler's, but if that association is
unwanted, the fix is to redraw the mark rather than to recolour it again. Nothing in the
build depends on the source file.
