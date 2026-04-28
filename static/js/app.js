/**
 * EcoSeek — app.js
 * Shared utilities available on every page.
 */

// ── XP toast (can be called from any page) ────────
function showXpToast(pts, subText) {
  const toast = document.getElementById("xp-toast");
  if (!toast) return;
  document.getElementById("xp-toast-num").textContent = "+" + pts;
  document.getElementById("xp-toast-sub").textContent = subText || "XP earned!";
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 3500);
}

// ── Badge popup ───────────────────────────────────
function showBadgePopup(badge) {
  const popup = document.getElementById("badge-popup");
  if (!popup) return;
  document.getElementById("badge-popup-icon").textContent = badge.icon || "🏆";
  document.getElementById("badge-popup-name").textContent = badge.label || "Badge unlocked!";
  popup.classList.remove("hidden");
}
function closeBadgePopup() {
  const popup = document.getElementById("badge-popup");
  if (popup) popup.classList.add("hidden");
}

// ── Category emoji helper ─────────────────────────
function categoryEmoji(cat) {
  return { bird: "🐦", insect: "🦋", plant: "🌸", animal: "🦊" }[cat] || "🌿";
}
