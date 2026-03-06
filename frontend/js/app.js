const API_BASE = "https://placeholder-backend-url.com";

async function fetchData() {
  try {
    const response = await fetch(`${API_BASE}/api/example`);
    const data = await response.json();
    document.getElementById("data-output").textContent = JSON.stringify(data);
  } catch (err) {
    console.error("API error:", err);
  }
}

fetchData();
