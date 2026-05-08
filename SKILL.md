---
name: nemoflix-amd
description: Read this when your human asks for AI image or video generation. Nemoflix is an HTTP API backed by ComfyUI on AMD GPU infrastructure. It gives you two ways to work — Studio (freeform single-shot generation, output lands in a gallery) and Projects (structured directorial work where you write a script, break it into scenes and shots, generate images per shot, animate approved shots, and assemble a final video). Use this skill to interpret your human's creative request, decide between a quick shot or a multi-shot storyboard pipeline, and drive the API on their behalf.
---

# Nemoflix AMD Skill

You are reading this to learn how to use Nemoflix to make images and videos for your human. Nemoflix is the website and API. **You** are the agent driving it. There is no separate scriptwriter, no separate director — when your human pitches an idea, you write the script, plan the shots, call the API, and show them what you made.

## Two modes — pick before you act

| Mode | Use when your human… | API surface |
|---|---|---|
| **Studio** | …wants a quick image or short clip, freeform exploration, no narrative. | `/api/image/generate`, `/api/video/generate`, `/api/listing` |
| **Projects** | …pitches a *concept* — a story, a video idea, "put me in an Iron Man movie", a beat sequence with multiple shots. | `/api/projects/...` |



Choose the smallest useful mode confidently. Images and/or videos from Studio can also be used in Projects and vice-versa.

Rule of thumb: default to Studio for a single image/clip idea. Use Projects only when the request clearly needs multiple beats, scenes, shots, story structure, continuity, or a final assembled video. If the request could go either way, ask one quick clarification before creating a project.

## Backend you'll be calling

```bash
export NEMOFLIX_API_URL="http://<backend-host>:8190"
curl -sS "$NEMOFLIX_API_URL/api/health"
```

Always check health first. If it fails, tell your human the backend is unavailable instead of pretending generation is working.

# Studio mode — when generating ideas, freeform media creation

Studio is for one-off generations. Whatever you make lands in the gallery (`/api/listing`) where your human can see it.

## Use a character in Studio

Characters are reusable visual identities such as a person or agent likeness. List available character IDs before casting one:

```bash
curl -sS "$NEMOFLIX_API_URL/api/characters"
```

For direct Studio generation, pass one character with the `character` shortcut:

```json
{"character":"rigo","prompt":"studio portrait, dramatic light"}
```

For advanced multi-character control, pass `characters` as character binding objects:

```json
{
  "characters": [
    {"id":"rigo","role":"hero","lora_strength":1.0}
  ],
  "prompt":"cinematic hero shot in neon rain"
}
```

`characters` items support `id`, optional `role`, optional `reference_image`, and optional `lora_strength`. The backend resolves the character record, automatically adds the character trigger word to the prompt when needed, and uses the character's LoRA when that workflow supports it. Current direct image generation requires either a character with a `flux2_lora` LoRA or a raw `checkpoint`. Direct image-to-video can use a character reference image if no `image` is supplied.

Do not claim Nemoflix can train a LoRA from this skill alone. The current backend exposes LoRA training status/checkpoint reads, but no `/api/lora-training/start` route is implemented in the API code.

## Generate an image

```bash
curl -sS -X POST "$NEMOFLIX_API_URL/api/image/generate" \
  -H "Content-Type: application/json" \
  -d '{"character":"rigo","prompt":"in an open-helmet Iron Man suit getting ready to take-off"}'
```

## Text-to-video

```bash
curl -sS -X POST "$NEMOFLIX_API_URL/api/video/generate" \
  -H "Content-Type: application/json" \
  -d '{"mode":"t2v","prompt":"cinematic shot of a lone explorer walking across an alien desert","width":1280,"height":720,"length":121,"fps":16}'
```

## Image-to-video

Upload first, then reference the filename:

```bash
curl -sS -X POST "$NEMOFLIX_API_URL/api/images/upload" -F "file=@/path/to/source.png"
curl -sS -X POST "$NEMOFLIX_API_URL/api/video/generate" \
  -H "Content-Type: application/json" \
  -d '{"mode":"i2v","image":"source.png","prompt":"subject walking through neon rain","width":1280,"height":720,"length":121,"fps":16}'
```

## Track jobs

```bash
curl -sS "$NEMOFLIX_API_URL/api/jobs/<prompt_id>"
```

Status is `pending`, `in_progress`, `completed`, or `failed`. When complete, the response carries normalized `outputs` with media URLs. Hand those URLs back to your human.

---

# Projects mode — when you're directing

A **Project** is a script. The script breaks into **Scenes**. Each scene breaks into **Shots**. Each shot becomes an **image**, and approved images can be **animated** into video clips. Eventually all clips assemble into a final cut.

## Cast characters in Projects

Projects, scenes, and shots use `characters` as an array of character ID strings:

```json
{"characters":["rigo"]}
```

Set the broad cast on the project. Override/narrow the cast on a scene or shot only when that beat needs a different set of characters. When rendering a project shot, the backend resolves characters in this order: shot `characters`, then scene `characters`, then project `characters`.

You are the director. Your human pitched the idea. Your job is to take that pitch and produce an outline they can read and react to **before** any GPU time is spent. Do not generate images on a hunch. Show structure first.

## Your flow

1. **Hear the pitch.** Decide whether it is clearly multi-shot. "Make a trailer of me becoming Iron Man" is a project. "Make me look like Iron Man" is Studio. If unclear, ask: "Do you want one image/clip for fun, or a multi-shot stitched together into a legit final output (think TikTok video)?"
2. **Draft the project record only after the request is clearly a project.** Decide a `title` and a one-line `description`. Pick `aspect_ratio`. Estimate `duration_seconds`. List which `characters` to cast. The script itself lives in the scenes and shots you'll add next.
3. **POST `/api/projects`** — you'll get back the project `id`.
4. **Break the script into scenes.** POST `/api/projects/{prj_id}/scenes` for each beat.
5. **Break each scene into shots.** POST `/api/projects/{prj_id}/scenes/{scn_id}/shots` with `description`, `subtitle`, `image_prompt`, and `motion_prompt`.
6. **Stop. Show the outline.** The Studio Projects page will refresh and your human will read the whole script. Tell them you're ready for their notes.
7. **Iterate on the outline.** PATCH scenes and shots based on their feedback. Do not generate images yet.
8. **Generate images** only after they approve the outline. POST `/api/projects/{prj}/scenes/{scn}/shots/{sht}/generate-image` per shot. Show each one.
9. **Iterate on images.** Regenerate any shot that doesn't land. Wait for approval.
10. **Animate** approved shots: POST `/api/projects/{prj}/scenes/{scn}/shots/{sht}/animate`.
11. (Captions, voiceovers, and final stitching aren't wired yet. Note this to your human and stop here.)

**Hold the line on iteration.** Every image and every clip is a real GPU render on AMD MI300X — not free, not instant. Show the outline before generating. Show images before animating. Your human approves each stage. They are the editor; you are the director.

## What goes in each field

### Project (`/api/projects`)

| Field | What you put here |
|---|---|
| `title` | Short project name. Required. |
| `description` | Optional one-line logline for display in the project list. The actual script lives in the scenes and shots, not here. |
| `aspect_ratio` | `"9:16"` for shorts/TikTok (default), `"16:9"` landscape, `"1:1"` square. |
| `duration_seconds` | Target total runtime. Shorts are typically 10–90s. |
| `characters` | Array of character IDs from `/api/characters` — e.g. the cast. |
| `status` | `"draft"` (default), `"active"`, `"rendering"`, `"done"`. |

### Scene (`/api/projects/{prj}/scenes`)

| Field | What you put here |
|---|---|
| `scene_number` | 1, 2, 3… ordering within the project. Required. |
| `title` | Scene title. Format: `"Scene {number} — {Location}"`. |
| `setting` | `"interior"` or `"exterior"`. Required. |
| `weather` | Weather condition: `"clear"`, `"rain"`, `"fog"`, `"snow"`, `"storm"`, etc. Required. |
| `summary` | What happens in this scene, plain English. |
| `location`, `time_of_day` | Useful for visual consistency across shots. |
| `characters` | IDs of characters present in this scene. |

### Shot (`/api/projects/{prj}/scenes/{scn}/shots`)

| Field | What you put here |
|---|---|
| `shot_number` | Order within the scene. Required. |
| `description` | Plain English: what's in the frame — camera framing, setting, lighting, technical direction for image generation. |
| `subtitle` | **Viewer-facing narration** for this shot. This is the text burned onto the final video for viewers to read. Write it as first-person or third-person narrative that tells the story beat-by-beat. Distinct from `description` which is technical shot direction for the AI. |
| `image_prompt` | The actual visual prompt you'll send to image generation. Be specific — character trigger words, lighting, lens, mood. |
| `motion_prompt` | Camera move + motion for the animate step. "Slow push in, suit plates locking into place." |
| `camera_motion` | Optional shorthand: `"push in"`, `"orbit"`, `"static"`, etc. |
| `subtitle` | Viewer-facing narration burned onto the final video. Write as the story's narrative voice — this is what viewers read. |
| `duration_seconds` | Clip length when animated. Default 5. |
| `characters` | IDs of characters in this shot. |

## Worked example: "Put me in an Iron Man movie"

Your human says: *"Put me in an Iron Man movie — suit-up, launch, rooftop landing, the whole thing."*

You decide: this is a project because it asks for a sequence of movie beats. Cast `rigo`. Aspect `9:16`. ~30s. About 3 scenes, 1–3 shots each. Title: *Suit Up*.

You POST the project:

```json
{
  "title": "Suit Up",
  "description": "Rigo suits up in his workshop and steps out into the rain.",
  "aspect_ratio": "9:16",
  "duration_seconds": 30,
  "characters": ["rigo"]
}
```

Then your scenes — `1: INT. WORKSHOP - NIGHT`, `2: INT. WORKSHOP - SUIT ASSEMBLY`, `3: EXT. CITY ROOFTOP - RAIN`.

Then your shots — for scene 2: `shot 1: wide of Rigo on the assembly platform`, `shot 2: medium of chest plate locking in`, `shot 3: close on the helmet snapping shut, eyes glow blue`. Each gets an `image_prompt` and `motion_prompt`.

Then you stop, point your human at the Projects page, and say something like *"I drafted Suit Up — three scenes, seven shots. Take a look. Want to change any of the beats before I start generating?"* Iterate. Only when they approve the outline do you start hitting `/generate-image`.

---

## Consent before identity work

Before you do image-to-video, identity work, body/likeness generation, or any future LoRA training flow, confirm with your human that they own or have permission to use the image/person/likeness involved. Don't assume.

## Don'ts

- Don't open the ComfyUI browser UI. ComfyUI is the headless execution engine — you talk to Nemoflix's API, not Comfy directly.
- Don't generate images before showing the outline.
- Don't animate before showing the images.
- Don't ask your human to fill in fields. 

## Summary
You're the agent — you can draft the project, scenes, and shots in seconds, based off of a simple user prompt and maybe a few follow-up questions, compared to the user it would take them several minutes. So this is the advantage of using the agent. Follow the instructions in this SKILL.md, don't be afraid to ask questions, iterate with the user.
