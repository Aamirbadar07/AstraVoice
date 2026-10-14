"""
auth_server.py – One-time OAuth 2.0 helper.
Run this once to generate token.json, then stop it and use api_server.py.
"""

import os
from flask import Flask, redirect, request
from google_auth_oauthlib.flow import Flow
from dotenv import load_dotenv

load_dotenv()

# Allow OAuth over plain HTTP for localhost development
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

app = Flask(__name__)

CLIENT_CONFIG = {
    "web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")],
    }
}

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")


def make_flow():
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    return flow


@app.route("/")
def index():
    flow = make_flow()
    auth_url, _ = flow.authorization_url(prompt="consent")
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>AstraVoice – Authorize Calendar</title>
        <style>
            body {{ font-family: sans-serif; display: flex; align-items: center;
                   justify-content: center; min-height: 100vh; margin: 0;
                   background: #0f172a; color: #e2e8f0; }}
            .card {{ background: #1e293b; padding: 2rem 3rem; border-radius: 12px;
                     text-align: center; }}
            h1 {{ color: #3b82f6; }}
            a.btn {{ display: inline-block; margin-top: 1.5rem; padding: .75rem 1.5rem;
                     background: #3b82f6; color: #fff; border-radius: 8px;
                     text-decoration: none; font-weight: 600; }}
            a.btn:hover {{ background: #2563eb; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>AI Calling Assistant</h1>
            <p>AstraVoice needs access to your Google Calendar to check availability and book meetings.</p>
            <a class="btn" href="{auth_url}">Click here to Authorize Google Calendar</a>
        </div>
    </body>
    </html>
    """


@app.route("/auth/callback")
def callback():
    flow = make_flow()
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials

    import json
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }
    with open("token.json", "w") as f:
        json.dump(token_data, f, indent=2)

    print("✅ token.json written. Press Ctrl+C to stop the auth server.")
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>AstraVoice – Authorized!</title>
        <style>
            body { font-family: sans-serif; display: flex; align-items: center;
                   justify-content: center; min-height: 100vh; margin: 0;
                   background: #0f172a; color: #e2e8f0; }
            .card { background: #1e293b; padding: 2rem 3rem; border-radius: 12px;
                     text-align: center; }
            h1 { color: #10b981; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>✅ Authorization Successful!</h1>
            <p>token.json has been saved. You can now stop this server (Ctrl+C)
            and start the main API bridge:</p>
            <pre style="background:#0f172a;padding:1rem;border-radius:8px;text-align:left">
python3 api_server.py
            </pre>
        </div>
    </body>
    </html>
    """


if __name__ == "__main__":
    print("🔐 Auth server running on http://localhost:8000")
    print("   Open that URL in Chrome to authorize Google Calendar.")
    app.run(port=8000, debug=False)
