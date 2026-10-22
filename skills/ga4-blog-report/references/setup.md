# Setup

One-time setup, about 10 minutes. Steps 1–4 are manual: they happen in the Google Cloud
console and in GA4 Admin, and no command in this skill can do them for you. You need to be
able to create a service account in a Google Cloud project, and to be an **Administrator**
of the GA4 property (to add a user to it).

The skill reads GA4 as a **service account**: a robot Google account that has its own key
and only the access you give it. Your own Google sign-in is not used.

## 1. Enable the Google Analytics Data API

1. Open the [Google Cloud console](https://console.cloud.google.com/) and pick a project in
   the project selector, or create a new one (**New project**). No billing account is
   needed.
2. Open [APIs & Services → Library → Google Analytics Data API](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com)
   with that project selected and press **Enable**.

If you use the gcloud CLI, the same step is:

```sh
gcloud services enable analyticsdata.googleapis.com --project <project ID>
```

Enable it in the project the service account belongs to (step 2). Enabling it in another
project does not help, and the report fails with `API_DISABLED`.

## 2. Create a service account and a JSON key

1. In the same project, open **IAM & Admin → Service Accounts** and press **Create service
   account**. Any name works, e.g. `ga4-blog-report`. Skip the optional role and user
   steps: the service account needs no Cloud role.
2. Open the new service account → **Keys** → **Add key → Create new key** → **JSON**. The
   browser downloads a `.json` file.
3. Note the service account's email (`…@<project>.iam.gserviceaccount.com`).

The key file works like a password for this service account. Keep it out of chats,
repositories and shared folders. If your organization blocks key creation
(`iam.disableServiceAccountKeyCreation`), ask an administrator for an exception for this
project.

## 3. Give the service account read access in GA4

1. In [Google Analytics](https://analytics.google.com/), open **Admin** (gear icon) and
   select the property.
2. **Property → Property access management** → **+** → **Add users**.
3. Enter the service account's email, choose the role **Viewer**, uncheck **Notify new
   users by email**, and press **Add**.

Viewer is enough: the skill only reads reports.

## 4. Find the property ID

In **Admin → Property → Property details**, copy the **Property ID**: digits only, e.g.
`123456789`. It is not the measurement ID `G-XXXXXXXXXX` of the web data stream. The ID
also appears in GA4 page URLs as `…/a<account ID>p<property ID>/…`.

## 5. Register the key and property

Ask the agent to configure the skill with the key file's path and the property ID, or run
it yourself:

```sh
uv run <skill folder>/scripts/ga4_report.py configure --key ~/Downloads/<key file>.json --property 123456789
```

`configure` checks that the file is a service account key, copies it to
`~/.config/ga4-blog-report/service-account.json` with mode 600, stores the property ID in
`settings.json` next to it, and prints the service account's email. It does not contact
Google; the first `report` does. After that works, delete the downloaded key file.

To switch to another property, run `configure` again with the new `--property`. To remove
the skill's access, delete `~/.config/ga4-blog-report/`, then delete the key in the Cloud
console (step 2) and remove the user in GA4 (step 3).

## Why not my own Google sign-in?

gcloud's application default credentials (`gcloud auth application-default login`) carry
only Cloud scopes and are refused with `ACCESS_TOKEN_SCOPE_INSUFFICIENT`. Requesting the
Analytics scope through gcloud's built-in sign-in app ends in "This app is blocked",
because Google does not grant that app sensitive scopes. A service account with Viewer
access avoids both, and you can revoke it at any time.
