import os
import base64
import tempfile
from flask import Blueprint, request, jsonify, session
from functools import wraps
from firebase_admin import firestore
import requests
from datetime import datetime, timezone, timedelta

from database.sql_db import get_db_connection, upsert_user
from scoring import calculate_points

def get_db():
    return firestore.client()

api_bp = Blueprint("api", __name__)

PLANTNET_API_KEY = os.environ.get("PLANTNET_API_KEY", "")
PLANTNET_URL     = "https://my-api.plantnet.org/v2/identify/all"

VISION_API_KEY   = os.environ.get("VISION_API_KEY", "")
VISION_URL       = "https://vision.googleapis.com/v1/images:annotate"

INAT_TAXA_URL    = "https://api.inaturalist.org/v1/taxa"

ECOSEEK_USER_AGENT = "EcoSeek/1.0 (student project; contact via github)"


def api_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Unauthorised"}), 401
        return f(*args, **kwargs)
    return decorated


@api_bp.route("/identify", methods=["POST"])
@api_login_required
def identify():
    try:
        data      = request.get_json()
        image_b64 = data.get("image_b64")
        if not image_b64:
            return jsonify({"error": "No image provided"}), 400

        plantnet_result = _identify_plantnet(image_b64)

        if plantnet_result and plantnet_result["confidence"] >= 15:
            return jsonify({**plantnet_result, "source": "plantnet"})

        vision_result = _identify_vision(image_b64)
        if vision_result:
            if plantnet_result and plantnet_result["confidence"] >= 5:
                return jsonify({**plantnet_result, "source": "plantnet"})
            if any(w in " ".join(vision_result.get("labels", [])).lower()
                    for w in ["flower", "petal", "plant", "leaf", "bloom", "vegetation"]):
                vision_result["category"] = "plant"
            return jsonify({**vision_result, "source": "vision"})

        return jsonify({"error": "Could not identify — try a clearer photo"}), 422

    except Exception as e:
        print(f"IDENTIFY ERROR: {e}")
        return jsonify({"error": str(e)}), 500


def _identify_plantnet(image_b64: str) -> dict | None:
    if not PLANTNET_API_KEY:
        return None
    try:
        img_bytes = base64.b64decode(image_b64)
        resp = requests.post(
            PLANTNET_URL,
            params={
                "api-key":    PLANTNET_API_KEY,
                "lang":       "en",
                "nb-results": 5,
            },
            files={"images": ("photo.jpg", img_bytes, "image/jpeg")},
            data={"organs": "auto"},
            timeout=15
        )

        if resp.status_code == 404:
            return None
        if not resp.ok:
            print(f"PLANTNET ERROR {resp.status_code}: {resp.text[:200]}")
            return None

        pdata      = resp.json()
        results    = pdata.get("results", [])
        if not results:
            return None

        top        = results[0]
        score      = round(top.get("score", 0) * 100, 1)
        species    = top["species"]
        sci_name   = species.get("scientificNameWithoutAuthor", "Unknown")
        common     = species.get("commonNames", [sci_name])
        common_name = common[0] if common else sci_name
        family     = species.get("family", {}).get("scientificNameWithoutAuthor", "")
        organ      = (pdata.get("predictedOrgans") or [{}])[0].get("organ", "")

        return {
            "species":     common_name,
            "sci_name":    sci_name,
            "family":      family,
            "category":    "plant",
            "confidence":  score,
            "organ":       organ,
            "labels":      [r["species"].get("scientificNameWithoutAuthor", "")
                            for r in results[:3]],
        }
    except Exception as e:
        print(f"PLANTNET EXCEPTION: {e}")
        return None


def _identify_vision(image_b64: str) -> dict | None:
    if not VISION_API_KEY:
        return None
    try:
        payload = {
            "requests": [{
                "image": {"content": image_b64},
                "features": [
                    {"type": "LABEL_DETECTION",  "maxResults": 10},
                    {"type": "WEB_DETECTION",    "maxResults": 5}
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
            print(f"VISION ERROR {resp.status_code}: {resp.text[:200]}")
            return None

        vdata       = resp.json()["responses"][0]
        labels      = [l["description"] for l in vdata.get("labelAnnotations", [])]
        web_entities = [e["description"] for e in
                        vdata.get("webDetection", {}).get("webEntities", [])
                        if e.get("score", 0) > 0.5]

        species     = web_entities[0] if web_entities else (labels[0] if labels else "Unknown")
        category    = _guess_category(labels)
        confidence  = round(
            (vdata.get("labelAnnotations") or [{}])[0].get("score", 0) * 100
        )

        return {
            "species":    species,
            "sci_name":   "",
            "family":     "",
            "category":   category,
            "confidence": confidence,
            "labels":     labels[:5],
        }
    except Exception as e:
        print(f"VISION EXCEPTION: {e}")
        return None


@api_bp.route("/funfacts", methods=["POST"])
@api_login_required
def fun_facts():
    data     = request.get_json()
    species  = data.get("species", "")
    sci_name = data.get("sci_name", "")
    category = data.get("category", "other")

    query = sci_name if sci_name else species

    try:
        resp = requests.get(
            INAT_TAXA_URL,
            params={
                "q":          query,
                "per_page":   1,
                "locale":     "en",
                "preferred_place_id": 6857,
            },
            headers={"User-Agent": ECOSEEK_USER_AGENT},
            timeout=10
        )

        if resp.ok:
            results = resp.json().get("results", [])
            if results:
                taxon        = results[0]
                wiki_summary = taxon.get("wikipedia_summary", "")
                common_name  = taxon.get("preferred_common_name", species)
                sci          = taxon.get("name", sci_name)
                rank         = taxon.get("rank", "")
                conservation = taxon.get("conservation_status", {})
                status_name  = (conservation.get("status_name") or "").replace("_", " ")

                facts = _extract_facts(wiki_summary, common_name, sci, rank, status_name, category)
                return jsonify({
                    "facts":       facts,
                    "common_name": common_name,
                    "sci_name":    sci,
                    "inat_url":    f"https://www.inaturalist.org/taxa/{taxon['id']}",
                    "source":      "iNaturalist"
                })

    except Exception as e:
        print(f"INAT TAXA ERROR: {e}")

    # Fallback facts if iNaturalist call fails
    return jsonify({"facts": _fallback_facts(species, category), "source": "fallback"})


def _extract_facts(summary: str, common: str, sci: str, rank: str,
                   status: str, category: str) -> list:
    facts = []

    if status and status not in ("least concern", ""):
        status_display = status.title()
        facts.append(
            f"🔴 The {common} is listed as '{status_display}' — "
            f"that means it needs our help to survive!"
        )

    if summary:
        sentences = [s.strip() for s in summary.replace("\n", " ").split(". ")
                     if len(s.strip()) > 40 and len(s.strip()) < 220]
        # Skip the boring first sentence (usually just "X is a species of Y")
        candidates = sentences[1:] if len(sentences) > 1 else sentences
        for s in candidates:
            if len(facts) >= 3:
                break
            # Skip sentences with too many brackets / citations
            if s.count("(") > 2 or "[" in s:
                continue
            facts.append(s.rstrip(".") + ".")

    fallbacks = _fallback_facts(common, category)
    while len(facts) < 3:
        fb = fallbacks[len(facts) % len(fallbacks)]
        if fb not in facts:
            facts.append(fb)

    return facts[:3]


def _fallback_facts(species: str, category: str) -> list:
    fallbacks = {
        "bird": [
            "Birds are the only living animals that have feathers!",
            "Some birds can remember thousands of places where they stored food.",
            "The peregrine falcon is the fastest animal on Earth, diving at over 240 mph!"
        ],
        "insect": [
            "There are more insects on Earth than any other type of animal!",
            "Butterflies taste with their feet — they have taste sensors on their legs.",
            "Bees have five eyes and can see colours that humans can't!"
        ],
        "plant": [
            "Plants make their own food using sunlight, water, and air in a process called photosynthesis!",
            "The oldest living tree in the world is over 5,000 years old.",
            "Some plants can send chemical signals through the air to warn nearby plants of danger!"
        ],
        "animal": [
            "Some animals, like the axolotl, can completely regrow lost limbs!",
            "The blue whale is the largest animal ever known to have lived on Earth.",
            "Foxes use the Earth's magnetic field like a compass to help them hunt!"
        ],
    }
    return fallbacks.get(category, [
        f"The {species} plays an important role in its local ecosystem!",
        "Every species you spot helps scientists understand how healthy our nature is.",
        "Great spotting — citizen science like this really makes a difference! 🌿"
    ])


@api_bp.route("/sighting", methods=["POST"])
@api_login_required
def save_sighting():
    db       = get_db()
    user_id  = session["user_id"]
    username = session.get("display_name", "Explorer")
    data     = request.get_json()
    species  = data.get("species",  "Unknown")
    sci_name = data.get("sci_name", "")
    category = data.get("category", "other")
    lat      = data.get("lat")
    lng      = data.get("lng")
    image_b64 = data.get("image_b64", "")

    upsert_user(user_id, username)

    existing = (
        db.collection("sightings")
        .where("user_id", "==", user_id)
        .where("species", "==", species)
        .limit(1)
        .get()
    )
    is_new = len(existing) == 0

    user_ref  = db.collection("users").document(user_id)
    user_snap = user_ref.get()
    user_data = user_snap.to_dict() if user_snap.exists else {}

    today    = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    last_active    = user_data.get("last_active", "")
    current_streak = user_data.get("day_streak", 0)

    if last_active == today:
        new_streak = current_streak
    elif last_active == yesterday:
        new_streak = current_streak + 1
    else:
        new_streak = 1

    points = calculate_points(species, is_new, streak_days=new_streak)

    sighting_ref = db.collection("sightings").document()
    sighting_ref.set({
        "user_id":   user_id,
        "species":   species,
        "sci_name":  sci_name,
        "category":  category,
        "is_new":    is_new,
        "points":    points,
        "lat":       lat,
        "lng":       lng,
        "image_b64": image_b64[:500] if image_b64 else "",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

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

    update_data = {
        "total_xp":    firestore.Increment(points),
        "total_points": firestore.Increment(points),
        "day_streak":  new_streak,
        "streak_days": new_streak,
        "last_active": today,
    }
    if is_new:
        update_data["species_count"]     = firestore.Increment(1)
        update_data[f"{category}_count"] = firestore.Increment(1)
    user_ref.set(update_data, merge=True)

    awarded = _check_badges(user_id, category, is_new)

    return jsonify({
        "points":         points,
        "is_new":         is_new,
        "sighting_id":    sighting_ref.id,
        "badges_awarded": awarded
    }), 201


@api_bp.route("/leaderboard")
def leaderboard():
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT user_id, display_name, total_points, species_count
            FROM leaderboard
            ORDER BY total_points DESC
            LIMIT 20
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@api_bp.route("/sightings/<user_id>")
@api_login_required
def get_sightings(user_id):
    if session["user_id"] != user_id:
        return jsonify({"error": "Forbidden"}), 403
    db   = get_db()
    docs = (
        db.collection("sightings")
        .where("user_id", "==", user_id)
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(50)
        .get()
    )
    return jsonify([{"id": d.id, **d.to_dict()} for d in docs])


@api_bp.route("/profile/photo", methods=["POST"])
@api_login_required
def update_profile_photo():
    db      = get_db()
    user_id = session["user_id"]
    data    = request.get_json()
    photo_b64 = data.get("photo_b64", "")
    if not photo_b64:
        return jsonify({"error": "No photo provided"}), 400
    if len(photo_b64) > 70000:
        return jsonify({"error": "Image too large — please use a smaller photo"}), 400
    db.collection("users").document(user_id).set(
        {"photo_url": photo_b64}, merge=True
    )
    session["photo_url"] = photo_b64
    return jsonify({"message": "Photo updated!"}), 200


def _guess_category(labels: list) -> str:
    label_str = " ".join(labels).lower()
    if any(w in label_str for w in ["plant", "flower", "petal", "tree", "leaf",
                                     "grass", "fern", "flora", "bloom", "blossom",
                                     "sunflower", "daisy", "rose", "vegetation"]):
        return "plant"
    if any(w in label_str for w in ["bird", "avian", "feather", "beak", "robin", "sparrow"]):
        return "bird"
    if any(w in label_str for w in ["insect", "butterfly", "beetle", "bug", "ant", "bee", "moth"]):
        return "insect"
    if any(w in label_str for w in ["mammal", "fox", "deer", "rabbit", "squirrel", "animal"]):
        return "animal"
    return "other"


BADGE_RULES = {
    "first_find":  {"label": "First Find",    "icon": "🌱", "threshold": 1},
    "bird_5":      {"label": "Bird Watcher",  "icon": "🐦", "threshold": 5,  "category": "bird"},
    "insect_5":    {"label": "Bug Hunter",    "icon": "🦋", "threshold": 5,  "category": "insect"},
    "plant_10":    {"label": "Botanist",      "icon": "🌸", "threshold": 10, "category": "plant"},
    "animal_5":    {"label": "Animal Spotter","icon": "🦊", "threshold": 5,  "category": "animal"},
    "species_10":  {"label": "Explorer 10",   "icon": "🗺️", "threshold": 10},
    "species_25":  {"label": "Explorer 25",   "icon": "🌍", "threshold": 25},
    "species_50":  {"label": "Champion",      "icon": "🏆", "threshold": 50},
}


def _check_badges(user_id: str, category: str, is_new: bool) -> list:
    db        = get_db()
    awarded   = []
    user_ref  = db.collection("users").document(user_id)
    user_data = user_ref.get().to_dict() or {}
    existing  = set(user_data.get("badges", []))

    total_species = user_data.get("species_count", 0) + (1 if is_new else 0)
    cat_count     = user_data.get(f"{category}_count", 0) + (1 if is_new else 0)

    for key, rule in BADGE_RULES.items():
        if key in existing:
            continue
        count = cat_count if rule.get("category") else total_species
        if count >= rule["threshold"]:
            existing.add(key)
            awarded.append({"key": key, "label": rule["label"], "icon": rule["icon"]})

    if awarded:
        user_ref.set({"badges": list(existing)}, merge=True)
    return awarded