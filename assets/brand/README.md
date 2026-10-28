# strata-memory brand marks

Files in this folder are the supplied logo package. `extensions/` is the V2 set. `original/` is the earlier icon set. Nothing here was redrawn.

`*_light_*` fills are for light backgrounds. `*_dark_*` fills are for dark backgrounds. SVGs are self-contained (outlined wordmark, no external fonts). PNGs are rasters of those SVGs. The note shipped with the V2 files is `extensions/README.txt`.

Four original PNGs are not copied. They are byte-identical to the V2 transparent icons:

| Omitted original | Identical file kept |
|------------------|---------------------|
| `original/logo_dark_transparent_512.png` | `extensions/icon_dark_transparent_512.png` |
| `original/logo_dark_transparent_1024.png` | `extensions/icon_dark_transparent_1024.png` |
| `original/logo_light_transparent_512.png` | `extensions/icon_light_transparent_512.png` |
| `original/logo_light_transparent_1024.png` | `extensions/icon_light_transparent_1024.png` |

The matching original SVGs are kept. They differ from the V2 SVGs (the originals include an `aria-label`).

## Which file to use

| Use | File |
|-----|------|
| Agensi listing icon, recall dot, 512 | `extensions/icon_light_transparent_512.png` on light, `extensions/icon_dark_transparent_512.png` on dark |
| Same icon, 1024 | `extensions/icon_*_transparent_1024.png` |
| Same icon, vector | `extensions/icon_*_transparent.svg` |
| Favicon, no recall dot | `extensions/favicon_minimal_light.ico` or `extensions/favicon_minimal_dark.ico` |
| GitHub / docs header | `extensions/lockup_light_transparent.svg` or `extensions/lockup_dark_transparent.svg` |
| Wordmark only | `extensions/wordmark_light_transparent.svg` or `extensions/wordmark_dark_transparent.svg` |

## extensions/ (V2)

Recall-dot icon, transparent background. Square mark for listings.

- `icon_light_transparent.svg`, `icon_light_transparent_512.png`, `icon_light_transparent_1024.png`
- `icon_dark_transparent.svg`, `icon_dark_transparent_512.png`, `icon_dark_transparent_1024.png`

No-dot icon, solid rounded square.

- `icon_light_minimal.svg`, `icon_light_minimal_512.png`, `icon_light_minimal_1024.png`
- `icon_dark_minimal.svg`, `icon_dark_minimal_512.png`, `icon_dark_minimal_1024.png`

No-dot icon, transparent background.

- `icon_light_minimal_transparent.svg`, `icon_light_minimal_transparent_512.png`, `icon_light_minimal_transparent_1024.png`
- `icon_dark_minimal_transparent.svg`, `icon_dark_minimal_transparent_512.png`, `icon_dark_minimal_transparent_1024.png`

No-dot favicons. Each theme has 16, 32, 48, 64, 180, and 192 PNG, plus an `.ico`.

- `favicon_minimal_light.ico`, `favicon_minimal_light_16.png`, `favicon_minimal_light_32.png`, `favicon_minimal_light_48.png`, `favicon_minimal_light_64.png`, `favicon_minimal_light_180.png`, `favicon_minimal_light_192.png`
- `favicon_minimal_dark.ico`, `favicon_minimal_dark_16.png`, `favicon_minimal_dark_32.png`, `favicon_minimal_dark_48.png`, `favicon_minimal_dark_64.png`, `favicon_minimal_dark_180.png`, `favicon_minimal_dark_192.png`

Horizontal symbol + wordmark, transparent. Header lockup. SVG, 1240 px, and 2480 px.

- `lockup_light_transparent.svg`, `lockup_light_transparent_1240.png`, `lockup_light_transparent_2480.png`
- `lockup_dark_transparent.svg`, `lockup_dark_transparent_1240.png`, `lockup_dark_transparent_2480.png`

Wordmark alone (`strata-memory`), transparent. SVG, 1000 px, and 2000 px.

- `wordmark_light_transparent.svg`, `wordmark_light_transparent_1000.png`, `wordmark_light_transparent_2000.png`
- `wordmark_dark_transparent.svg`, `wordmark_dark_transparent_1000.png`, `wordmark_dark_transparent_2000.png`

Sheet of the V2 lockups and icons: `preview_v2.png`.

## original/

Recall-dot icon on a solid rounded square, with favicons. Not the V2 minimal or lockup set.

- `logo_light.svg`, `logo_light_512.png`, `logo_light_1024.png`
- `logo_dark.svg`, `logo_dark_512.png`, `logo_dark_1024.png`
- `logo_light_transparent.svg`, `logo_dark_transparent.svg` (PNG rasters are the identical V2 files listed above)
- `favicon_light.ico` and `favicon_light_16.png`, `favicon_light_32.png`, `favicon_light_48.png`, `favicon_light_64.png`, `favicon_light_180.png`, `favicon_light_192.png`
- `favicon_dark.ico` and `favicon_dark_16.png`, `favicon_dark_32.png`, `favicon_dark_48.png`, `favicon_dark_64.png`, `favicon_dark_180.png`, `favicon_dark_192.png`
- `preview.png` — light and dark original icons
