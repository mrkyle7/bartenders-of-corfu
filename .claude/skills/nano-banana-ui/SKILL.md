---
name: nano-banana-ui
description: Use Gemini "Nano Banana" image generation to help with UI work — generate visual mockups of a screen before coding it, restyle a screenshot of the current UI to explore a redesign, or produce raster assets (card art, ingredient icons, backgrounds, logos) for `static/`. Use when the user asks to "mock up", "visualise", "generate art/an icon/an image for", "show me what X could look like", or mentions nano banana / Gemini images.
argument-hint: "[mockup|restyle|asset] <what you want>"
---

# Nano Banana for UI

Gemini's image models ("Nano Banana" = `gemini-2.5-flash-image`, "Nano Banana Pro" = `gemini-3-pro-image-preview`) are good at two things that help here:

1. **Exploring visual direction cheaply** — a picture of a redesigned screen costs seconds; implementing one costs hours.
2. **Producing raster assets** — illustrated card art, ingredient icons, textured backgrounds.

They are **not** a source of truth for layout or code. A generated mockup is a reference image; the real UI is still hand-built in HTML/CSS by the `ui-developer` agent, under the rules in `.claude/agents/ui-developer.md` (board-game interaction model, WCAG 2.1 AA, 320 px / 1280 px layouts, theming tokens).

## Tool

```bash
python3 .claude/skills/nano-banana-ui/scripts/nano_banana.py "<prompt>" -o <out.png> \
    [-i reference.png ...] [--aspect 16:9] [-n 3] [--model gemini-3-pro-image-preview]
```

- Key: `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) from the environment, else from the repo `.env` (gitignored). If missing, tell the user to get one at https://aistudio.google.com/apikey and add `GEMINI_API_KEY=...` to `.env` — never ask them to paste it into chat, never echo it.
- Image models need billing on the AI Studio project. A `402 ... prepayment credits are depleted` error means the user must top up at https://ai.studio/projects — don't retry.
- `-i` attaches reference images (repeatable) → edit / restyle mode.
- `-n` makes N independent variations (`out-1.png`, `out-2.png`, …). Each is a paid API call — default to 1–3.
- Prints the written paths on stdout. After running, **Read each image** to look at it before describing it to the user.
- Put exploratory output in the session scratchpad directory, not the repo. Only assets the user has approved go into `static/`.

## Modes

### `mockup` — visualise a screen before building it

1. Gather context first: read the relevant page (the game is the bar top: `static/bar.html`, `static/bar/app.js`, `static/css/bar.css`) and the colour tokens in `bar.css` `:root` (walnut, Aegean, whitewash, kumquat), so the prompt describes the *real* screen (elements, states, game vocabulary), not a generic one.
2. Write a prompt that states: device + aspect (`--aspect 9:16` for 320–414 px mobile, `16:9` for desktop), the screen and its purpose, every element that must appear, the palette (pull hex values from `bar.css`), and "flat UI screenshot, no device frame, legible text".
3. Generate 2–3 variations, Read them, and present a short comparison. Ask the user which direction to pursue.
4. Hand the chosen image path plus a written spec to the `ui-developer` agent to implement. Call out anything in the mockup that would violate project rules (low-contrast text on the walnut table or Aegean mats, hidden mid-turn controls, tiny tap targets) so it isn't copied.

### `restyle` — redesign an existing screen from a screenshot

1. Capture the current UI: run the app (`./run-local.sh` or the `run` skill) and take a screenshot with Playwright (`browser_take_screenshot`), at 375 px and/or 1280 px width. Save it to the scratchpad.
2. Pass it with `-i` and a prompt like *"Keep the exact layout and every element of this game screen; restyle it as <direction>. Keep all text legible with strong contrast."* Constraining "keep layout" keeps the result implementable.
3. Same review → choose → hand-off flow as `mockup`.

### `asset` — art that ships in `static/`

1. Prompt for the asset alone: subject, style consistent with existing art (attach an existing asset such as `static/bar/img/cards/karaoke.webp` with `-i` as a style reference — but not a UI screenshot: the model copies badges and panels from it as blank boxes, so describe the style in words instead), plain or solid background, square (`--aspect 1:1`) for icons/cards, no text baked in (text belongs in HTML for accessibility and i18n).
2. Read the result and show the user. Only after approval, copy into `static/bar/img/` (card scenes in `static/bar/img/cards/`) with a descriptive kebab-case filename.
3. Shrink before committing — Gemini returns ~1 MP images (Pro returns JPEG; the script picks the extension). Convert to WebP with Pillow without adding a project dependency: `uv run --with pillow python ...` (card scenes ~400 px wide, icons 128–280 px, textures 384–640 px). For an object on white, flood-fill the white from the edges to transparent and crop to the alpha bounding box. For a texture that must tile, mirror it into a 2×2 grid — it then repeats without seams. Frames (Greek-key borders) work as CSS `border-image` 9-slices: measure the band width in pixels for the slice.
4. Wire it in with a meaningful `alt` (or `alt=""` + `aria-hidden` if purely decorative), and check it reads on both the light page chrome and the dark board.

## Prompting tips

- Be concrete and positive: list what must be visible, in what order, with which colours. Name the game nouns (karaoke card, bladder, cup, spirit/mixer ingredients, card rows 1–3).
- Models still garble small text. For mockups, accept placeholder text; never ship an asset with baked-in words.
- For edits, describe the *change* and what to preserve ("keep composition, change only the background to …").
- If the API refuses or returns no image, the script prints the model's note — rephrase rather than retry verbatim. `IMAGE_RECITATION` means the prompt is too close to stock imagery (e.g. a plain wood texture): make it more specific or painterly.
- Use Pro (`--model gemini-3-pro-image-preview`) when text rendering or fine detail matters; Flash for fast iteration.
