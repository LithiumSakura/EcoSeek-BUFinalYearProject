"""
EcoSeek — Google Cloud Functions
Background tasks triggered by Firestore events.

Deploy with:
  gcloud functions deploy check_badges \
    --runtime python311 \
    --trigger-event providers/cloud.firestore/eventTypes/document.create \
    --trigger-resource "projects/YOUR_PROJECT/databases/(default)/documents/sightings/{sightingId}" \
    --region europe-west2
"""

import functions_framework
from firebase_admin import firestore, initialize_app
import firebase_admin

# Initialise Firebase (uses Application Default Credentials on Cloud)
if not firebase_admin._apps:
    initialize_app()

db = firestore.client()

BADGE_RULES = {
    "first_find":  {"label": "First Find",      "icon": "🌱", "threshold": 1,  "category": None},
    "bird_5":      {"label": "Bird Watcher",     "icon": "🐦", "threshold": 5,  "category": "bird"},
    "insect_5":    {"label": "Bug Hunter",       "icon": "🦋", "threshold": 5,  "category": "insect"},
    "plant_10":    {"label": "Botanist",         "icon": "🌸", "threshold": 10, "category": "plant"},
    "animal_5":    {"label": "Animal Spotter",   "icon": "🦊", "threshold": 5,  "category": "animal"},
    "species_10":  {"label": "Explorer 10",      "icon": "🗺️", "threshold": 10, "category": None},
    "species_25":  {"label": "Explorer 25",      "icon": "🌍", "threshold": 25, "category": None},
    "species_50":  {"label": "Explorer 50",      "icon": "🏆", "threshold": 50, "category": None},
}


@functions_framework.cloud_event
def check_badges(cloud_event):
    """
    Triggered when a new sighting document is created in Firestore.
    Awards badges to the user if they have crossed any thresholds.
    """
    data = cloud_event.data
    sighting = data.get("value", {}).get("fields", {})

    user_id  = sighting.get("user_id",  {}).get("stringValue")
    category = sighting.get("category", {}).get("stringValue")
    is_new   = sighting.get("is_new",   {}).get("booleanValue", False)

    if not user_id:
        return

    user_ref  = db.collection("users").document(user_id)
    user_data = user_ref.get().to_dict() or {}
    existing_badges = set(user_data.get("badges", []))

    # Increment counters
    total_species = user_data.get("species_count", 0) + (1 if is_new else 0)
    cat_count     = user_data.get(f"{category}_count", 0) + (1 if is_new else 0)

    newly_awarded = []
    for key, rule in BADGE_RULES.items():
        if key in existing_badges:
            continue
        check_count = cat_count if rule["category"] else total_species
        if check_count >= rule["threshold"]:
            existing_badges.add(key)
            newly_awarded.append({"key": key, "label": rule["label"], "icon": rule["icon"]})

    # Update user document with new badges and counters
    update_data = {
        "badges":       list(existing_badges),
        "species_count": total_species,
        f"{category}_count": cat_count,
    }
    user_ref.set(update_data, merge=True)

    if newly_awarded:
        print(f"Awarded badges to {user_id}: {[b['key'] for b in newly_awarded]}")
