// VolRider 网页前端：音量状态轮询。
// 后端见 web/server.py。2026-10-25 起均衡器功能已整块删掉，只做响度均衡。

const $ = (id) => document.getElementById(id);

async function postCommand(cmd) {
  try {
    await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cmd),
    });
  } catch (e) { /* 后端断开时静默，下次轮询恢复 */ }
}

// ---------------------------------------------------------------- 音量部分

const appRows = new Map();
let masterDragging = false;
let lastDeviceNames = "";
let lastDevices = [];

function fmtPct(v) {
  return Math.round(v * 100) + "%";
}

function ensureAppRow(name) {
  if (appRows.has(name)) return appRows.get(name);
  const row = document.createElement("div");
  row.className = "app-row";
  row.innerHTML =
    '<span class="app-name"></span>' +
    '<div class="bar"><div class="bar-fill"></div><div class="bar-marker"></div></div>' +
    '<span class="app-pct peak-pct"></span>' +
    '<input class="app-vol" type="range" min="0" max="100" step="1" value="100">' +
    '<span class="app-pct vol-pct"></span>' +
    '<label><input class="app-auto" type="checkbox" checked> 自动</label>';
  row.querySelector(".app-name").textContent = name;
  const slider = row.querySelector(".app-vol");
  const autoCb = row.querySelector(".app-auto");
  const rec = {
    el: row,
    fill: row.querySelector(".bar-fill"),
    marker: row.querySelector(".bar-marker"),
    peakLabel: row.querySelector(".peak-pct"),
    volLabel: row.querySelector(".vol-pct"),
    slider: slider,
    autoCb: autoCb,
    dragging: false,
    lastUserAuto: 0,
  };
  slider.addEventListener("pointerdown", () => { rec.dragging = true; });
  slider.addEventListener("pointerup", () => { rec.dragging = false; });
  slider.addEventListener("change", () => { rec.dragging = false; });
  slider.addEventListener("input", () => {
    const v = parseFloat(slider.value) / 100;
    rec.volLabel.textContent = fmtPct(v);
    postCommand({ type: "session_volume", name: name, value: v });
  });
  autoCb.addEventListener("change", () => {
    rec.lastUserAuto = Date.now();
    postCommand({ type: "auto_app", name: name, value: autoCb.checked });
  });
  $("app-list").appendChild(row);
  appRows.set(name, rec);
  return rec;
}

function renderState(s) {
  const badge = $("mode-badge");
  if (s.mode === "mock") {
    badge.textContent = "演示模式（模拟数据）";
    badge.className = "badge mock";
  } else {
    badge.textContent = "真实音频";
    badge.className = "badge real";
  }

  // 设备下拉：用户正在选时不打断
  const select = $("device-select");
  const names = (s.devices || []).map((d) => d.name);
  if (JSON.stringify(names) !== lastDeviceNames) {
    lastDeviceNames = JSON.stringify(names);
    lastDevices = s.devices || [];
    select.innerHTML = "";
    for (const d of lastDevices) {
      const opt = document.createElement("option");
      opt.value = d.id;
      opt.textContent = d.name;
      select.appendChild(opt);
    }
  }
  if (document.activeElement !== select) {
    const def = (s.devices || []).find((d) => d.id === s.default_device);
    if (def) select.value = def.id;
  }

  // 总音量
  const masterSlider = $("master-slider");
  if (!masterDragging) {
    masterSlider.value = Math.round(s.master * 100);
    $("master-label").textContent = fmtPct(s.master);
  }

  // 开关类：直接同步（500ms 内用户刚点的跳过，避免回闪）
  const now = Date.now();
  const enabledCb = $("enabled-check");
  if (!enabledCb.dataset.userSet || now - parseInt(enabledCb.dataset.userSet, 10) > 500) {
    enabledCb.checked = !!s.enabled;
  }
  const autoStartCb = $("autostart-check");
  if (!autoStartCb.dataset.userSet || now - parseInt(autoStartCb.dataset.userSet, 10) > 500) {
    autoStartCb.checked = !!s.autostart;
  }
  const targetSlider = $("target-slider");
  if (document.activeElement !== targetSlider) {
    targetSlider.value = Math.round(s.target * 100);
    $("target-label").textContent = fmtPct(s.target);
  }

  // 应用行
  const sessionNames = (s.sessions || []).map((x) => x.name);
  for (const old of Array.from(appRows.keys())) {
    if (!sessionNames.includes(old)) {
      appRows.get(old).el.remove();
      appRows.delete(old);
    }
  }
  $("app-empty").style.display = sessionNames.length ? "none" : "block";
  for (const sess of s.sessions || []) {
    const rec = ensureAppRow(sess.name);
    const effective = Math.min(1, Math.max(0, sess.smooth * s.master));
    rec.fill.style.width = effective * 100 + "%";
    rec.marker.style.left = Math.min(100, s.reference * s.master * 100) + "%";
    rec.peakLabel.textContent = fmtPct(effective);
    if (!rec.dragging) {
      if (Math.abs(parseFloat(rec.slider.value) - sess.volume * 100) > 1) {
        rec.slider.value = Math.round(sess.volume * 100);
      }
      rec.volLabel.textContent = fmtPct(sess.volume);
    }
    if (now - rec.lastUserAuto > 500) {
      rec.autoCb.checked = !!sess.auto;
    }
  }

  if (s.error) {
    $("status").textContent = "读取失败：" + s.error;
  } else if (s.events && s.events.length) {
    $("status").textContent = s.events[s.events.length - 1];
  }
}

async function poll() {
  try {
    const r = await fetch("/api/state");
    const s = await r.json();
    renderState(s);
  } catch (e) {
    $("status").textContent = "后端连接失败，正在重试…";
  }
}

$("master-slider").addEventListener("pointerdown", () => { masterDragging = true; });
$("master-slider").addEventListener("pointerup", () => { masterDragging = false; });
$("master-slider").addEventListener("change", () => { masterDragging = false; });
$("master-slider").addEventListener("input", (e) => {
  const v = parseFloat(e.target.value) / 100;
  $("master-label").textContent = fmtPct(v);
  postCommand({ type: "master_volume", value: v });
});
$("target-slider").addEventListener("input", (e) => {
  const v = parseFloat(e.target.value) / 100;
  $("target-label").textContent = fmtPct(v);
  postCommand({ type: "target", value: v });
});
$("enabled-check").addEventListener("change", (e) => {
  e.target.dataset.userSet = String(Date.now());
  postCommand({ type: "enabled", value: e.target.checked });
});
$("autostart-check").addEventListener("change", (e) => {
  e.target.dataset.userSet = String(Date.now());
  postCommand({ type: "autostart", value: e.target.checked });
});
$("device-set").addEventListener("click", () => {
  const select = $("device-select");
  const id = select.value;
  const dev = lastDevices.find((d) => d.id === id);
  if (dev) postCommand({ type: "default_device", device_id: id, device_name: dev.name });
});

// ---------------------------------------------------------------- 启动

poll();
setInterval(poll, 150);
