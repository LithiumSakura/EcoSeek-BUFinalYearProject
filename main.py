"""
EcoSeek — Main Flask Application
Entry point for Google App Engine.
"""

import os

# ── Load secrets ───────────────────────────────────────────────────────────────
# Locally: read from .env file (never committed)
# On App Engine: fetch from Google Cloud Secret Manager
# ──────────────────────────────────────────────────────────────────────────────
def _load_secrets():
    if os.environ.get("GAE_ENV"):
        # Running on App Engine — fetch from Secret Manager
        try:
            from google.cloud import secretmanager
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "ecoseek-buproject-f015d")
            client = secretmanager.SecretManagerServiceClient()

            def _get(name):
                resource = f"projects/{project_id}/secrets/{name}/versions/latest"
                return client.access_secret_version(request={"name": resource}).payload.data.decode("utf-8")

            os.environ.setdefault("SECRET_KEY",      _get("ECOSEEK_SECRET_KEY"))
            os.environ.setdefault("VISION_API_KEY",  _get("ECOSEEK_VISION_API_KEY"))
            os.environ.setdefault("ANTHROPIC_API_KEY", _get("ECOSEEK_ANTHROPIC_API_KEY"))
        except Exception as e:
            print(f"WARNING: Could not load secrets from Secret Manager: {e}")
    else:
        # Running locally — load from .env
        from dotenv import load_dotenv
        load_dotenv()

_load_secrets()

# ── Firebase init ──────────────────────────────────────────────────────────────
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "firebase-key.json")
    if os.path.exists(key_path):
        cred = credentials.Certificate(key_path)
    else:
        cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred, {
        "projectId": os.environ.get("GOOGLE_CLOUD_PROJECT", "ecoseek-buproject-f015d")
    })

db = firestore.client()

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from functools import wraps

from auth import auth_bp
from api import api_bp
from database.sql_db import init_db, get_user_rank
from scoring import get_level

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-only-not-for-production")

app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(api_bp,  url_prefix="/api")

with app.app_context():
    init_db()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("home"))
    return render_template("index.html")


@app.route("/home")
@login_required
def home():
    user_id = session["user_id"]
    user_doc = db.collection("users").document(user_id).get()
    user_data = user_doc.to_dict() if user_doc.exists else {}
    user_data.setdefault("display_name", session.get("display_name", "Explorer"))
    return render_template("home.html", user=user_data)


@app.route("/camera")
@login_required
def camera():
    return render_template("camera.html")


@app.route("/leaderboard")
@login_required
def leaderboard():
    return render_template("leaderboard.html")


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", user_id=session["user_id"])


@app.route("/api/level")
@login_required
def api_level():
    xp = request.args.get("xp", 0, type=int)
    return jsonify(get_level(xp))


@app.route("/api/profile/<user_id>")
@login_required
def api_profile(user_id):
    if session["user_id"] != user_id:
        return jsonify({"error": "Forbidden"}), 403
    user_doc = db.collection("users").document(user_id).get()
    user_data = user_doc.to_dict() if user_doc.exists else {}
    rank = get_user_rank(user_id)
    total_xp = user_data.get("total_xp", user_data.get("total_points", 0))
    level_info = get_level(total_xp)
    return jsonify({
        "display_name":  user_data.get("display_name", session.get("display_name", "Explorer")),
        "photo_url":     user_data.get("photo_url", ""),
        "total_points":  total_xp,
        "species_count": user_data.get("species_count", 0),
        "streak_days":   user_data.get("day_streak", user_data.get("streak_days", 0)),
        "badges":        user_data.get("badges", []),
        "insect_count":  user_data.get("insect_count", 0),
        "plant_count":   user_data.get("plant_count", 0),
        "bird_count":    user_data.get("bird_count", 0),
        "animal_count":  user_data.get("animal_count", 0),
        "rank":          rank,
        **level_info
    })


@app.route("/_ah/health")
def health():
    return "OK", 200


application = app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=True)