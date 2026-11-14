// 3D cyberpunk robot DJ for the Party Mode deck stage.
// Builds a CSS 3D scene into #djRig and exposes window.djRig so app.js can
// sync it with the live mix (on-air state, BPM, transitions).
(function () {
  "use strict";

  const root = document.getElementById("djRig");
  if (!root) {
    return;
  }

  const SIDES = ["front", "back", "left", "right", "top", "bottom"];

  function el(tag, className, style) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (style) node.setAttribute("style", style);
    return node;
  }

  function add(parent, ...children) {
    for (const child of children) parent.appendChild(child);
    return parent;
  }

  // A solid box centered on its parent's origin. `faces` maps a side name to
  // extra markup for that face; `className` adds shading/material classes.
  function box(className, w, h, d, faces = {}) {
    const node = el("div", `dj-box ${className}`, `--w:${w}px;--h:${h}px;--d:${d}px`);
    for (const side of SIDES) {
      const face = el("div", `dj-f dj-${side}`);
      if (faces[side]) face.innerHTML = faces[side];
      node.appendChild(face);
    }
    return node;
  }

  // A transform node. Placement is static; animation goes on an inner node so
  // keyframes never fight with the placement transform.
  function at(x, y, z, extra = "", className = "") {
    return el("div", `dj-pos ${className}`, `transform:translate3d(${x}px,${y}px,${z}px) ${extra}`);
  }

  function anim(className) {
    return el("div", `dj-pos ${className}`);
  }

  // ---------- Backdrop (flat layers behind the 3D world) ----------
  const backdrop = el("div", "dj-backdrop");
  const skyline = el("div", "dj-skyline");
  const buildings = [
    [0, 46, 120], [44, 30, 170], [72, 58, 96], [128, 26, 210], [152, 48, 140],
    [198, 36, 182], [232, 62, 110], [292, 30, 236], [320, 54, 150], [372, 40, 196],
    [410, 70, 120], [478, 34, 220], [510, 52, 160], [560, 38, 128], [596, 60, 204],
    [654, 30, 150], [682, 56, 182], [736, 44, 118], [778, 34, 214], [810, 66, 140],
    [874, 40, 176], [912, 58, 120], [968, 32, 196],
  ];
  buildings.forEach(([left, width, height], index) => {
    const tower = el(
      "span",
      `dj-tower${index % 4 === 0 ? " lit" : ""}`,
      `left:${(left / 1000) * 100}%;width:${(width / 1000) * 100}%;height:${height}px`,
    );
    skyline.appendChild(tower);
  });

  const signA = el("div", "dj-sign dj-sign-a");
  signA.textContent = "BASS//NET";
  const signB = el("div", "dj-sign dj-sign-b");
  signB.textContent = "NEON//DJ";

  add(
    backdrop,
    el("div", "dj-sky"),
    skyline,
    signA,
    signB,
    el("div", "dj-beam b1"),
    el("div", "dj-beam b2"),
    el("div", "dj-beam b3"),
    el("div", "dj-beam b4"),
    el("div", "dj-beam b5"),
    el("div", "dj-beam b6"),
    el("div", "dj-halo"),
  );

  // ---------- 3D world ----------
  const viewport = el("div", "dj-viewport");
  const world = el("div", "dj-world");
  viewport.appendChild(world);

  // Floor grid and hologram rings, lying flat on the stage floor.
  const floorY = 136;
  add(
    world,
    add(at(0, floorY, 40, "rotateX(90deg)"), el("div", "dj-floor")),
    add(at(0, floorY - 1, -40, "rotateX(90deg)"), add(anim("dj-ring-spin dj-perf"), el("div", "dj-ring r1"))),
    add(at(0, floorY - 2, -40, "rotateX(90deg)"), add(anim("dj-ring-spin rev dj-perf"), el("div", "dj-ring r2"))),
  );

  // ---------- Robot ----------
  const robot = anim("dj-robot");
  const robotBody = anim("dj-bounce dj-perf");
  robot.appendChild(robotBody);

  const torsoFront = `
    <div class="dj-chest">
      <span class="dj-shoulder-line"></span>
      <div class="dj-core"><i></i></div>
      <span class="dj-serial">UNIT // DJ-07</span>
      <div class="dj-vents"><i></i><i></i><i></i><i></i></div>
      <span class="dj-hazard"></span>
    </div>`;
  const torsoSide = `<div class="dj-ribs"></div>`;
  const torsoBack = `<div class="dj-cables"><i></i><i></i><i></i></div>`;
  add(
    robotBody,
    add(at(0, -30, -60), box("dj-metal dj-torso", 140, 150, 80, { front: torsoFront, left: torsoSide, right: torsoSide, back: torsoBack })),
    add(at(0, 52, -60), box("dj-metal dj-dark", 104, 34, 64)),
    add(at(0, -114, -60), box("dj-metal dj-dark dj-neck", 34, 26, 34, { front: `<span class="dj-neck-glow"></span>` })),
  );

  // Shoulders
  [-1, 1].forEach((side) => {
    add(robotBody, add(at(side * 92, -88, -60), box("dj-metal dj-shoulder", 48, 42, 50, { front: `<span class="dj-pad-led"></span>`, top: `<span class="dj-pad-stripe"></span>` })));
  });

  // Head (pivots at the neck)
  const headFront = `
    <span class="dj-brow"></span>
    <div class="dj-visor"><span class="dj-scan"></span><span class="dj-eye l"></span><span class="dj-eye r"></span></div>
    <div class="dj-grill"><i></i><i></i><i></i><i></i><i></i></div>
    <span class="dj-cheek l"></span><span class="dj-cheek r"></span>`;
  const headSide = `<div class="dj-circuit"></div><span class="dj-side-led"></span>`;
  const headJoint = at(0, -126, -60);
  const headAnim = anim("dj-head-bob dj-perf");
  const cup = `<span class="dj-cup-ring"></span>`;
  add(
    headAnim,
    add(at(0, -46, 0), box("dj-metal dj-head", 104, 92, 92, { front: headFront, left: headSide, right: headSide, top: `<span class="dj-top-seam"></span>` })),
    add(at(0, -95, 0), box("dj-metal dj-dark", 128, 12, 24)),
    add(at(0, -104, 0), box("dj-neon-fin", 8, 22, 74)),
    add(at(-62, -42, 0), box("dj-metal dj-cup", 22, 54, 52, { left: cup, right: cup })),
    add(at(62, -42, 0), box("dj-metal dj-cup", 22, 54, 52, { left: cup, right: cup })),
    add(at(-62, -6, 22, "rotateY(-18deg)"), box("dj-metal dj-dark", 6, 6, 50)),
    add(at(-56, 4, 50), box("dj-mic", 12, 8, 10)),
    add(at(38, -110, -22), box("dj-metal dj-dark", 4, 36, 4)),
    add(at(38, -130, -22), box("dj-antenna-tip", 9, 9, 9)),
  );
  add(robotBody, add(headJoint, headAnim));

  // Arms: shoulder joint > upper arm > elbow joint > forearm > hand
  function arm(side) {
    const name = side < 0 ? "l" : "r";
    const joint = at(side * 92, -82, -60);
    const upper = anim(`dj-upper ${name} dj-perf`);
    const elbow = at(0, 96, 0);
    const fore = anim(`dj-fore ${name} dj-perf`);
    add(
      fore,
      add(at(0, 0, 0), box("dj-metal dj-dark", 32, 32, 32)),
      add(at(0, 52, 0), box("dj-metal dj-forearm", 26, 96, 26, { front: `<span class="dj-arm-stripe"></span>`, left: `<span class="dj-arm-stripe"></span>`, right: `<span class="dj-arm-stripe"></span>` })),
      add(at(0, 96, 0), box("dj-cuff", 30, 8, 30)),
      add(at(0, 114, 4), box("dj-metal dj-hand", 34, 28, 40, { front: `<span class="dj-knuckles"></span>`, bottom: `<span class="dj-palm-glow"></span>` })),
    );
    add(
      upper,
      add(at(0, 48, 0), box("dj-metal dj-upperarm", 30, 96, 30, { front: `<span class="dj-arm-stripe"></span>` })),
      add(elbow, fore),
    );
    return add(joint, upper);
  }
  add(robotBody, arm(-1), arm(1));
  world.appendChild(robot);

  // ---------- Booth ----------
  const platter = (name) => `
    <div class="dj-platter ${name}">
      <div class="dj-platter-ring"></div>
      <div class="dj-vinyl dj-perf"><div class="dj-vinyl-scratch dj-perf"><span class="dj-vinyl-label"></span><span class="dj-vinyl-mark"></span></div></div>
      <span class="dj-vinyl-sheen"></span>
    </div>
    <span class="dj-tonearm ${name}"></span>`;
  const deckTop = `
    <div class="dj-deck-top">
      ${platter("l")}
      <div class="dj-mixer">
        <span class="dj-knob" style="left:16px;top:12px"></span>
        <span class="dj-knob tw dj-perf" style="left:16px;top:42px"></span>
        <span class="dj-knob" style="left:16px;top:72px"></span>
        <span class="dj-knob tw dj-perf" style="right:16px;top:12px;animation-delay:-1s"></span>
        <span class="dj-knob" style="right:16px;top:42px"></span>
        <span class="dj-knob tw dj-perf" style="right:16px;top:72px;animation-delay:-.5s"></span>
        <span class="dj-meter dj-perf" style="left:56px"></span>
        <span class="dj-meter b dj-perf" style="left:76px"></span>
        <span class="dj-ftrack" style="left:26px"><i class="dj-perf"></i></span>
        <span class="dj-ftrack" style="right:26px"><i class="dj-perf" style="animation-delay:-1s"></i></span>
        <span class="dj-xtrack"><i class="dj-perf"></i></span>
      </div>
      ${platter("r")}
    </div>`;
  const deckFront = `
    <div class="dj-booth-front">
      <span class="dj-booth-strip"></span>
      <span class="dj-booth-hazard l"></span>
      <span class="dj-booth-hazard r"></span>
      <strong class="dj-booth-word">AI&nbsp;·&nbsp;DJ</strong>
      <span class="dj-booth-leds dj-perf"></span>
      <span class="dj-booth-grid"></span>
    </div>`;
  add(world, add(at(0, 95, 70), box("dj-metal dj-booth", 560, 82, 170, { top: deckTop, front: deckFront })));

  // ---------- Overlays ----------
  const hud = el("div", "dj-hud");
  hud.innerHTML = `
    <div class="dj-hud-tag"><span class="dj-hud-dot"></span><span data-dj="status">Standby</span></div>
    <div class="dj-hud-bpm"><strong data-dj="bpm">--</strong><span>BPM</span></div>
    <div class="dj-hud-ticker" data-dj="ticker">Waiting for a set</div>`;

  add(root, backdrop, viewport, el("div", "dj-rain"), el("div", "dj-scanlines"), el("div", "dj-flash"), hud);

  // ---------- Live sync ----------
  const stage = root.closest(".deck-stage") || root;
  const statusNode = hud.querySelector('[data-dj="status"]');
  const bpmNode = hud.querySelector('[data-dj="bpm"]');
  const tickerNode = hud.querySelector('[data-dj="ticker"]');
  const liveLines = ["Scratching deck A", "Riding the filter", "Cutting the lows", "Reading the room", "Lining up the drop"];
  let tickerTimer = null;
  let tickerIndex = 0;
  let pulseTimer = null;

  function setTicker(live) {
    if (live && !tickerTimer) {
      tickerNode.textContent = liveLines[0];
      tickerTimer = setInterval(() => {
        tickerIndex = (tickerIndex + 1) % liveLines.length;
        tickerNode.textContent = liveLines[tickerIndex];
      }, 2600);
    } else if (!live && tickerTimer) {
      clearInterval(tickerTimer);
      tickerTimer = null;
    }
    if (!live) tickerNode.textContent = "Waiting for a set";
  }

  window.djRig = {
    update({ live = false, bpm = null } = {}) {
      const tempo = Number(bpm) > 40 && Number(bpm) < 220 ? Number(bpm) : 124;
      stage.style.setProperty("--dj-beat", `${(60 / tempo).toFixed(3)}s`);
      bpmNode.textContent = bpm ? String(Math.round(tempo)) : "--";
      statusNode.textContent = live ? "On air" : "Standby";
      setTicker(live);
    },
    pulse(label) {
      stage.classList.remove("dj-drop");
      // Force a reflow so the flash animation restarts on back-to-back transitions.
      void stage.offsetWidth;
      stage.classList.add("dj-drop");
      if (label) tickerNode.textContent = label;
      clearTimeout(pulseTimer);
      pulseTimer = setTimeout(() => stage.classList.remove("dj-drop"), 2600);
    },
  };
})();
