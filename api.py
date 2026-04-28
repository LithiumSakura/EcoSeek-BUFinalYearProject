"""
EcoSeek — REST API Blueprint
All /api/* endpoints. Returns JSON.
"""

import firebase_admin
from firebase_admin import credentials, firestore
import os

if not firebase_admin._apps:
    key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "firebase-key.json")
    if os.path.exists(key_path):
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred, {
            "projectId": os.environ.get("GOOGLE_CLOUD_PROJECT", "ecoseek-individualproject")
        })

db = firestore.client()

from flask import Blueprint, request, jsonify, session
from functools import wraps
from firebase_admin import firestore
import requests
import os
from datetime import datetime, timezone

from database.sql_db import get_db_connection
from scoring import calculate_points

api_bp = Blueprint("api", __name__)
def get_db():
    return firestore.client()

VISION_API_KEY = os.environ.get("VISION_API_KEY", "")
VISION_URL = "https://vision.googleapis.com/v1/images:annotate"


# ── Auth guard ───────────────────────────────────────────────────
def api_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Unauthorised"}), 401
        return f(*args, **kwargs)
    return decorated


# ── /api/identify  ───────────────────────────────────────────────
@api_bp.route("/identify", methods=["POST"])
@api_login_required
def identify():
    """
    Accepts a base64 image, calls Google Vision API,
    returns species name + info.
    """
    data = request.get_json()
    image_b64 = data.get("image_b64")
    if not image_b64:
        return jsonify({"error": "No image provided"}), 400

    payload = {
        "requests": [{
            "image": {"content": image_b64},
            "features": [
                {"type": "LABEL_DETECTION", "maxResults": 10},
                {"type": "WEB_DETECTION", "maxResults": 5}
            ]
        }]
    }

    resp = requests.post(
        VISION_URL,
        params={"key": VISION_API_KEY},
        json=payload,
        timeout=10
    )
    if not resp.ok:
        return jsonify({"error": "Vision API error"}), 502

    vision_data = resp.json()["responses"][0]
    labels = [l["description"] for l in vision_data.get("labelAnnotations", [])]
    web_entities = [e["description"] for e in
                    vision_data.get("webDetection", {}).get("webEntities", [])
                    if e.get("score", 0) > 0.5]

    # Best guess at species
    species = web_entities[0] if web_entities else (labels[0] if labels else "Unknown")
    category = _guess_category(labels)

    return jsonify({
        "species": species,
        "category": category,
        "labels": labels[:5],
        "confidence": round(vision_data.get("labelAnnotations", [{}])[0].get("score", 0) * 100)
    })


# ── /api/sighting  ───────────────────────────────────────────────
@api_bp.route("/sighting", methods=["POST"])
@api_login_required
def save_sighting():
    """
    Save a confirmed sighting to Firestore (NoSQL) and
    update the SQL leaderboard score.
    """
    user_id = session["user_id"]
    data = request.get_json()
    species = data.get("species", "Unknown")
    category = data.get("category", "other")
    lat = data.get("lat")
    lng = data.get("lng")
    image_b64 = data.get("image_b64", "")

    # Check if this is a new species for the user
    existing = (
        db.collection("sightings")
        .where("user_id", "==", user_id)
        .where("species", "==", species)
        .limit(1)
        .get()
    )
    is_new = len(existing) == 0
    points = calculate_points(species, is_new)

    # --- Firestore: store rich sighting document (NoSQL) ---
    sighting_ref = db.collection("sightings").document()
    sighting_ref.set({
        "user_id": user_id,
        "species": species,
        "category": category,
        "is_new": is_new,
        "points": points,
        "lat": lat,
        "lng": lng,
        "image_b64": image_b64[:500] if image_b64 else "",  # thumbnail stub
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    # --- SQL: update leaderboard score ---
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO leaderboard (user_id, total_points, species_count)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              total_points = total_points + ?,
              species_count = species_count + ?
        """, (user_id, points, 1 if is_new else 0,
              points, 1 if is_new else 0))
        conn.commit()

    # --- Firestore: check and award badges ---
    awarded = _check_badges(user_id, category, is_new)

    return jsonify({
        "points": points,
        "is_new": is_new,
        "sighting_id": sighting_ref.id,
        "badges_awarded": awarded
    }), 201


# ── /api/leaderboard ─────────────────────────────────────────────
@api_bp.route("/leaderboard")
def leaderboard():
    """Top 20 users from SQL leaderboard table."""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT user_id, display_name, total_points, species_count
            FROM leaderboard
            ORDER BY total_points DESC
            LIMIT 20
        """).fetchall()
    return jsonify([dict(r) for r in rows])


# ── /api/sightings/<user_id> ─────────────────────────────────────
@api_bp.route("/sightings/<user_id>")
@api_login_required
def get_sightings(user_id):
    """Get all sightings for a user from Firestore."""
    if session["user_id"] != user_id:
        return jsonify({"error": "Forbidden"}), 403
    docs = (
        db.collection("sightings")
        .where("user_id", "==", user_id)
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(50)
        .get()
    )
    return jsonify([{"id": d.id, **d.to_dict()} for d in docs])


# ── /api/nearby ──────────────────────────────────────────────────
@api_bp.route("/nearby")
@api_login_required
def nearby_sightings():
    """Recent sightings from all users for the explore map."""
    docs = (
        db.collection("sightings")
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(100)
        .get()
    )
    return jsonify([{
        "species": d.to_dict().get("species"),
        "category": d.to_dict().get("category"),
        "lat": d.to_dict().get("lat"),
        "lng": d.to_dict().get("lng"),
    } for d in docs if d.to_dict().get("lat")])


# ── Helpers ──────────────────────────────────────────────────────
def _guess_category(labels: list) -> str:
    label_str = " ".join(labels).lower()
    if any(w in label_str for w in ["bird", "avian", "feather", "beak"]):
        return "bird"
    if any(w in label_str for w in ["insect", "butterfly", "beetle", "bug", "ant", "bee"]):
        return "insect"
    if any(w in label_str for w in ["plant", "flower", "tree", "leaf", "grass", "fern"]):
        return "plant"
    if any(w in label_str for w in ["mammal", "fox", "deer", "rabbit", "squirrel"]):
        return "animal"
    return "other"


BADGE_RULES = {
    "first_find": {"label": "First Find", "icon": "🌱", "threshold": 1},
    "bird_5": {"label": "Bird Watcher", "icon": "🐦", "threshold": 5, "category": "bird"},
    "insect_5": {"label": "Bug Hunter", "icon": "🦋", "threshold": 5, "category": "insect"},
    "plant_10": {"label": "Botanist", "icon": "🌸", "threshold": 10, "category": "plant"},
    "species_25": {"label": "Explorer 25", "icon": "🗺️", "threshold": 25},
    "species_50": {"label": "Explorer 50", "icon": "🌍", "threshold": 50},
}


def _check_badges(user_id: str, category: str, is_new: bool) -> list:
    """Award badges if thresholds are newly crossed. Returns list of awarded badge keys."""
    awarded = []
    user_ref = db.collection("users").document(user_id)
    user_data = user_ref.get().to_dict() or {}
    existing_badges = set(user_data.get("badges", []))

    total_species = user_data.get("species_count", 0) + (1 if is_new else 0)
    cat_count = user_data.get(f"{category}_count", 0) + (1 if is_new else 0)

    for key, rule in BADGE_RULES.items():
        if key in existing_badges:
            continue
        cat = rule.get("category")
        count = cat_count if cat else total_species
        if count >= rule["threshold"]:
            existing_badges.add(key)
            awarded.append({"key": key, "label": rule["label"], "icon": rule["icon"]})

    if awarded:
        user_ref.set({"badges": list(existing_badges)}, merge=True)
    return awarded
