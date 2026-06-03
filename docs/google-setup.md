# Google API Setup

Step-by-step instructions to configure Google API access for Liminal Drive Analytics. This covers personal Google Drive access using OAuth. For org-wide Workspace deployment, see the note at the bottom.

---

## Step 1 — Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Click the project dropdown at the top → **New Project**.
3. Name it `liminal-drive-analytics` (or anything you like).
4. Click **Create** and wait for it to provision (~30 seconds).
5. Make sure the new project is selected in the dropdown before continuing.

---

## Step 2 — Enable the Required APIs

You need to enable three APIs for this project.

1. In the left sidebar, go to **APIs & Services → Library**.
2. Search for and enable each of the following:

| API | What it's used for |
|---|---|
| **Google Drive API** | List files, get metadata |
| **Google Docs API** | Read document content to extract links |
| **Drive Activity API** | Get view, edit, and comment events |

For each: click the API name → click **Enable**.

---

## Step 3 — Configure the OAuth Consent Screen

This is required before you can create credentials.

1. Go to **APIs & Services → OAuth consent screen**.
2. Select **External** (even for personal use — Internal requires a Workspace org).
3. Fill in the required fields:
   - **App name**: `Liminal Drive Analytics`
   - **User support email**: your Gmail address
   - **Developer contact email**: your Gmail address
4. Click **Save and Continue** through the Scopes step (you'll add scopes in code, not here).
5. On the **Test users** step, click **Add users** and add your own Gmail address.
6. Click **Save and Continue**, then **Back to Dashboard**.

> **Note:** While the app is in "Testing" mode, only the test users you add can authenticate. This is fine for personal use — you don't need to publish the app.

---

## Step 4 — Create OAuth Credentials

1. Go to **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth client ID**.
3. Application type: **Desktop app**.
4. Name: `liminal-drive-analytics-local`.
5. Click **Create**.
6. Click **Download JSON** on the confirmation dialog.
7. Save the downloaded file as `credentials.json` in the root of this project.

> `credentials.json` contains your client secret. It is gitignored — never commit it.

---

## Step 5 — Install Dependencies

```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

Or if using the project requirements file:

```bash
pip install -r requirements.txt
```

---

## Step 6 — Authenticate

Run the auth script. It will open a browser window asking you to sign in with your Google account and grant the requested permissions.

```bash
python src/auth.py
```

On first run:
1. A browser window opens.
2. Sign in with the Google account you added as a test user.
3. You'll see a warning that the app is unverified — click **Advanced → Go to Liminal Drive Analytics (unsafe)**.
4. Grant the requested permissions.
5. The browser will redirect to `localhost` and you can close it.

A `token.json` file is saved locally. This stores your access and refresh tokens so you don't need to re-authenticate on every run. It is gitignored.

---

## Step 7 — Verify Access

```bash
python src/auth.py --verify
```

This should print a list of your 10 most recently modified Google Docs, confirming that authentication and API access are working.

---

## Scopes Granted

The app requests the minimum scopes needed:

| Scope | Why |
|---|---|
| `drive.readonly` | List files and read metadata |
| `documents.readonly` | Read document body to extract links |
| `drive.activity.readonly` | Read view/edit/comment events |

All scopes are read-only. The app never writes to Drive.

---

## Revoking Access

If you want to revoke access at any time:

1. Go to [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
2. Find **Liminal Drive Analytics** and click **Remove Access**.
3. Delete `token.json` from the project directory.

---

## For Org-Wide Workspace Deployment

Personal OAuth is sufficient for testing. For production deployment across an organization:

1. A **Google Workspace Admin** creates a Service Account in the Cloud project.
2. The admin grants **Domain-Wide Delegation** to the service account, authorizing the same three scopes.
3. The indexer uses the service account (no user interaction required) and can access Drive activity across all users in the org.
4. The consent screen app type changes to **Internal** so only org users can authenticate.

This requires Workspace Admin access — flag this when you're ready to move from personal testing to org deployment.
