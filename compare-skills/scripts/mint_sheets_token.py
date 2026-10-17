#!/usr/bin/env python3
"""One-time sign-in: save an OAuth token that can create and write Google Sheets, for the
optional Sheet output of build_comparison_sheet.py.

    python3 mint_sheets_token.py [--client-secrets <file>] [--token <file>] [--force]

Run it once, in a terminal, on a machine whose browser you can click in. It opens Google's
consent page and, on approval, writes the token file (default
~/.claude/google-oauth/sheets_token.json; build_comparison_sheet.py reads the same path, or
the COMPARE_SKILLS_SHEETS_TOKEN variable). The client file is a desktop OAuth client you
download from your own Google Cloud project, with the Google Sheets API switched on (default
~/.claude/google-oauth/credentials.json).

The scope is narrow on purpose: `spreadsheets` can create a spreadsheet and edit the ones
this account can open. It cannot read the rest of Drive or change sharing. Needs
google-auth-oauthlib. Prints metadata only, never a token value.
Exit 0 ok; 2 on a missing client file or an existing token without --force.
"""
import argparse
import json
import os
import sys

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DEFAULT_CLIENT = "~/.claude/google-oauth/credentials.json"
DEFAULT_TOKEN = "~/.claude/google-oauth/sheets_token.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--client-secrets", default=DEFAULT_CLIENT, help="desktop OAuth client JSON")
    ap.add_argument("--token", default=os.environ.get("COMPARE_SKILLS_SHEETS_TOKEN", DEFAULT_TOKEN),
                    help="where to write the token")
    ap.add_argument("--force", action="store_true", help="replace an existing token")
    args = ap.parse_args(argv)
    client = os.path.expanduser(args.client_secrets)
    token_path = os.path.expanduser(args.token)
    if not os.path.isfile(client):
        print(f"no OAuth client file at {client}; pass --client-secrets", file=sys.stderr)
        return 2
    if os.path.isfile(token_path) and not args.force:
        print(f"{token_path} already exists; pass --force to replace it", file=sys.stderr)
        return 2
    from google_auth_oauthlib.flow import InstalledAppFlow
    creds = InstalledAppFlow.from_client_secrets_file(client, SCOPES).run_local_server(port=0)
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # never readable by others
    with os.fdopen(fd, "w") as handle:
        handle.write(creds.to_json())
    os.chmod(token_path, 0o600)  # also tightens a file that already existed (--force)
    written = json.load(open(token_path))
    print(f"wrote {token_path}")
    print(f"granted scopes: {written.get('scopes')}")
    print(f"refresh token present: {bool(written.get('refresh_token'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
