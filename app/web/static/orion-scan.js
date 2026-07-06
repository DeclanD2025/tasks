// ORION barcode scanner — native BarcodeDetector where available, honest
// manual fallback everywhere else (no paid SDK, no heavy vendored decoder).
// On a hit it looks the code up via ORION's own proxy to Open Food Facts.

(function () {
  "use strict";

  const stage = document.querySelector("[data-scan-stage]");
  if (!stage) return;

  const video = stage.querySelector("video");
  const statusEl = document.querySelector("[data-scan-status]");
  const resultEl = document.querySelector("[data-scan-result]");
  const manualForm = document.querySelector("[data-scan-manual]");
  let stream = null;
  let scanning = false;

  function status(text) { if (statusEl) statusEl.textContent = text; }

  function text(tag, className, value) {
    const node = document.createElement(tag);
    node.className = className || "";
    node.textContent = value;
    return node;
  }

  async function lookup(code) {
    status(`Found ${code} — looking it up…`);
    stopCamera();
    try {
      const response = await fetch(`/api/nutrition/barcode/${encodeURIComponent(code)}`,
        { credentials: "same-origin" });
      const data = await response.json();
      renderResult(code, data);
    } catch {
      status("Lookup failed — network unavailable. Enter it manually below.");
    }
  }

  function renderResult(code, data) {
    if (!resultEl) return;
    resultEl.replaceChildren();
    if (!data.found) {
      status("");
      resultEl.appendChild(text("strong", "", "Not in Open Food Facts."));
      resultEl.appendChild(text("p", "hint",
        "Add it once with Quick add or manual entry — your correction is remembered and wins next time."));
      return;
    }
    const food = data.food;
    status("");
    const form = document.querySelector("[data-log-form]");
    if (form) {
      form.querySelector('input[name="name"]').value = food.name || `Product ${code}`;
      form.querySelector('input[name="food_id"]').value = food.id || "";
      form.querySelector('input[name="food_payload"]').value = food.id ? "" : JSON.stringify(food);
      const grams = form.querySelector('input[name="grams"]');
      grams.value = food.serving_size ? String(Math.round(food.serving_size)) : "100";
      form.hidden = false;
    }
    resultEl.appendChild(text("strong", "", food.name || `Product ${code}`));
    if (food.brand) resultEl.appendChild(text("p", "hint", food.brand));
    const macros = [
      food.calories_100g !== null && food.calories_100g !== undefined ? `${Math.round(food.calories_100g)} kcal` : null,
      food.protein_100g !== null && food.protein_100g !== undefined ? `${food.protein_100g}g protein` : null,
      food.carbs_100g !== null && food.carbs_100g !== undefined ? `${food.carbs_100g}g carbs` : null,
      food.fat_100g !== null && food.fat_100g !== undefined ? `${food.fat_100g}g fat` : null,
    ].filter(Boolean).join(" · ");
    if (macros) resultEl.appendChild(text("p", "hint", `Per 100g: ${macros}`));
    form?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function stopCamera() {
    scanning = false;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
  }

  async function startCamera() {
    if (!("BarcodeDetector" in window)) {
      status("Live scanning isn't supported in this browser — type the barcode below instead.");
      stage.hidden = true;
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" }, audio: false,
      });
      video.srcObject = stream;
      await video.play();
      scanning = true;
      status("Point the camera at the barcode.");
      const detector = new window.BarcodeDetector({
        formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"],
      });
      const scanFrame = async () => {
        if (!scanning) return;
        try {
          const codes = await detector.detect(video);
          if (codes.length && codes[0].rawValue) {
            lookup(codes[0].rawValue.trim());
            return;
          }
        } catch { /* transient frame errors are normal */ }
        requestAnimationFrame(scanFrame);
      };
      requestAnimationFrame(scanFrame);
    } catch {
      status("Camera unavailable — type the barcode below instead.");
      stage.hidden = true;
    }
  }

  manualForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const code = manualForm.querySelector('input[name="barcode"]').value.replace(/\D/g, "");
    if (code) lookup(code);
  });

  window.addEventListener("pagehide", stopCamera);
  startCamera();
})();
