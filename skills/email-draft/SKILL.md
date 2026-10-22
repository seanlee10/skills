---
name: email-draft
description: "Draft a customer or partner email (meeting recap, follow-up, next steps, support reply) in a consistent business style and put it on the macOS clipboard as rich text that pastes cleanly into Gmail. Use whenever the user asks to write, draft or rework an email, or a recap of a call to send to someone."
---

# email-draft

Terminal markdown does not paste into Gmail: `**`, `- [ ]`, backslash line breaks and
backticks arrive as literal characters. So the deliverable is an HTML file copied to the
clipboard as rich text, not markdown in the chat. Write the email in the language the user
asks for (default: the language of their request).

## Workflow

1. Write the email body as HTML in a temporary file (the agent's scratchpad if it has one,
   e.g. `email-<slug>.html`). Body only: no subject line, no notes to the user.
2. Copy it to the clipboard as rich text (see [Run](#run)).
3. Reply with:
   - `Subject:` line on its own (plain text, so the user can copy it separately).
   - A short plain-text preview of the email (headings and bullets readable, no markdown
     emphasis needed).
   - "Copied to clipboard as rich text, paste into Gmail with Cmd+V."
   - Any notes for the user (assumptions, things to verify) **after** the preview, under a
     clear separator. Never inside the email.

To rework an email the user pastes in, follow the same workflow on the revised text.

## Run

```sh
<this skill's folder>/scripts/copy-html.sh email.html
```

In Claude Code the skill folder is `${CLAUDE_SKILL_DIR}`:

```sh
"${CLAUDE_SKILL_DIR}/scripts/copy-html.sh" /path/to/email-recap.html
```

The script needs macOS (`osascript` with AppKit). It puts the HTML on the clipboard as
`public.html` with a plain-text fallback and prints `copied N chars`. On other systems, or
if it fails, give the user the HTML file's full path instead and say the clipboard step was
skipped; do not paste markdown as a substitute.

## Writing style

- Greeting with the recipients' first names, two names joined with "and" (`Hi Alex and
  Jordan,`). Warm one-line opener: "Thanks for your time today! Here's a quick recap of our
  discussion and the suggested next steps ahead of next week's session."
- Numbered section headers in bold Title Case, every word capitalised: **1. What We
  Discussed**, **2. Next Steps for Your Team**, **3. Next Steps from My Side**. Recaps use
  the discussed / your team / my side trio; support replies use one section per product or
  question, then a recommendation.
- Corrections stay soft: "I'd like to clarify a couple of points", not "I need to correct".
  Apologise once, briefly, then move on.
- Polite, slightly formal register: "Please note that…", "without further customization",
  "the newly configured provider". Avoid casual shorthand ("this route"); prefer "additional
  headers" over "extra headers".
- One requirement per sentence. Split "depends on X, and your gateway would need Y" into
  "This approach also depends on X. Your gateway must also support Y."
- Bold UI labels, product names and key requirements (**Settings → Integrations**, **Allow
  external access**). Numbered steps for click-paths, each step one action starting with a
  verb.
- Inside a section, bold Title Case sub-headers on their own line (**Evaluation Scope**),
  followed by short paragraphs of one to three sentences. Prefer several short paragraphs
  over one dense numbered paragraph.
- Turn compound "whether A, whether B, whether C" sentences into a bullet list under a
  lead-in sentence.
- Bullets are full sentences ending with a period. Action items lead with a bold verb
  phrase: "**Create a test dataset** with a manageable subset of around 50–100 cases."
- No checkboxes. Actions are plain bullets.
- Explain the purpose, not just the step ("so that both input and output checks are
  included").
- Typography: en dash for ranges and list descriptions (`50–100`, `name – description`),
  `→` for flows.
- Never wrap the email in `---` separators or append notes after the sign-off.
- End with an offer of help, then a forward-looking line ("Looking forward to seeing the
  initial results next week!"), then `Best,` and the sender's first name on separate lines.
  Take the name from the conversation or the user's profile; if it is unknown, ask once.
- Customer-facing from the first draft: no internal repository names, ticket numbers,
  internal tool names or other internal details.

## HTML rules

Keep the markup minimal so Gmail applies its own font:

- `<p>` for paragraphs and headers; `<b>` for bold; `<ul>`/`<ol>` with `<li>` for lists
  (nest a `<ul>` inside an `<li>` for sub-bullets).
- Section and sub-headers are `<p><b>…</b></p>`, not `<h1>`–`<h3>` (Gmail renders those
  oversized).
- Identifiers such as dataset or package names:
  `<span style="font-family:monospace">…</span>`.
- No `<style>` blocks, classes, fonts, colors or `<html>`/`<body>` wrappers.
- Sign-off: `<p>Best,<br>Name</p>`.

Skeleton:

```html
<p>Hi Alex and Jordan,</p>
<p>Thanks for your time today! Here's a quick recap of our discussion and the suggested next steps ahead of next week's session.</p>
<p><b>1. What We Discussed</b></p>
<p><b>Evaluation Scope</b></p>
<p>Your assistant sits between an input check and an output check. The evaluation covers the entire workflow to identify:</p>
<ul>
  <li>Whether unexpected inputs can bypass the input check.</li>
</ul>
<p><b>2. Next Steps for Your Team</b></p>
<ul>
  <li><b>Select a test dataset.</b> Some good starting points include:
    <ul><li><span style="font-family:monospace">support-tickets-sample</span> – Real support questions across categories.</li></ul>
  </li>
</ul>
<p><b>3. Next Steps from My Side</b></p>
<p>Please let me know if you have any questions in the meantime. Looking forward to seeing the initial results next week!</p>
<p>Best,<br>Name</p>
```
