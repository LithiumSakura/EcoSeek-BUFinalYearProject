"""
EcoSeek — Authentication Blueprint
Handles login, register, logout via Firebase Auth + Google OAuth.
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import firebase_admin
from firebase_admin import auth as firebase_auth
import re
import os

auth_bp = Blueprint("auth", __name__)

# ── Helpers ─────────────────────────────────────────────────────
def is_safe_username(username: str) -> bool:
    """Allow letters, digits, underscores, hyphens, 3-20 chars."""
    return bool(re.match(r"^[a-zA-Z0-9_\-]{3,20}$", username))

def _create_session(decoded: dict):
    """Populate Flask session from a decoded Firebase token."""
    session["user_id"]      = decoded["uid"]
    session["email"]        = decoded.get("email", "")
    session["display_name"] = decoded.get("name", decoded.get("display_name", "Explorer"))

def _upsert_leaderboard(user_id: str, display_name: str):
    """Ensure user exists in the SQL leaderboard table."""
    from database.sql_db import upsert_user
    upsert_user(user_id, display_name)

def _upsert_firestore(user_id: str, display_name: str, email: str):
    """Create Firestore user document if it doesn't exist yet."""
    import firebase_admin
    from firebase_admin import firestore
    db = firestore.client()
    user_ref = db.collection("users").document(user_id)
    if not user_ref.get().exists:
        user_ref.set({
            "display_name": display_name,
            "email": email,
            "total_xp": 0,
            "species_count": 0,
            "day_streak": 0,
            "badges": [],
        })


# ── Routes ───────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    data = request.get_json() or {}
    id_token = data.get("id_token") or request.form.get("id_token")
    if not id_token:
        return jsonify({"error": "No token provided"}), 400

    try:
        decoded = firebase_auth.verify_id_token(id_token)
        _create_session(decoded)
        _upsert_leaderboard(decoded["uid"], session["display_name"])
        return jsonify({"redirect": url_for("home")}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 401

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    data = request.get_json() or request.form
    username = data.get("username", "").strip()
    email    = data.get("email", "").strip()
    password = data.get("password", "")

    if not is_safe_username(username):
        return jsonify({"error": "Username must be 3-20 chars, letters/numbers only"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    try:
        # Create user in Firebase Auth
        user = firebase_auth.create_user(
            email=email,
            password=password,
            display_name=username
        )
        # Pre-create records so leaderboard and profile work immediately
        _upsert_leaderboard(user.uid, username)
        _upsert_firestore(user.uid, username, email)
        return jsonify({"uid": user.uid, "message": "Account created!"}), 201
    except firebase_admin.exceptions.FirebaseError as e:
        return jsonify({"error": str(e)}), 400

@auth_bp.route("/google-callback", methods=["POST"])
def google_callback():
    """Receive Google OAuth ID token from client, create session."""
    data = request.get_json() or {}
    id_token = data.get("id_token")
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        _create_session(decoded)
        _upsert_leaderboard(decoded["uid"], session["display_name"])
        _upsert_firestore(decoded["uid"], session["display_name"], session["email"])
        return jsonify({"redirect": url_for("home")}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 401

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))