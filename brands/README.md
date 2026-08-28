# Integration icon / brand assets

This folder contains the icon assets for the **integration itself** (the
picture shown next to "Stundenplan" in **Settings → Devices & Services**,
in the "Add Integration" search, and in the HACS store) — as opposed to
`custom_components/stundenplan/icons.json`, which only controls the icons
of individual *entities* (sensors) once the integration is set up.

## Why these files aren't picked up automatically

Home Assistant does **not** read integration icons from `manifest.json` or
from any file inside `custom_components/`. Both HA core and HACS fetch them
at runtime from the central CDN **brands.home-assistant.io**, which is built
from the **[home-assistant/brands](https://github.com/home-assistant/brands)**
repository — a separate, community-curated repo. There is no manifest field
or local file that can set this icon directly.

To make the icon actually appear, the files below need to be submitted via
pull request to that repository, under:

```
custom_integrations/stundenplan/icon.png
custom_integrations/stundenplan/icon@2x.png
custom_integrations/stundenplan/logo.png
custom_integrations/stundenplan/logo@2x.png
```

See the [home-assistant/brands contribution
guide](https://github.com/home-assistant/brands#adding-a-new-integration-or-brand)
for the exact requirements and PR process. Once merged, Home Assistant and
HACS will pick it up automatically within a day or so — no release or code
change in *this* repository is needed.

## What's in this folder

| File | Size | Content |
|---|---|---|
| `icon.png` | 256×256 | `mdi:school-outline` in blue (`#1976D2`), transparent background |
| `icon@2x.png` | 512×512 | same, retina/high-DPI resolution |
| `logo.png` | 256×256 | identical to `icon.png` — there is no separate wordmark/logo for this integration |
| `logo@2x.png` | 512×512 | identical to `icon@2x.png` |

The icon is rendered directly from the official MDI `school-outline` path
data (icon code `F1180`, added in MDI v4.4.95,
[source](https://pictogrammers.com/library/mdi/icon/school-outline/)),
colored blue, so it stays visually consistent with the "built-in icon
library" look requested for this integration.
