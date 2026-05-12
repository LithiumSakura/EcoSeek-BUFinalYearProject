"""
EcoSeek — REST API Blueprint
All /api/* endpoints. Returns JSON.
"""

import os
from flask import Blueprint, request, jsonify, session
from functools import wraps
from firebase_admin import firestore
import firebase_admin
import requests
from datetime import datetime, timezone, timedelta

from database.sql_db import get_db_connection, upsert_user
from scoring import calculate_points

# Firestore client — initialised in main.py before this is imported
def get_db():
    return firestore.client()

api_bp = Blueprint("api", __name__)

VISION_API_KEY = os.environ.get("VISION_API_KEY", "")
VISION_URL     = "https://vision.googleapis.com/v1/images:annotate"


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
    try:
        data = request.get_json()
        image_b64 = data.get("image_b64")
        if not image_b64:
            return jsonify({"error": "No image provided"}), 400

        payload = {
            "requests": [{
                "image": {"content": image_b64},
                "features": [
                    {"type": "LABEL_DETECTION", "maxResults": 10},
                    {"type": "WEB_DETECTION",   "maxResults": 5}
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
            print(f"VISION API RESPONSE: {resp.status_code} - {resp.text}")
            return jsonify({"error": "Vision API error"}), 502

        vision_data = resp.json()["responses"][0]
        labels      = [l["description"] for l in vision_data.get("labelAnnotations", [])]
        web_entities = [e["description"] for e in
                        vision_data.get("webDetection", {}).get("webEntities", [])
                        if e.get("score", 0) > 0.5]

        species  = web_entities[0] if web_entities else (labels[0] if labels else "Unknown")
        category = _guess_category(labels)

        return jsonify({
            "species":    species,
            "category":   category,
            "labels":     labels[:5],
            "confidence": round(vision_data.get("labelAnnotations", [{}])[0].get("score", 0) * 100)
        })
    except Exception as e:
        print(f"IDENTIFY ERROR: {e}")
        return jsonify({"error": str(e)}), 500


# ── /api/sighting  ───────────────────────────────────────────────
@api_bp.route("/sighting", methods=["POST"])
@api_login_required
def save_sighting():
    """
    Save a confirmed sighting to Firestore (NoSQL) and
    update the SQL leaderboard score.
    """
    db = get_db()
    user_id  = session["user_id"]
    username = session.get("display_name", "Explorer")
    data     = request.get_json()
    species  = data.get("species", "Unknown")
    category = data.get("category", "other")
    lat      = data.get("lat")
    lng      = data.get("lng")
    image_b64 = data.get("image_b64", "")

    # Ensure user row exists in SQL leaderboard
    upsert_user(user_id, username)

    # Check if this is a new species for the user
    existing = (
        db.collection("sightings")
        .where("user_id", "==", user_id)
        .where("species", "==", species)
        .limit(1)
        .get()
    )
    is_new = len(existing) == 0

    # ── Streak calculation ────────────────────────────────────────
    user_ref  = db.collection("users").document(user_id)
    user_snap = user_ref.get()
    user_data = user_snap.to_dict() if user_snap.exists else {}

    today     = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    last_active     = user_data.get("last_active", "")
    current_streak  = user_data.get("day_streak", 0)

    if last_active == today:
        new_streak = current_streak          # already logged today
    elif last_active == yesterday:
        new_streak = current_streak + 1      # continuing streak
    else:
        new_streak = 1                        # streak reset

    # ── Points ───────────────────────────────────────────────────
    points = calculate_points(species, is_new, streak_days=new_streak)

    # ── Firestore: store sighting ─────────────────────────────────
    sighting_ref = db.collection("sightings").document()
    sighting_ref.set({
        "user_id":   user_id,
        "species":   species,
        "category":  category,
        "is_new":    is_new,
        "points":    points,
        "lat":       lat,
        "lng":       lng,
        "image_b64": image_b64[:500] if image_b64 else "",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    # ── SQL: upsert leaderboard row ───────────────────────────────
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO leaderboard (user_id, display_name, total_points, species_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                total_points  = total_points  + ?,
                species_count = species_count + ?,
                display_name  = excluded.display_name,
                last_seen     = datetime('now')
        """, (
            user_id, username, points, 1 if is_new else 0,
            points, 1 if is_new else 0
        ))
        conn.commit()

    # ── Firestore: update user profile ───────────────────────────
    update_data = {
        "total_xp":    firestore.Increment(points),
        "day_streak":  new_streak,
        "last_active": today,
    }
    if is_new:
        update_data["species_count"]      = firestore.Increment(1)
        update_data[f"{category}_count"]  = firestore.Increment(1)

    user_ref.set(update_data, merge=True)

    # ── Badge check ───────────────────────────────────────────────
    awarded = _check_badges(user_id, category, is_new)

    return jsonify({
        "points":         points,
        "is_new":         is_new,
        "sighting_id":    sighting_ref.id,
        "badges_awarded": awarded
    }), 201


# ── /api/leaderboard ─────────────────────────────────────────────
@api_bp.route("/leaderboard")
def leaderboard():
    """Top 20 users from SQL leaderboard table, with display_name."""
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
    db = get_db()
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
    db = get_db()
    docs = (
        db.collection("sightings")
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(100)
        .get()
    )
    results = []
    for d in docs:
        d_dict = d.to_dict()
        if d_dict.get("lat") and d_dict.get("lng"):
            results.append({
                "species":   d_dict.get("species"),
                "category":  d_dict.get("category"),
                "lat":       d_dict.get("lat"),
                "lng":       d_dict.get("lng"),
                "timestamp": d_dict.get("timestamp", ""),
            })
    return jsonify(results)


# ── /api/profile/photo ───────────────────────────────────────────
@api_bp.route("/profile/photo", methods=["POST"])
@api_login_required
def update_profile_photo():
    """
    Store a base64 profile photo for the current user.
    Saves a small thumbnail to Firestore (max ~50 KB).
    For production you'd upload to Cloud Storage instead.
    """
    db = get_db()
    user_id = session["user_id"]
    data    = request.get_json()
    photo_b64 = data.get("photo_b64", "")

    if not photo_b64:
        return jsonify({"error": "No photo provided"}), 400

    # Limit stored size — frontend should send a resized thumbnail
    if len(photo_b64) > 70000:
        return jsonify({"error": "Image too large — please use a smaller photo"}), 400

    user_ref = get_db().collection("users").document(user_id)
    user_ref.set({"photo_url": photo_b64}, merge=True)
    session["photo_url"] = photo_b64

    return jsonify({"message": "Photo updated!"}), 200


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
    "first_find":  {"label": "First Find",      "icon": "🌱", "threshold": 1},
    "bird_5":      {"label": "Bird Watcher",     "icon": "🐦", "threshold": 5,  "category": "bird"},
    "insect_5":    {"label": "Bug Hunter",       "icon": "🦋", "threshold": 5,  "category": "insect"},
    "plant_10":    {"label": "Botanist",         "icon": "🌸", "threshold": 10, "category": "plant"},
    "animal_5":    {"label": "Animal Spotter",   "icon": "🦊", "threshold": 5,  "category": "animal"},
    "species_10":  {"label": "Explorer 10",      "icon": "🗺️", "threshold": 10},
    "species_25":  {"label": "Explorer 25",      "icon": "🌍", "threshold": 25},
    "species_50":  {"label": "Champion",         "icon": "🏆", "threshold": 50},
}


def _check_badges(user_id: str, category: str, is_new: bool) -> list:
    """Award badges if thresholds are newly crossed. Returns list of awarded badge dicts."""
    db = get_db()
    awarded   = []
    user_ref  = db.collection("users").document(user_id)
    user_data = user_ref.get().to_dict() or {}
    existing_badges = set(user_data.get("badges", []))

    total_species = user_data.get("species_count", 0) + (1 if is_new else 0)
    cat_count     = user_data.get(f"{category}_count", 0) + (1 if is_new else 0)

    for key, rule in BADGE_RULES.items():
        if key in existing_badges:
            continue
        cat   = rule.get("category")
        count = cat_count if cat else total_species
        if count >= rule["threshold"]:
            existing_badges.add(key)
            awarded.append({"key": key, "label": rule["label"], "icon": rule["icon"]})

    if awarded:
        user_ref.set({"badges": list(existing_badges)}, merge=True)
    return awarded


# ── /api/funfacts ─────────────────────────────────────────────────
@api_bp.route("/funfacts", methods=["POST"])
@api_login_required
def fun_facts():
    """
    Uses the Anthropic API to generate 3 child-friendly fun facts
    about the identified species.
    """
    data    = request.get_json()
    species  = data.get("species", "this plant or animal")
    category = data.get("category", "nature")

    prompt = (
        f"You are a friendly nature guide for children aged 8-14. "
        f"A child has just spotted a {species} (category: {category}). "
        f"Give exactly 3 short, fun, surprising facts about {species}. "
        f"Each fact should be one sentence, easy to understand, and exciting. "
        f"Reply ONLY as a JSON array of 3 strings, nothing else. "
        f'Example format: ["Fact one.", "Fact two.", "Fact three."]'
    )

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key":    os.environ.get("ANTHROPIC_API_KEY", ""),
                "anthropic-version": "2023-06-01"
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages":   [{"role": "user", "content": prompt}]
            },
            timeout=15
        )

        if not resp.ok:
            return jsonify({"facts": _fallback_facts(species, category)}), 200

        raw   = resp.json()["content"][0]["text"].strip()
        # Strip any accidental markdown fences
        raw   = raw.replace("```json", "").replace("```", "").strip()
        import json as _json
        facts = _json.loads(raw)
        if not isinstance(facts, list):
            raise ValueError("Not a list")
        return jsonify({"facts": facts[:3]}), 200

    except Exception as e:
        print(f"FUN FACTS ERROR: {e}")
        return jsonify({"facts": _fallback_facts(species, category)}), 200


def _fallback_facts(species: str, category: str) -> list:
    """Static fallback facts by category if the API call fails."""
    fallbacks = {
        "bird":   [
            "Birds are the only living animals that have feathers!",
            "Some birds can remember thousands of hiding spots where they stored food.",
            "The fastest bird in the world, the peregrine falcon, can dive at over 240 mph!"
        ],
        "insect": [
            "Insects have 6 legs and 3 body parts — head, thorax, and abdomen.",
            "There are more insects on Earth than any other type of animal!",
            "Butterflies taste with their feet — they have taste sensors on their legs."
        ],
        "plant":  [
            "Plants make their own food using sunlight, water, and air — it's called photosynthesis!",
            "The oldest living tree in the world is over 5,000 years old.",
            "Some plants can live for hundreds of years without any soil, just clinging to rocks!"
        ],
        "animal": [
            "Mammals are warm-blooded and most give birth to live young.",
            "Some animals, like the axolotl, can regrow lost limbs completely!",
            "The blue whale is the largest animal ever known to have lived on Earth."
        ],
    }
    return fallbacks.get(category, [
        f"{species} is a fascinating part of our natural world!",
        "Every species plays an important role in its ecosystem.",
        "Spotting wildlife helps scientists track how nature is doing — great work! 🌿"
    ])