"""
generate_cloudrun_token.py - Helper to format token.json for Cloud Run GOOGLE_TOKEN_JSON.

Outputs the minified, single-line stringified JSON required for the Cloud Run
environment variable GOOGLE_TOKEN_JSON.
"""

import os
import json
import sys

TOKEN_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "token.json")

def main():
    if not os.path.exists(TOKEN_PATH):
        print(f"Error: '{TOKEN_PATH}' not found. Please run 'python auth_server.py' to generate it first.")
        sys.exit(1)

    with open(TOKEN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Minify into single-line string
    minified = json.dumps(data, separators=(",", ":"))
    print("\n" + "=" * 60)
    print("  GOOGLE_TOKEN_JSON (Minified Single-Line for Cloud Run)")
    print("=" * 60 + "\n")
    print(minified)
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()

