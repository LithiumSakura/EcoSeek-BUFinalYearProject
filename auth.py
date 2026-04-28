"""
EcoSeek — Authentication Blueprint
Handles login, register, logout via Firebase Auth + Google OAuth.
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import firebase_admin
from firebase_admin import auth as firebase_auth
import bcrypt
import re

auth_bp = Blueprint("auth", __name__)


# ── Helper ───────────────────────────────────────────────────────
def is_safe_username(username: str) -> bool:
    """Allow letters, digits, underscores, hyphens, 3-20 chars."""
    return bool(re.match(r"^[a-zA-Z0-9_\-]{3,20}$", username))


# ── Routes ───────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    # --- Email/password login (Firebase verifies on client, we verify token) ---
    id_token = request.form.get("id_token") or request.json.get("id_token")
    if not id_token:
        return jsonify({"error": "No token provided"}), 400

    try:
        decoded = firebase_auth.verify_id_token(id_token)
        session["user_id"] = decoded["uid"]
        session["email"] = decoded.get("email", "")
        session["display_name"] = decoded.get("name", "Explorer")
        return jsonify({"redirect": url_for("home")}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 401


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    data = request.get_json() or request.form
    username = data.get("username", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not is_safe_username(username):
        return jsonify({"error": "Username must be 3-20 chars, letters/numbers only"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    try:
        # Create user in Firebase Auth
        user = firebase_auth.create_user(email=email, password=password, display_name=username)
        return jsonify({"uid": user.uid, "message": "Account created!"}), 201
    except firebase_admin.exceptions.FirebaseError as e:
        return jsonify({"error": str(e)}), 400


@auth_bp.route("/google-callback", methods=["POST"])
def google_callback():
    """Receive Google OAuth ID token from client, create session."""
    id_token = request.json.get("id_token")
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        session["user_id"] = decoded["uid"]
        session["email"] = decoded.get("email", "")
        session["display_name"] = decoded.get("name", "Explorer")
        return jsonify({"redirect": url_for("home")}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 401


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))
