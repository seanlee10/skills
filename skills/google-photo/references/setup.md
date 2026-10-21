# One-time Google Cloud setup

The skill talks to Google with your **own** OAuth client, in your own Google Cloud project.
An *OAuth client* is a small ID file (`client_secret.json`) that identifies "your app" to
Google, so that Google's own sign-in page can ask you whether this app may see the photos
you pick. You do this once per Google account; it takes about 10 minutes. The project does
not need a billing account.

## Before you start

- A Google account that owns the photos (a personal Gmail account works) and a browser.
- Optional, for steps 1–2 from a terminal: the
  [`gcloud` CLI](https://cloud.google.com/sdk/docs/install). After installing it, sign
  gcloud itself in once with `gcloud auth login` (any Google account you own; this is
  separate from the skill's own sign-in in step 6). Without gcloud, use the console links
  given in each step.
- A **project ID**. It must be unique across all of Google Cloud (not just your account),
  6–30 characters long, made of lowercase letters, digits and hyphens, starting with a
  letter and not ending with a hyphen, e.g. `my-photo-picker-2026`. If the ID is taken,
  pick another. The examples below use `my-photo-picker-2026`: replace it with yours
  everywhere, including in the console links.
- Where the skill lives, for the commands in steps 5–6 (`check`, `auth`): first ask your
  agent for the full path to `gphoto.py` in the installed skill, and use that in place of
  `<this skill's folder>/scripts/gphoto.py`. In a clone of the repository the folder is
  `skills/google-photo`. (Inside Claude Code the agent sees the folder as
  `${CLAUDE_SKILL_DIR}`; that variable is not set in your own terminal.)

## 1. Create a project

```sh
gcloud projects create my-photo-picker-2026
```

Or in the console: <https://console.cloud.google.com/projectcreate>.

## 2. Enable the Photos Picker API

```sh
gcloud services enable photospicker.googleapis.com --project=my-photo-picker-2026
```

Or in the console:
<https://console.cloud.google.com/apis/library/photospicker.googleapis.com?project=my-photo-picker-2026>
→ **Enable** (APIs & Services → Library → "Google Photos Picker API").

## 3. Consent screen (web console only)

There is no gcloud command for this with a personal account. Open (replace the id):

<https://console.cloud.google.com/auth/overview?project=my-photo-picker-2026>

1. **Google Auth Platform → Get started.**
2. App name (anything, e.g. "My photo picker") and user support email (yours).
3. Audience: **External**.
4. Contact email (yours); accept the policy; **Create**.
5. **Audience → Test users → Add users**
   (<https://console.cloud.google.com/auth/audience?project=my-photo-picker-2026>): add the
   Gmail address that owns the photos. Without this, sign-in fails with "Access blocked" /
   "has not completed the Google verification process".

Leave the app in **Testing**; you do not need to publish or verify it.

## 4. Desktop OAuth client (web console only)

Open: <https://console.cloud.google.com/auth/clients/create?project=my-photo-picker-2026>

1. Application type: **Desktop app**; any name.
2. **Create**, then **Download JSON**.

## 5. Put the client file in place

```sh
mkdir -p ~/.config/google-photo
chmod 700 ~/.config/google-photo
mv ~/Downloads/client_secret_*.json ~/.config/google-photo/client_secret.json
chmod 600 ~/.config/google-photo/client_secret.json
```

Or keep it elsewhere and set `GOOGLE_PHOTO_CLIENT_SECRET=/path/to/client_secret.json` in
the shell that starts your agent. The whole config folder can be moved with
`GOOGLE_PHOTO_CONFIG_DIR`. Do not paste the file's contents into a chat, and do not commit
it anywhere.

Then check it:

```sh
uv run <this skill's folder>/scripts/gphoto.py check
```

It should report `"client_secret":"present"`.

## 6. Sign in

```sh
uv run <this skill's folder>/scripts/gphoto.py auth
```

The browser opens Google's sign-in. Choose the account that owns the photos (the test user
from step 3). Google shows **"Google hasn't verified this app"**: that is your own app, so
choose **Continue**. Grant the Google Photos permission. The page then says you can close
it, and the command prints `{"status":"ok","signed_in":true}`. The *refresh token* (your saved
sign-in, so you do not have to log in for every command) is saved in
`~/.config/google-photo/token.json` (mode 0600, readable only by you). Only one permission is requested:
`photospicker.mediaitems.readonly` (see the items you pick, nothing else).

## Good to know

- **7-day sign-in.** Google issues refresh tokens that expire after 7 days for apps left in
  Testing status. When that happens a command fails with `AUTH_REQUIRED`: run
  `uv run <this skill's folder>/scripts/gphoto.py auth` again. (Publishing the app to "In production" removes the limit but may require Google's
  app verification; for personal use, signing in again weekly is simpler.)
- **"This app is blocked".** Signing in with gcloud's own client
  (`gcloud auth application-default login --scopes=...photospicker...`) is blocked by
  Google for this scope. That is why you create your own Desktop client above; the skill
  always uses that one.
- **Local only.** Sign-in uses a one-time listener on `127.0.0.1` and your browser, so it
  only works on your own computer. Over SSH, in a container or on headless Linux the
  skill refuses (`REMOTE_ENVIRONMENT_REFUSED`).
- **Revoke access** any time at <https://myaccount.google.com/permissions>, and delete
  `~/.config/google-photo/token.json`.

## What the picker can and cannot do

Checked live on 2026-10-21:

- The picker's search finds **named people** (Google's face groups; name them first in
  Google Photos under People), and also dates, places and things.
- Search results are grouped by day, each day with a **select-all checkbox**.
- At most **2,000 items per session**; use several sessions for more.
- The API returns capture time, type, file name, MIME type, dimensions, camera and video
  fps, but **no location, no people and no description**, so the skill cannot filter by
  place or check who is in a photo.
