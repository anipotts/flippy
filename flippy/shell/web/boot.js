// Start the app window: load the settings model, apply the window mode, show the route.
(async () => {
  "use strict";
  const F = window.F;
  F.call("mark", { name: "script" }).catch(() => {});
  F.state = await F.call("state");
  for (const p of F.state.pages) for (const f of p.fields) F.fields.set(f.id, f);
  document.getElementById("version").textContent = F.state.version ? `Flippy ${F.state.version}` : "Flippy";
  F.applyMode();
  const route = F.state.route || location.hash.slice(1) || "settings/general";
  if (location.hash.slice(1) !== route) history.replaceState(null, "", "#" + route);
  F.render(route);
  requestAnimationFrame(() => F.call("mark", { name: "painted" }).catch(() => {}));
})();
