# Brand icons

`icon.png` (256×256) and `icon@2x.png` (512×512) are the integration's icons in the
Home Assistant UI — the integrations dashboard, the config-flow dialog, and the device
pages. Both are built from `src/icon-v18.svg`.

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
| tile silhouette vs card | 4.14:1 | 4.12:1 | 0.02 |
| bar cut-lines vs tile | 4.14:1 | 4.12:1 | 0.02 |
| dial ring vs dial | 4.95:1 | 3.45:1 | 1.50 |

Total drift **1.55**. The tile's fill governs two thirds of that and the dial's only one
third, which is why the near-neutral colour sits on the tile. `#D4468F` lands at
relative luminance 0.2036 against the theme-neutral point of 0.2043 — the geometric mean
of Home Assistant's two card grounds — so it is within a thousandth of the tone that
treats both themes identically.

A `dark_` pair earns its keep when a design is markedly better on one ground than the
other. This one is not, so it ships as a single file.

## Palette

| Token | Hex | Use |
| --- | --- | --- |
| Tile | `#D4468F` | Rounded-square ground; theme-neutral |
| Dial | `#D81B60` | Filled ellipse, the subject |
| Lines | — | Not painted: cut through to the card behind |

Corner radius 16 on a 79 grid (20.3%). Outside the rounded corners the PNG is fully
transparent, so it composites cleanly on any card colour, and `-trim` is a no-op — the
brands repo's "minimum empty space on the edges" rule is satisfied.

## Rebuilding

```sh
./src/build.sh              # v18, the shipped mark
./src/build.sh vermilion    # or any other src/icon-<name>.svg
```

`src/` also holds earlier explorations kept for reference — `icon-bleed-right.svg` (what
shipped before v18), plus `icon-band.svg`, `icon-bleed-both.svg` and `icon-letterbox.svg`
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
