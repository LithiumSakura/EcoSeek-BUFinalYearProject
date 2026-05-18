let currentImageB64    = null;
let identifiedSpecies  = null;
let identifiedCategory = null;
let userLat = null;
let userLng = null;

window.addEventListener("DOMContentLoaded", () => {
  startCamera();
  getLocation();
});

async function startCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment" }  // rear camera on phones
    });
    document.getElementById("video").srcObject = stream;
  } catch (err) {
    document.getElementById("vf-hint").textContent =
      "📷 Camera not available — use the upload button below!";
    console.warn("Camera error:", err);
  }
}

function getLocation() {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(
    pos => {
      userLat = pos.coords.latitude;
      userLng = pos.coords.longitude;
    },
    () => {}  // silently fail if denied
  );
}

function capturePhoto() {
  const video  = document.getElementById("video");
  const canvas = document.getElementById("canvas");
  canvas.width  = video.videoWidth  || 640;
  canvas.height = video.videoHeight || 480;
  canvas.getContext("2d").drawImage(video, 0, 0);
  const b64 = canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
  identifyImage(b64);
}

function handleUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    const b64 = e.target.result.split(",")[1];
    identifyImage(b64);
  };
  reader.readAsDataURL(file);
}

async function identifyImage(b64) {
  currentImageB64 = b64;
  showSpinner(true);
  hideResult();

  try {
    const resp = await fetch("/api/identify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_b64: b64 })
    });
    const data = await resp.json();

    if (!resp.ok) throw new Error(data.error || "Identification failed");

    identifiedSpecies  = data.species;
    identifiedCategory = data.category;
    showResult(data);

    // Fetch fun facts in the background after result is shown
    loadFunFacts(data.species, data.category);

  } catch (err) {
    alert("Oops! Could not identify that. Try again or try a clearer photo 📷");
    console.error(err);
  } finally {
    showSpinner(false);
  }
}

function showResult(data) {
  const emoji = { bird:"🐦", insect:"🦋", plant:"🌸", animal:"🦊" }[data.category] || "🌿";
  document.getElementById("result-emoji").textContent = emoji;
  document.getElementById("result-name").textContent  = data.species;
  document.getElementById("result-sci").textContent   = "";

  // Tags
  const tagsEl = document.getElementById("result-tags");
  tagsEl.innerHTML = [
    `<span class="result-tag">✨ ${data.category || "Nature"}</span>`,
    ...(data.labels || []).slice(0, 3).map(l => `<span class="result-tag">${l}</span>`)
  ].join("");

  // Show fun facts section in loading state
  document.getElementById("fun-facts-wrap").style.display = "block";
  document.getElementById("fun-facts-loading").classList.remove("hidden");
  document.getElementById("fun-facts-list").innerHTML = "";

  // Hide XP until saved
  document.getElementById("result-xp").style.display = "none";
  document.getElementById("result-panel").classList.remove("hidden");
}

async function loadFunFacts(species, category) {
  try {
    const resp = await fetch("/api/funfacts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ species, category })
    });
    const data = await resp.json();

    document.getElementById("fun-facts-loading").classList.add("hidden");

    if (data.facts && data.facts.length) {
      document.getElementById("fun-facts-list").innerHTML =
        data.facts.map(f => `<li>${f}</li>`).join("");
    }
  } catch (err) {
    document.getElementById("fun-facts-loading").classList.add("hidden");
    console.warn("Fun facts error:", err);
  }
}

async function saveSighting() {
  if (!identifiedSpecies) return;

  const btn = document.getElementById("save-btn");
  btn.textContent = "Saving... 🌀";
  btn.disabled = true;

  try {
    const resp = await fetch("/api/sighting", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        species:   identifiedSpecies,
        category:  identifiedCategory,
        image_b64: currentImageB64,
        lat: userLat,
        lng: userLng
      })
    });
    const data = await resp.json();

    if (!resp.ok) throw new Error(data.error || "Save failed");

    document.getElementById("result-xp-num").textContent = "+" + data.points;
    document.getElementById("result-xp-sub").textContent = data.is_new
      ? "Brand new species! 🎉"
      : "Keep spotting to find new ones!";
    document.getElementById("result-xp").style.display = "flex";

    showXpToast(data.points, data.is_new);

    if (data.badges_awarded && data.badges_awarded.length > 0) {
      setTimeout(() => showBadgePopup(data.badges_awarded[0]), 2000);
    }

    btn.textContent = "Saved! ✅";
  } catch (err) {
    btn.textContent = "Save to My Collection! 🌟";
    btn.disabled = false;
    alert("Could not save sighting. Please try again.");
    console.error(err);
  }
}

function resetCamera() {
  hideResult();
  currentImageB64    = null;
  identifiedSpecies  = null;
  identifiedCategory = null;
  document.getElementById("save-btn").textContent = "Save to My Collection! 🌟";
  document.getElementById("save-btn").disabled    = false;
  document.getElementById("fun-facts-wrap").style.display = "none";
  document.getElementById("fun-facts-list").innerHTML = "";
}

// UI helpers
function showSpinner(show) {
  document.getElementById("spinner").classList.toggle("hidden", !show);
}
function hideResult() {
  document.getElementById("result-panel").classList.add("hidden");
}
function showXpToast(pts, isNew) {
  document.getElementById("xp-toast-num").textContent = "+" + pts;
  document.getElementById("xp-toast-sub").textContent = isNew ? "New species!" : "Sighting saved!";
  const toast = document.getElementById("xp-toast");
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 3500);
}
function showBadgePopup(badge) {
  document.getElementById("badge-popup-icon").textContent = badge.icon;
  document.getElementById("badge-popup-name").textContent = badge.label;
  document.getElementById("badge-popup").classList.remove("hidden");
}
function closeBadgePopup() {
  document.getElementById("badge-popup").classList.add("hidden");
}