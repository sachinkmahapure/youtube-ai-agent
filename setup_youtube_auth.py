"""
setup_youtube_auth.py
----------------------
One-time helper to authorise the agent to upload to your YouTube channel.

Steps:
  1. Download client_secrets.json from Google Cloud Console
     (APIs & Services → Credentials → OAuth 2.0 Client ID → Desktop App → Download)
  2. Place it at config/client_secrets.json
  3. Run: python setup_youtube_auth.py
  4. Authorise in the browser that opens
  5. Credentials are saved to config/youtube_credentials.json

For GitHub Actions:
  Copy the contents of config/youtube_credentials.json into the
  GitHub Secret named YOUTUBE_CREDENTIALS.
"""
from __future__ import annotations

# ── Path fix ─────────────────────────────────────────────────────────────────
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ─────────────────────────────────────────────────────────────────────────────

import pickle
from pathlib import Path

CLIENT_SECRETS = "config/client_secrets.json"
CREDENTIALS_FILE = "config/youtube_credentials.json"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def main() -> None:
    if not Path(CLIENT_SECRETS).exists():
        print(f"❌  {CLIENT_SECRETS} not found.")
        print(
            "   Download it from Google Cloud Console:\n"
            "   APIs & Services → Credentials → OAuth 2.0 Client ID → Desktop → Download JSON\n"
            f"   Then save it as {CLIENT_SECRETS}"
        )
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    print("🔐  Opening browser for YouTube authorisation…")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
    creds = flow.run_local_server(port=0)

    Path(CREDENTIALS_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(CREDENTIALS_FILE, "wb") as fh:
        pickle.dump(creds, fh)

    print(f"\n✅  Credentials saved to {CREDENTIALS_FILE}")

    # Quick sanity check — print connected channel name
    youtube = build("youtube", "v3", credentials=creds)
    resp = youtube.channels().list(part="snippet", mine=True).execute()
    if resp.get("items"):
        name = resp["items"][0]["snippet"]["title"]
        print(f"🎬  Connected channel: {name}")
    else:
        print("⚠️   No YouTube channel found on this Google account.")

    print(
        "\nNext steps:\n"
        "  1. Test upload:  python main.py run --topic 'Test' --days 1 --format short\n"
        f"  2. GitHub CI:    copy {CREDENTIALS_FILE} contents → secret YOUTUBE_CREDENTIALS"
    )


if __name__ == "__main__":
    main()
