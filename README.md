# EcoSeek
A gamified nature-spotting web app for children, built with Flask, Firebase, and Google Cloud. Point your phone at a plant or animal, get an instant AI identification, and earn XP for every discovery.


## Features
* AI species identification — plants via Pl@ntNet API; birds, animals, and insects via Google Cloud Vision API
* XP and levelling system — earn 50 XP for a new species, 5 XP for a repeat sighting, +10 XP streak bonus after 7 consecutive days
* Leaderboard — top 20 users ranked by total XP (SQLite locally, persists to /tmp on App Engine)
* User profiles — badges, category counts (birds / plants / insects / animals), streak tracking
* Firebase Auth — email/password and Google Sign-In
* Firestore — user documents, sighting history
* Google App Engine — one-command deploy

## Requirements
* Python 3.11+
* A Google account (for Cloud Console & Firebase)
* Google Cloud SDK installed

## Quick start guide (for local development)
1. Clone the repo
2. Create and activate a virtual environment
```
python -m venv venv
 
# Windows
venv\Scripts\activate
 
# macOS / Linux
source venv/bin/activate
```
3. Install dependencies
```bash
pip install -r requirements.txt
```
4. Set up Firebase
5. Create .env file
```
SECRET_KEY=replace-with-any-long-random-string
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_APPLICATION_CREDENTIALS=firebase-key.json
VISION_API_KEY=your-google-vision-api-key
PLANTNET_API_KEY=your-plantnet-api-key
```
6. Run locally

## Scoring system and levels

| Event | XP |
|---|---|
| New species (first time spotted) | 50 XP |
| Repeat sighting | 5 XP |
| 7-day streak bonus | +10 XP |
 
**Levels:**
| Level | XP required |
|---|---|
| Seedling | 0 |
| Sprout | 100 |
| Explorer | 300 |
| Nature Scout | 600 |
| Wildlife Ranger | 1000 |
| Eco Guardian | 1500 |
| Master Naturalist | 2500 |

## Licence
Built as a student project. Not licensed for commercial use.
