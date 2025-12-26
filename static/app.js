// static/app.js
(() => {
  const $ = (id) => document.getElementById(id);

  let currentPlan = null;

  function setStatus(msg) { $("status").textContent = msg; }

  function setText(id, value) { $(id).textContent = value ?? "—"; }

  $("btnPlan").addEventListener("click", async () => {
    setStatus("Planning...");
    currentPlan = null;
    $("plan").textContent = "";
    $("btnRun").disabled = true;

    const goal = $("goal").value.trim();
    const note_text = $("noteText").value.trim();

    const r = await fetch("/api/plan", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ goal, note_text })
    });

    const data = await r.json();
    if (!data.ok) {
      setStatus("Planner error.");
      $("plan").textContent = JSON.stringify(data, null, 2);
      return;
    }

    currentPlan = data.plan;
    $("plan").textContent = JSON.stringify(currentPlan, null, 2);
    $("btnRun").disabled = false;
    setStatus("Plan ready.");
  });

  $("btnRun").addEventListener("click", async () => {
    if (!currentPlan) return;

    setStatus("Running in Docker...");
    $("btnRun").disabled = true;

    // Clear output areas
    setText("runId", "—");
    setText("finalShot", "—");
    setText("finalUrl", "—");
    setText("visionSummary", "—");
    $("dom").textContent = "";
    $("steps").textContent = "";
    $("logs").textContent = "";

    const goal = $("goal").value.trim();
    const note_text = $("noteText").value.trim();

    const r = await fetch("/api/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ goal, note_text, plan: currentPlan })
    });

    const data = await r.json();

    setStatus(data.ok ? "Done." : "Run failed.");

    setText("runId", data.run_id);
    setText("finalShot", data.final_screenshot);
    setText("finalUrl", data?.result?.final_url);
    setText("visionSummary", data.vision_summary);

    $("dom").textContent = data?.result?.final_dom_preview
      ? data.result.final_dom_preview
      : JSON.stringify(data, null, 2);

    $("steps").textContent = JSON.stringify(data?.result?.steps || data, null, 2);
    $("logs").textContent = JSON.stringify(data?.logs || {}, null, 2);

    $("btnRun").disabled = false;
  });
})();

