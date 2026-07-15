const selectedFiles = new Map();
const selectedLibraryTracks = new Map();
const analyzedTracks = new Map();
const liveQueue = [];

let liveSession = null;
let draggedQueueId = null;

const els = {
  dropZone: document.getElementById("dropZone"),
  fileInput: document.getElementById("fileInput"),
  folderInput: document.getElementById("folderInput"),
  chooseFilesButton: document.getElementById("chooseFilesButton"),
  chooseFolderButton: document.getElementById("chooseFolderButton"),
  clearButton: document.getElementById("clearButton"),
  liveMixButton: document.getElementById("liveMixButton"),
  transitionNowButton: document.getElementById("transitionNowButton"),
  stopLiveButton: document.getElementById("stopLiveButton"),
  downloadMixButton: document.getElementById("downloadMixButton"),
  loadLibraryButton: document.getElementById("loadLibraryButton"),
  catalogSearchButton: document.getElementById("catalogSearchButton"),
  catalogSearch: document.getElementById("catalogSearch"),
  catalogResults: document.getElementById("catalogResults"),
  mixDirection: document.getElementById("mixDirection"),
  autoOrder: document.getElementById("autoOrder"),
  useSfx: document.getElementById("useSfx"),
  targetMinutes: document.getElementById("targetMinutes"),
  playSeconds: document.getElementById("playSeconds"),
  transitionSeconds: document.getElementById("transitionSeconds"),
  fileList: document.getElementById("fileList"),
  trackList: document.getElementById("trackList"),
  queueList: document.getElementById("queueList"),
  fileCount: document.getElementById("fileCount"),
  trackCount: document.getElementById("trackCount"),
  queueCount: document.getElementById("queueCount"),
  statusText: document.getElementById("statusText"),
  progressBar: document.getElementById("progressBar"),
  playerPanel: document.getElementById("playerPanel"),
  liveNow: document.getElementById("liveNow"),
  mixPlayer: document.getElementById("mixPlayer"),
  downloadLink: document.getElementById("downloadLink"),
  mixName: document.getElementById("mixName"),
  mixLength: document.getElementById("mixLength"),
  mixStatus: document.getElementById("mixStatus"),
  errorPanel: document.getElementById("errorPanel"),
  errorList: document.getElementById("errorList"),
};

els.chooseFilesButton.addEventListener("click", () => els.fileInput.click());
els.chooseFolderButton.addEventListener("click", () => els.folderInput.click());
els.clearButton.addEventListener("click", clearAll);
els.stopLiveButton.addEventListener("click", stopLiveMix);
els.transitionNowButton.addEventListener("click", () => transitionToNextTrack(true));
els.liveMixButton.addEventListener("click", () => makeMix({ live: true }));
els.downloadMixButton.addEventListener("click", () => makeMix({ live: false }));
els.loadLibraryButton.addEventListener("click", () => searchCatalog(""));
els.catalogSearchButton.addEventListener("click", () => searchCatalog(els.catalogSearch.value));
els.catalogSearch.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchCatalog(els.catalogSearch.value);
  }
});

els.fileInput.addEventListener("change", () => {
  addFiles(Array.from(els.fileInput.files || []));
  els.fileInput.value = "";
});

els.folderInput.addEventListener("change", () => {
  addFiles(Array.from(els.folderInput.files || []));
  els.folderInput.value = "";
});

["dragenter", "dragover"].forEach((eventName) => {
  els.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    els.dropZone.classList.add("dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  els.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    els.dropZone.classList.remove("dragging");
  });
});

els.dropZone.addEventListener("drop", async (event) => {
  setStatus("Reading dropped files", 8);
  const files = await filesFromDrop(event.dataTransfer);
  addFiles(files);
});

els.dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    els.fileInput.click();
  }
});

function addFiles(files) {
  const mp3s = files.filter((file) => file.name.toLowerCase().endsWith(".mp3"));
  for (const file of mp3s) {
    const key = fileKey(file);
    selectedFiles.set(key, file);
    ensureQueueItem({
      id: `file:${key}`,
      type: "file",
      key,
      name: file.webkitRelativePath || file.name,
      meta: formatBytes(file.size),
    });
  }
  renderFiles();
  renderQueue();
  clearErrors();
  setStatus(mp3s.length ? "Files ready" : "No MP3 files found", mp3s.length ? 16 : 0);
}

function fileKey(file) {
  return `${file.webkitRelativePath || file.name}:${file.size}:${file.lastModified}`;
}

async function filesFromDrop(dataTransfer) {
  const items = Array.from(dataTransfer.items || []);
  const entryItems = items
    .map((item) => (typeof item.webkitGetAsEntry === "function" ? item.webkitGetAsEntry() : null))
    .filter(Boolean);

  if (entryItems.length) {
    const nested = await Promise.all(entryItems.map(readEntry));
    return nested.flat();
  }

  return Array.from(dataTransfer.files || []);
}

async function readEntry(entry) {
  if (entry.isFile) {
    return new Promise((resolve) => {
      entry.file((file) => resolve([file]), () => resolve([]));
    });
  }

  if (!entry.isDirectory) {
    return [];
  }

  const reader = entry.createReader();
  const children = [];
  while (true) {
    const batch = await new Promise((resolve) => {
      reader.readEntries(resolve, () => resolve([]));
    });
    if (!batch.length) {
      break;
    }
    children.push(...batch);
  }

  const nested = await Promise.all(children.map(readEntry));
  return nested.flat();
}

async function searchCatalog(query) {
  try {
    setStatus("Searching library", 12);
    const params = query.trim() ? `?query=${encodeURIComponent(query.trim())}` : "";
    const results = await fetchJson(`/api/tracks/search${params}`);
    renderCatalogResults(results);
    setStatus(results.length ? "Library results ready" : "No saved matches", results.length ? 20 : 0);
  } catch (error) {
    showErrors([{ file_name: "Search", error: error.message || "Library search failed." }]);
  }
}

function renderCatalogResults(results) {
  els.catalogResults.innerHTML = "";
  if (!results.length) {
    const item = document.createElement("li");
    item.className = "catalog-item";
    item.innerHTML = `
      <div>
        <strong>No saved tracks found</strong>
        <div class="catalog-meta">Analyze tracks first, or connect a licensed provider later.</div>
      </div>
    `;
    els.catalogResults.appendChild(item);
    return;
  }

  for (const track of results) {
    const item = document.createElement("li");
    item.className = "catalog-item";
    const isSelected = selectedLibraryTracks.has(track.track_id);
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(track.title || track.file_name)}</strong>
        <div class="catalog-meta">${formatBpm(track.estimated_bpm)} - ${escapeHtml(track.key?.display_name || "Unknown key")} - ${formatDuration(track.duration_seconds)}</div>
      </div>
      <button type="button" class="small-button">${isSelected ? "Added" : "Add"}</button>
    `;
    const button = item.querySelector("button");
    button.disabled = isSelected;
    button.addEventListener("click", () => addLibraryTrack(track, results));
    els.catalogResults.appendChild(item);
  }
}

function addLibraryTrack(track, catalogResults) {
  selectedLibraryTracks.set(track.track_id, track);
  ensureQueueItem({
    id: `track:${track.track_id}`,
    type: "track",
    trackId: track.track_id,
    name: track.title || track.file_name,
    meta: `${formatBpm(track.estimated_bpm)} - ${track.key?.display_name || "Unknown key"}`,
  });
  renderTracks();
  renderQueue();
  renderCatalogResults(catalogResults);
  setStatus("Track added to queue", 24);
}

function ensureQueueItem(item) {
  if (!liveQueue.some((queued) => queued.id === item.id)) {
    liveQueue.push(item);
  }
}

function renderFiles() {
  const files = Array.from(selectedFiles.values());
  els.fileCount.textContent = `${files.length} file${files.length === 1 ? "" : "s"}`;
  els.fileList.innerHTML = "";

  if (!files.length) {
    els.fileList.appendChild(emptyItem("No files selected yet."));
    return;
  }

  for (const file of files) {
    const item = document.createElement("li");
    item.className = "file-item";
    item.innerHTML = `
      <strong>${escapeHtml(file.webkitRelativePath || file.name)}</strong>
      <span class="file-meta">${formatBytes(file.size)}</span>
    `;
    els.fileList.appendChild(item);
  }
}

function renderTracks() {
  const tracks = selectedTrackSummaries();
  els.trackList.innerHTML = "";

  for (const track of tracks) {
    const item = document.createElement("li");
    item.className = "track-item";
    item.innerHTML = `
      <strong>${escapeHtml(track.title || track.file_name)}</strong>
      <div class="track-meta">
        <span>${formatBpm(track.estimated_bpm)}</span>
        <span>${escapeHtml(track.key?.display_name || "Unknown key")}</span>
        <span>${formatDuration(track.duration_seconds)}</span>
        <span>Energy ${formatEnergy(track.overall_rms_energy)}</span>
      </div>
    `;
    els.trackList.appendChild(item);
  }

  els.trackCount.textContent = `${tracks.length} track${tracks.length === 1 ? "" : "s"}`;
  if (!tracks.length) {
    els.trackList.appendChild(emptyItem("No tracks selected yet."));
  }
}

function renderQueue() {
  els.queueList.innerHTML = "";
  els.queueCount.textContent = `${liveQueue.length} queued`;

  if (!liveQueue.length) {
    els.queueList.appendChild(emptyItem("Drop tracks or add saved songs to build the live queue."));
    return;
  }

  const currentId = liveSession?.currentItemId || null;
  for (const item of liveQueue) {
    const row = document.createElement("li");
    row.className = `queue-item${item.id === currentId ? " current" : ""}`;
    row.draggable = true;
    row.dataset.queueId = item.id;
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(item.name)}</strong>
        <div class="queue-meta">${escapeHtml(item.meta || item.type)}</div>
      </div>
      <div class="queue-actions">
        <button type="button" data-action="next">Play Next</button>
        <button type="button" data-action="remove">Remove</button>
      </div>
    `;
    row.addEventListener("dragstart", handleQueueDragStart);
    row.addEventListener("dragover", handleQueueDragOver);
    row.addEventListener("drop", handleQueueDrop);
    row.addEventListener("dragend", handleQueueDragEnd);
    row.querySelector('[data-action="next"]').addEventListener("click", () => cueQueueItemNext(item.id));
    row.querySelector('[data-action="remove"]').addEventListener("click", () => removeQueueItem(item.id));
    els.queueList.appendChild(row);
  }
}

function handleQueueDragStart(event) {
  draggedQueueId = event.currentTarget.dataset.queueId;
  event.currentTarget.classList.add("dragging");
}

function handleQueueDragOver(event) {
  event.preventDefault();
}

function handleQueueDrop(event) {
  event.preventDefault();
  const targetId = event.currentTarget.dataset.queueId;
  if (!draggedQueueId || draggedQueueId === targetId) {
    return;
  }
  moveQueueItemBefore(draggedQueueId, targetId);
}

function handleQueueDragEnd(event) {
  event.currentTarget.classList.remove("dragging");
  draggedQueueId = null;
}

function moveQueueItemBefore(itemId, targetId) {
  const fromIndex = liveQueue.findIndex((item) => item.id === itemId);
  const toIndex = liveQueue.findIndex((item) => item.id === targetId);
  if (fromIndex < 0 || toIndex < 0) {
    return;
  }
  const [item] = liveQueue.splice(fromIndex, 1);
  const adjustedIndex = liveQueue.findIndex((queued) => queued.id === targetId);
  liveQueue.splice(adjustedIndex, 0, item);
  syncLiveDecodedOrder();
  renderQueue();
}

function cueQueueItemNext(itemId) {
  const index = liveQueue.findIndex((item) => item.id === itemId);
  if (index < 0) {
    return;
  }

  const [item] = liveQueue.splice(index, 1);
  const currentIndex = liveQueue.findIndex((queued) => queued.id === liveSession?.currentItemId);
  liveQueue.splice(currentIndex >= 0 ? currentIndex + 1 : 0, 0, item);
  syncLiveDecodedOrder();
  renderQueue();
  setStatus("Next song cued", liveSession?.playing ? 48 : 24);
}

function removeQueueItem(itemId) {
  const index = liveQueue.findIndex((item) => item.id === itemId);
  if (index < 0) {
    return;
  }
  liveQueue.splice(index, 1);
  selectedLibraryTracks.delete(itemId.replace("track:", ""));
  syncLiveDecodedOrder();
  renderTracks();
  renderQueue();
}

function syncLiveDecodedOrder() {
  if (!liveSession?.decodedQueue?.length) {
    return;
  }
  const byId = new Map(liveSession.decodedQueue.map((item) => [item.queueId, item]));
  const current = liveSession.currentItemId ? byId.get(liveSession.currentItemId) : null;
  const ordered = liveQueue.map((item) => byId.get(item.id)).filter(Boolean);
  liveSession.decodedQueue = ordered;
  liveSession.currentIndex = current ? ordered.findIndex((item) => item.queueId === current.queueId) : -1;
}

function selectedTrackSummaries() {
  const combined = new Map();
  for (const [trackId, track] of selectedLibraryTracks) {
    combined.set(trackId, track);
  }
  for (const [trackId, track] of analyzedTracks) {
    combined.set(trackId, track);
  }
  return Array.from(combined.values());
}

async function makeMix({ live }) {
  if (liveQueue.length < 2) {
    showErrors([{ file_name: "Selection", error: "Queue at least two MP3 files or saved tracks." }]);
    setStatus("Add more tracks", 0);
    return;
  }

  toggleBusy(true);
  clearErrors();
  if (!live) {
    stopLiveMix();
    hidePlayer();
  }

  if (live) {
    startBrowserLiveMix(liveQueue.slice()).catch((error) => {
      showErrors([{ file_name: "Live Mix", error: error.message || "Live playback could not start." }]);
    });
  }

  try {
    analyzedTracks.clear();
    const fileItems = liveQueue.filter((item) => item.type === "file");
    const fileTrackIdsByQueueId = new Map();

    if (fileItems.length) {
      setStatus(live ? "Live playing, analyzing files" : "Uploading and analyzing", 32);
      const files = fileItems.map((item) => selectedFiles.get(item.key)).filter(Boolean);
      const batch = await analyzeFiles(files);
      showErrors(batch.errors || []);
      const batchTracks = batch.tracks || [];
      for (let index = 0; index < fileItems.length; index += 1) {
        if (batchTracks[index]?.track_id) {
          fileTrackIdsByQueueId.set(fileItems[index].id, batchTracks[index].track_id);
        }
      }
    }

    const trackIds = unique(
      liveQueue
        .map((item) => (item.type === "track" ? item.trackId : fileTrackIdsByQueueId.get(item.id)))
        .filter(Boolean),
    );
    if (trackIds.length < 2) {
      throw new Error("At least two unique analyzed tracks are needed for a mix.");
    }

    setStatus(live ? "Live playing, planning render" : "Loading track details", 52);
    const tracks = await Promise.all(trackIds.map(fetchTrack));
    for (const track of tracks) {
      analyzedTracks.set(track.track_id, track);
    }
    renderTracks();

    setStatus(live ? "Live playing, polishing transitions" : "Planning transitions", 68);
    const plan = await createPlan(trackIds);

    setStatus(live ? "Live playing, rendering download" : "Rendering audio", 84);
    const record = await renderMix(plan.mix_id);

    setStatus(live ? "Live mix playing. Download ready." : "Mix ready", 100);
    showPlayer(record, !live);
  } catch (error) {
    setStatus(live && liveSession?.playing ? "Live playing, render stopped" : "Stopped", live ? 34 : 0);
    showErrors([{ file_name: "Mix", error: error.message || "Something went wrong." }]);
  } finally {
    toggleBusy(false);
  }
}

async function startBrowserLiveMix(queueItems) {
  const sources = queueItems.map(sourceFromQueueItem).filter(Boolean);
  if (sources.length < 2) {
    return;
  }

  stopLiveMix();
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    throw new Error("This browser does not support live audio mixing.");
  }

  const context = new AudioContextClass();
  liveSession = {
    context,
    decodedQueue: [],
    currentIndex: -1,
    currentItemId: null,
    currentSource: null,
    currentGain: null,
    timers: [],
    playing: false,
    transitioning: false,
    segmentSeconds: numericValue(els.playSeconds, 75),
    transitionSeconds: numericValue(els.transitionSeconds, 10),
    withSfx: els.useSfx.checked,
  };
  els.playerPanel.classList.remove("hidden");
  els.liveNow.classList.remove("hidden");
  els.stopLiveButton.disabled = false;
  els.transitionNowButton.disabled = false;

  setStatus("Loading live deck", 18);
  for (let index = 0; index < sources.length; index += 1) {
    setStatus(`Loading live track ${index + 1} of ${sources.length}`, 20 + index * 6);
    const arrayBuffer = await sources[index].loadArrayBuffer();
    const buffer = await context.decodeAudioData(arrayBuffer.slice(0));
    liveSession.decodedQueue.push({
      queueId: sources[index].queueId,
      name: sources[index].name,
      buffer,
    });
  }

  playLiveTrackAtIndex(0, 0.8);
  setStatus("Live deck playing", 42);
}

function sourceFromQueueItem(item) {
  if (item.type === "file") {
    const file = selectedFiles.get(item.key);
    if (!file) {
      return null;
    }
    return {
      queueId: item.id,
      name: item.name,
      loadArrayBuffer: () => file.arrayBuffer(),
    };
  }

  if (item.type === "track") {
    return {
      queueId: item.id,
      name: item.name,
      loadArrayBuffer: async () => {
        const response = await fetch(`/api/tracks/${encodeURIComponent(item.trackId)}/audio`);
        if (!response.ok) {
          throw new Error(`Could not load ${item.name}.`);
        }
        return response.arrayBuffer();
      },
    };
  }

  return null;
}

function playLiveTrackAtIndex(index, fadeInSeconds) {
  if (!liveSession || index < 0 || index >= liveSession.decodedQueue.length) {
    stopLiveMix();
    return;
  }

  clearLiveTimers();
  const { context, decodedQueue } = liveSession;
  const track = decodedQueue[index];
  const now = context.currentTime + 0.05;
  const duration = liveTrackWindow(track.buffer.duration);
  const source = context.createBufferSource();
  const gain = context.createGain();

  source.buffer = track.buffer;
  source.connect(gain).connect(context.destination);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.linearRampToValueAtTime(1.0, now + Math.min(fadeInSeconds, 2.0));
  source.start(now, 0, duration + liveSession.transitionSeconds + 0.2);

  liveSession.currentIndex = index;
  liveSession.currentItemId = track.queueId;
  liveSession.currentSource = source;
  liveSession.currentGain = gain;
  liveSession.playing = true;
  liveSession.transitioning = false;

  source.addEventListener("ended", () => {
    if (liveSession?.currentSource === source && !liveSession.transitioning) {
      transitionToNextTrack(false);
    }
  });

  const autoMs = Math.max(1000, duration * 1000);
  liveSession.timers.push(window.setTimeout(() => transitionToNextTrack(false), autoMs));
  renderQueue();
}

function liveTrackWindow(bufferDuration) {
  const segment = Math.max(15, numericValue(els.playSeconds, liveSession?.segmentSeconds || 75));
  const transition = Math.max(2, numericValue(els.transitionSeconds, liveSession?.transitionSeconds || 10));
  return Math.max(4, Math.min(segment, Math.max(4, bufferDuration - transition)));
}

function transitionToNextTrack(manual) {
  if (!liveSession || liveSession.transitioning) {
    return;
  }

  const nextIndex = liveSession.currentIndex + 1;
  if (nextIndex >= liveSession.decodedQueue.length) {
    if (manual) {
      setStatus("No next track queued", 45);
    }
    return;
  }

  clearLiveTimers();
  liveSession.transitioning = true;
  const { context } = liveSession;
  const now = context.currentTime + 0.05;
  const transition = Math.max(2, numericValue(els.transitionSeconds, liveSession.transitionSeconds));
  const nextTrack = liveSession.decodedQueue[nextIndex];
  const nextSource = context.createBufferSource();
  const nextGain = context.createGain();

  nextSource.buffer = nextTrack.buffer;
  nextSource.connect(nextGain).connect(context.destination);
  nextGain.gain.setValueAtTime(0.0001, now);
  nextGain.gain.linearRampToValueAtTime(1.0, now + transition);
  nextSource.start(now, 0, liveTrackWindow(nextTrack.buffer.duration) + transition + 0.2);

  if (liveSession.currentGain) {
    liveSession.currentGain.gain.cancelScheduledValues(now);
    liveSession.currentGain.gain.setValueAtTime(Math.max(liveSession.currentGain.gain.value, 0.0001), now);
    liveSession.currentGain.gain.linearRampToValueAtTime(0.0001, now + transition);
  }
  if (liveSession.currentSource) {
    const oldSource = liveSession.currentSource;
    liveSession.timers.push(
      window.setTimeout(() => {
        try {
          oldSource.stop();
        } catch {
          // Source may already be stopped.
        }
      }, transition * 1000 + 80),
    );
  }

  if (liveSession.withSfx) {
    scheduleBrowserSfx(context, now, transition);
  }

  liveSession.currentIndex = nextIndex;
  liveSession.currentItemId = nextTrack.queueId;
  liveSession.currentSource = nextSource;
  liveSession.currentGain = nextGain;
  liveSession.transitioning = false;
  const nextWindow = liveTrackWindow(nextTrack.buffer.duration);
  liveSession.timers.push(window.setTimeout(() => transitionToNextTrack(false), Math.max(1000, nextWindow * 1000)));
  setStatus(manual ? "Manual transition" : "Auto transition", 52);
  renderQueue();
}

function scheduleBrowserSfx(context, transitionStart, transitionSeconds) {
  const sweepDuration = Math.max(0.8, Math.min(transitionSeconds, 7.5));
  const sweep = context.createOscillator();
  const sweepGain = context.createGain();
  sweep.type = "sawtooth";
  sweep.frequency.setValueAtTime(420, transitionStart);
  sweep.frequency.exponentialRampToValueAtTime(4200, transitionStart + sweepDuration);
  sweepGain.gain.setValueAtTime(0.0001, transitionStart);
  sweepGain.gain.linearRampToValueAtTime(0.035, transitionStart + sweepDuration * 0.65);
  sweepGain.gain.exponentialRampToValueAtTime(0.0001, transitionStart + sweepDuration);
  sweep.connect(sweepGain).connect(context.destination);
  sweep.start(transitionStart);
  sweep.stop(transitionStart + sweepDuration + 0.05);
  liveSession?.timers.push(window.setTimeout(() => sweep.disconnect(), (sweepDuration + 0.2) * 1000));

  const impactTime = transitionStart + transitionSeconds - 0.04;
  const impact = context.createOscillator();
  const impactGain = context.createGain();
  impact.type = "sine";
  impact.frequency.setValueAtTime(72, impactTime);
  impact.frequency.exponentialRampToValueAtTime(42, impactTime + 0.42);
  impactGain.gain.setValueAtTime(0.12, impactTime);
  impactGain.gain.exponentialRampToValueAtTime(0.0001, impactTime + 0.42);
  impact.connect(impactGain).connect(context.destination);
  impact.start(impactTime);
  impact.stop(impactTime + 0.48);
}

function clearLiveTimers() {
  if (!liveSession) {
    return;
  }
  for (const timer of liveSession.timers) {
    window.clearTimeout(timer);
  }
  liveSession.timers = [];
}

function stopLiveMix() {
  if (!liveSession) {
    return;
  }
  clearLiveTimers();
  for (const source of [liveSession.currentSource]) {
    try {
      source?.stop();
    } catch {
      // Source may have already ended.
    }
  }
  liveSession.context.close().catch(() => {});
  liveSession = null;
  els.liveNow.classList.add("hidden");
  els.stopLiveButton.disabled = true;
  els.transitionNowButton.disabled = true;
  if (!els.mixPlayer.src) {
    els.playerPanel.classList.add("hidden");
  }
  setStatus("Live stopped", 0);
  renderQueue();
}

async function analyzeFiles(files) {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file, file.name);
  }
  return fetchJson("/api/tracks/analyze-batch", {
    method: "POST",
    body: formData,
  });
}

async function fetchTrack(trackId) {
  return fetchJson(`/api/tracks/${encodeURIComponent(trackId)}`);
}

async function createPlan(trackIds) {
  const targetMinutes = Number.parseFloat(els.targetMinutes.value);
  const playSeconds = numericValue(els.playSeconds, 75);
  const body = {
    track_ids: trackIds,
    mix_name: `Easy Mix ${new Date().toLocaleString()}`,
    transition_bars: 8,
    target_duration_minutes: Number.isFinite(targetMinutes) ? targetMinutes : null,
    max_play_seconds_per_track: playSeconds,
    auto_order: els.autoOrder.checked,
    mix_direction: els.mixDirection.value.trim() || null,
    use_transition_sfx: els.useSfx.checked,
  };

  return fetchJson("/api/mixes/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function renderMix(mixId) {
  return fetchJson("/api/mixes/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mix_id: mixId, output_format: "wav" }),
  });
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    throw new Error(readError(payload));
  }

  return payload;
}

function readError(payload) {
  if (typeof payload === "string") {
    return payload || "Request failed.";
  }
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  if (Array.isArray(payload.detail)) {
    return payload.detail.map((item) => item.msg || JSON.stringify(item)).join(" ");
  }
  return "Request failed.";
}

function showPlayer(record, autoplayRenderedFile) {
  const src = `/api/mixes/${encodeURIComponent(record.mix_id)}/audio?cache=${Date.now()}`;
  els.mixPlayer.src = src;
  els.downloadLink.href = src;
  els.downloadLink.download = record.output_filename || "ai-dj-mix.wav";
  els.mixName.textContent = record.mix_name;
  els.mixLength.textContent = formatDuration(record.duration_seconds || 0);
  els.mixStatus.textContent = record.status;
  els.playerPanel.classList.remove("hidden");

  if (autoplayRenderedFile) {
    els.mixPlayer.play().catch(() => {
      setStatus("Mix ready. Press play.", 100);
    });
  }
}

function hidePlayer() {
  els.playerPanel.classList.add("hidden");
  els.liveNow.classList.add("hidden");
  els.mixPlayer.removeAttribute("src");
  els.mixPlayer.load();
}

function showErrors(errors) {
  els.errorList.innerHTML = "";
  if (!errors.length) {
    els.errorPanel.classList.add("hidden");
    return;
  }

  for (const error of errors) {
    const item = document.createElement("li");
    item.className = "error-item";
    item.innerHTML = `
      <strong>${escapeHtml(error.file_name || "Error")}</strong>
      <span class="error-meta">${escapeHtml(error.error || "Could not process this item.")}</span>
    `;
    els.errorList.appendChild(item);
  }
  els.errorPanel.classList.remove("hidden");
}

function clearErrors() {
  showErrors([]);
}

function clearAll() {
  selectedFiles.clear();
  selectedLibraryTracks.clear();
  analyzedTracks.clear();
  liveQueue.splice(0, liveQueue.length);
  stopLiveMix();
  renderFiles();
  renderTracks();
  renderQueue();
  renderCatalogResults([]);
  hidePlayer();
  clearErrors();
  setStatus("Ready", 0);
}

function setStatus(text, progress) {
  els.statusText.textContent = text;
  els.progressBar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
}

function toggleBusy(isBusy) {
  for (const button of [
    els.liveMixButton,
    els.downloadMixButton,
    els.clearButton,
    els.chooseFilesButton,
    els.chooseFolderButton,
    els.loadLibraryButton,
    els.catalogSearchButton,
  ]) {
    button.disabled = isBusy;
  }
}

function emptyItem(text) {
  const item = document.createElement("li");
  item.className = "file-item";
  item.innerHTML = `<span class="file-meta">${escapeHtml(text)}</span>`;
  return item;
}

function unique(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

function numericValue(input, fallback) {
  const value = Number.parseFloat(input?.value);
  return Number.isFinite(value) ? value : fallback;
}

function formatBytes(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatBpm(bpm) {
  return bpm ? `${Math.round(bpm)} BPM` : "No BPM";
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  const minutes = Math.floor(total / 60);
  const remaining = String(total % 60).padStart(2, "0");
  return `${minutes}:${remaining}`;
}

function formatEnergy(value) {
  if (!Number.isFinite(value)) {
    return "0.00";
  }
  return value.toFixed(2);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

renderFiles();
renderTracks();
renderQueue();
renderCatalogResults([]);
