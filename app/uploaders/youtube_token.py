#!/usr/bin/env python3
"""
app.uploaders.youtube_token — Create and verify the YouTube OAuth token.

Two subcommands:

    python -m app.uploaders.youtube_token generate
        Opens a Google login in the browser, asks for the YouTube scopes this
        project needs, and writes .credentials/youtube_token.json. Run it the
        first time, or whenever the token breaks or you want to switch account.

    python -m app.uploaders.youtube_token generate --manual
        Same, for machines without a browser (Colab/Kaggle): prints a login
        link and asks you to paste back the URL the browser was redirected to.

    python -m app.uploaders.youtube_token verify
        Refreshes the stored token and prints the channel it resolves to, so you
        can confirm the credentials still work without uploading anything.

The client-secret file comes from Google Cloud Console:
  APIs & Services -> Credentials -> OAuth client ID -> Desktop app -> Download JSON
Rename the download to client_secret.json and put it in .credentials/.

Treat .credentials/youtube_token.json like a password — never commit it.
"""

import argparse
import os
import sys

# Permissions requested from the Google/YouTube account:
#   youtube.upload   -> upload videos
#   youtube.readonly -> read channel/video data, e.g. the existing schedule
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

CREDENTIALS_DIR = ".credentials"
CLIENT_SECRET_FILE = os.path.join(CREDENTIALS_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(CREDENTIALS_DIR, "youtube_token.json")


def generate_token(client_secret_file: str = CLIENT_SECRET_FILE,
                   token_file: str = TOKEN_FILE) -> str:
    """Run the desktop OAuth flow and write the token file."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(client_secret_file):
        raise FileNotFoundError(
            f"{client_secret_file} not found. Download the OAuth client ID JSON "
            f"from Google Cloud, rename it to client_secret.json and place it in "
            f"{CREDENTIALS_DIR}/"
        )

    os.makedirs(os.path.dirname(token_file) or ".", exist_ok=True)

    flow = InstalledAppFlow.from_client_secrets_file(
        client_secret_file, scopes=YOUTUBE_SCOPES
    )

    # port=0            -> let Python pick a free port for the local callback.
    # access_type       -> request a refresh_token so the access token can be
    #                      renewed without logging in again.
    # prompt="consent"  -> force the consent screen so a refresh_token is issued.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    with open(token_file, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print(f"✅ Token created: {token_file}")
    return token_file


def generate_token_manual(client_secret_file: str = CLIENT_SECRET_FILE,
                          token_file: str = TOKEN_FILE,
                          pasted_url: str | None = None) -> str:
    """
    Run the OAuth flow without a local browser (Colab, Kaggle, SSH).

    Open the printed link, approve access, and the browser is sent to a
    ``http://localhost`` page that fails to load — that is expected. Copy the
    full address from the address bar and paste it back. The ``code`` in that
    URL is exchanged for a token with a refresh_token.
    """
    from urllib.parse import parse_qs, urlparse

    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(client_secret_file):
        raise FileNotFoundError(
            f"{client_secret_file} not found. Download the OAuth client ID JSON "
            "(Desktop app) from Google Cloud and put it there."
        )

    os.makedirs(os.path.dirname(token_file) or ".", exist_ok=True)

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, scopes=YOUTUBE_SCOPES)
    flow.redirect_uri = "http://localhost:1"
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

    if pasted_url is None:
        print("1. Open this link and approve access with the channel's Google account:\n")
        print(f"   {auth_url}\n")
        print("2. The browser then shows 'This site can't be reached' — that is expected.")
        print("   Copy the FULL address from the address bar and paste it below.\n")
        pasted_url = input("Paste the redirected URL: ").strip()

    code = parse_qs(urlparse(pasted_url).query).get("code", [pasted_url])[0]
    flow.fetch_token(code=code)

    with open(token_file, "w", encoding="utf-8") as f:
        f.write(flow.credentials.to_json())

    print(f"✅ Token created: {token_file}")
    return token_file


def verify_token(token_file: str = TOKEN_FILE) -> None:
    """Refresh the stored token and print the channel it belongs to."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(token_file, YOUTUBE_SCOPES)

    print(f"Token valid      : {creds.valid}")
    print(f"Token expired    : {creds.expired}")
    print(f"Has refresh_token: {bool(creds.refresh_token)}")
    print(f"Expiry           : {creds.expiry}")

    if not creds.refresh_token:
        raise RuntimeError(
            "No refresh_token present. Re-run `generate` (it uses "
            "prompt='consent' and access_type='offline')."
        )

    print("Refreshing the token...")
    creds.refresh(Request())
    with open(token_file, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print(f"Refresh OK. Valid: {creds.valid}, new expiry: {creds.expiry}")

    youtube = build("youtube", "v3", credentials=creds)
    items = youtube.channels().list(part="snippet,contentDetails", mine=True).execute().get(
        "items", []
    )
    if not items:
        print("The token is valid but no YouTube channel was found.")
        return

    channel = items[0]
    print(f"Channel detected : {channel['snippet']['title']}")
    print(f"Channel ID       : {channel['id']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Create or verify the YouTube OAuth token.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "command", choices=["generate", "verify"],
        help="'generate' runs the OAuth login; 'verify' refreshes and checks the token.",
    )
    p.add_argument("--token-file", default=TOKEN_FILE,
                   help="Path of the YouTube OAuth token JSON.")
    p.add_argument("--client-secret", default=CLIENT_SECRET_FILE,
                   help="Path of the Google OAuth client-secret JSON (generate only).")
    p.add_argument("--manual", action="store_true",
                   help="No local browser (Colab/Kaggle/SSH): print a login link and "
                        "paste the redirected URL back (generate only).")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "generate":
        if args.manual:
            generate_token_manual(args.client_secret, args.token_file)
        else:
            generate_token(args.client_secret, args.token_file)
        return

    if not os.path.exists(args.token_file):
        print(f"❌ Token not found: {args.token_file}")
        sys.exit(1)
    verify_token(args.token_file)


if __name__ == "__main__":
    main()
