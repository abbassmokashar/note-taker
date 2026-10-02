// Meeting detail interactions: transcript/audio sync, view toggles, notes tabs.

(function () {
  const player = document.getElementById("player");
  const transcript = document.getElementById("transcript");
  const segments = transcript ? Array.from(transcript.querySelectorAll(".seg")) : [];

  // Click a segment to seek the audio.
  segments.forEach((el) => {
    el.addEventListener("click", () => {
      if (!player) return;
      const start = parseFloat(el.dataset.start || "0");
      player.currentTime = start;
      player.play().catch(() => {});
    });
  });

  // Highlight the segment being played.
  if (player) {
    player.addEventListener("timeupdate", () => {
      const t = player.currentTime;
      let active = null;
      for (const el of segments) {
        if (parseFloat(el.dataset.start || "0") <= t) active = el;
        else break;
      }
      segments.forEach((el) => el.classList.toggle("active", el === active));
    });
  }

  // Bilingual / English / Arabic view.
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-view]").forEach((b) => b.classList.remove("active"));
      button.classList.add("active");
      if (!transcript) return;
      transcript.classList.remove("view-both", "view-en", "view-ar");
      transcript.classList.add("view-" + button.dataset.view);
    });
  });

  // Notes tabs.
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-tab]").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll("[data-panel]").forEach((p) => p.classList.remove("active"));
      button.classList.add("active");
      const panel = document.querySelector(`[data-panel="${button.dataset.tab}"]`);
      if (panel) panel.classList.add("active");
    });
  });
  const firstPanel = document.querySelector("[data-panel]");
  if (firstPanel) firstPanel.classList.add("active");

  // Speaker rename.
  const renameForm = document.getElementById("rename-form");
  if (renameForm) {
    renameForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(renameForm);
      const url = `/meetings/${renameForm.dataset.id}/speaker?old=${encodeURIComponent(
        data.get("old")
      )}&new=${encodeURIComponent(data.get("new"))}`;
      const response = await fetch(url, { method: "POST" });
      if (response.ok) window.location.reload();
      else alert("Rename failed: " + (await response.text()));
    });
  }

  // Reprocess.
  const reprocess = document.getElementById("reprocess");
  if (reprocess) {
    reprocess.addEventListener("click", async () => {
      const response = await fetch(`/meetings/${reprocess.dataset.id}/reprocess`, {
        method: "POST",
      });
      alert(response.ok ? "Reprocessing queued." : "Reprocess failed.");
    });
  }
})();
