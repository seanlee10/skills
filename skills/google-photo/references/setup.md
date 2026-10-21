# One-time Google Cloud setup

The skill talks to Google with your **own** OAuth client, in your own Google Cloud project.
You do this once per Google account; it takes about 10 minutes. The project does not need
a billing account.

You need: a Google account that owns the photos (a personal Gmail account works), a browser,
and optionally the [`gcloud` CLI](https://cloud.google.com/sdk/docs/install) for steps 1–2.

## 1. Create a project

With gcloud (pick any unused id, lowercase letters, digits and dashes, e.g.
`my-photo-picker-2026`):

```sh
gcloud auth login                      # signs gcloud itself in; any account you own
gcloud projects create my-photo-picker-2026
```

Or in the console: <https://console.cloud.google.com/projectcreate>.

## 2. Enable the Photos Picker API

```sh
gcloud services enable photospicker.googleapis.com --project=my-photo-picker-2026
```

Or in the console: APIs & Services → Library → "Google Photos Picker API" → Enable.

## 3. Consent screen (web console only)

There is no gcloud command for this with a personal account. Open (replace the id):

<https://console.cloud.google.com/auth/overview?project=my-photo-picker-2026>

1. **Google Auth Platform → Get started.**
2. App name (anything, e.g. "My photo picker") and user support email (yours).
3. Audience: **External**.
4. Contact email (yours); accept the policy; **Create**.
5. **Audience → Test users → Add users**: add the Gmail address that owns the photos.
   Without this, sign-in fails with "Access blocked" / "has not completed the Google
   verification process".

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

Then `gphoto.py check` should report `"client_secret":"present"`.

## 6. Sign in

```sh
uv run <this skill's folder>/scripts/gphoto.py auth
```

The browser opens Google's sign-in. Choose the account that owns the photos (the test user
from step 3). Google shows **"Google hasn't verified this app"**: that is your own app, so
choose **Continue**. Grant the Google Photos permission. The page then says you can close
it, and the command prints `{"status":"ok","signed_in":true}`. The refresh token is saved
in `~/.config/google-photo/token.json` (mode 0600). Only one permission is requested:
`photospicker.mediaitems.readonly` (see the items you pick, nothing else).

## Good to know

- **7-day sign-in.** Google issues refresh tokens that expire after 7 days for apps left in
  Testing status. When that happens a command fails with `AUTH_REQUIRED`: run `auth`
  again. (Publishing the app to "In production" removes the limit but may require Google's
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
