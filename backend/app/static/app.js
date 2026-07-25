const selectedFiles = new Map();
const selectedLibraryTracks = new Map();
const analyzedTracks = new Map();
const trackResearch = new Map();
const liveQueue = [];
const referenceMixes = new Map();

let liveSession = null;
let draggedQueueId = null;
let blendSecondsTouched = false;
let appBusy = false;
let mixBusy = false;
let liveLineupUpdatePromise = Promise.resolve(false);

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
  chooseReferenceButton: document.getElementById("chooseReferenceButton"),
  trainStyleButton: document.getElementById("trainStyleButton"),
  referenceInput: document.getElementById("referenceInput"),
  referenceList: document.getElementById("referenceList"),
  styleStatus: document.getElementById("styleStatus"),
  loadLibraryButton: document.getElementById("loadLibraryButton"),
  catalogSearchButton: document.getElementById("catalogSearchButton"),
  catalogSearch: document.getElementById("catalogSearch"),
  catalogResults: document.getElementById("catalogResults"),
  audioUrlInput: document.getElementById("audioUrlInput"),
  importUrlButton: document.getElementById("importUrlButton"),
  researchLibraryButton: document.getElementById("researchLibraryButton"),
  researchPanel: document.getElementById("researchPanel"),
  mixDirection: document.getElementById("mixDirection"),
  autoOrder: document.getElementById("autoOrder"),
  useSfx: document.getElementById("useSfx"),
  useTrainedStyle: document.getElementById("useTrainedStyle"),
  targetMinutes: document.getElementById("targetMinutes"),
  playSeconds: document.getElementById("playSeconds"),
  transitionSeconds: document.getElementById("transitionSeconds"),
  timingAuto: document.getElementById("timingAuto"),
  timingManual: document.getElementById("timingManual"),
  autoTimingNote: document.getElementById("autoTimingNote"),
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
  deckStage: document.querySelector(".deck-stage"),
  deckState: document.getElementById("deckState"),
  nowPlayingTitle: document.getElementById("now-playing-title"),
  nowPlayingMeta: document.getElementById("nowPlayingMeta"),
  upNextTitle: document.getElementById("upNextTitle"),
  upNextMeta: document.getElementById("upNextMeta"),
};

els.chooseFilesButton.addEventListener("click", () => els.fileInput.click());
els.chooseFolderButton.addEventListener("click", () => els.folderInput.click());
els.clearButton.addEventListener("click", clearAll);
els.stopLiveButton.addEventListener("click", stopLiveMix);
els.transitionNowButton.addEventListener("click", () => {
  try {
    transitionToNextTrack(true);
  } catch (error) {
    if (liveSession) {
      liveSession.transitioning = false;
    }
    setStatus("Could not mix next - current song stays live", 48);
    showErrors([{ file_name: "Live deck", error: error.message || "The next transition could not start." }]);
  }
});
els.liveMixButton.addEventListener("click", () => makeMix({ live: true }));
els.downloadMixButton.addEventListener("click", () => makeMix({ live: false }));
els.chooseReferenceButton.addEventListener("click", () => els.referenceInput.click());
els.trainStyleButton.addEventListener("click", trainDJStyle);
els.loadLibraryButton.addEventListener("click", () => searchCatalog(""));
els.catalogSearchButton.addEventListener("click", () => searchCatalog(els.catalogSearch.value));
els.importUrlButton.addEventListener("click", importAudioUrl);
els.researchLibraryButton.addEventListener("click", researchLibrary);
els.catalogSearch.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchCatalog(els.catalogSearch.value);
  }
});
els.audioUrlInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    importAudioUrl();
  }
});
els.timingAuto.addEventListener("change", updateTimingMode);
els.timingManual.addEventListener("change", updateTimingMode);
els.playSeconds.addEventListener("input", updateTimingMode);
els.transitionSeconds.addEventListener("input", () => {
  blendSecondsTouched = true;
});
els.useTrainedStyle.addEventListener("change", () => {
  if (els.useTrainedStyle.checked) {
    blendSecondsTouched = false;
  }
});

els.fileInput.addEventListener("change", async () => {
  await addFiles(Array.from(els.fileInput.files || []));
  els.fileInput.value = "";
});

els.folderInput.addEventListener("change", async () => {
  await addFiles(Array.from(els.folderInput.files || []));
  els.folderInput.value = "";
});

els.referenceInput.addEventListener("change", () => {
  addReferenceMixes(Array.from(els.referenceInput.files || []));
  els.referenceInput.value = "";
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
  await addFiles(files);
});

els.dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    els.fileInput.click();
  }
});

async function addFiles(files) {
  const mp3s = files.filter((file) => file.name.toLowerCase().endsWith(".mp3"));
  if (!mp3s.length) {
    setStatus("No MP3 files found", 0);
    return;
  }

  const newMp3s = [];
  let localDuplicates = 0;
  for (const file of mp3s) {
    const key = fileKey(file);
    if (selectedFiles.has(key)) {
      localDuplicates += 1;
      continue;
    }
    selectedFiles.set(key, file);
    newMp3s.push(file);
  }
  renderFiles();
  clearErrors();

  if (!newMp3s.length) {
    setStatus(`${localDuplicates} duplicate song${localDuplicates === 1 ? "" : "s"} skipped`, 100);
    return;
  }

  try {
    toggleBusy(true);
    setStatus(`Analyzing ${newMp3s.length} song${newMp3s.length === 1 ? "" : "s"}`, 24);
    const batch = await analyzeFiles(newMp3s);
    showErrors(batch.errors || []);
    const trackIds = unique((batch.tracks || []).map((track) => track.track_id).filter(Boolean));
    const tracks = await Promise.all(trackIds.map(fetchTrack));

    for (const track of tracks) {
      selectedLibraryTracks.set(track.track_id, track);
      analyzedTracks.set(track.track_id, track);
      ensureQueueItem({
        id: `track:${track.track_id}`,
        type: "track",
        trackId: track.track_id,
        name: track.title || track.file_name,
        meta: `${formatBpm(track.estimated_bpm)} - ${track.key?.display_name || "Unknown key"}`,
      });
    }

    setStatus("Building DJ cue research", 68);
    const researchRecords = await Promise.all(
      trackIds.map((trackId) => fetchJson(`/api/tracks/${encodeURIComponent(trackId)}/research`)),
    );
    for (const research of researchRecords) {
      trackResearch.set(research.track_id, research);
    }

    renderTracks();
    renderQueue();
    const lineupUpdated = liveSession?.playing
      ? await scheduleLiveLineupUpdate("New songs added")
      : false;
    if (researchRecords.length === 1) {
      renderTrackResearch(researchRecords[0]);
    } else if (researchRecords.length > 1) {
      renderLibraryResearch(researchRecords);
    }
    clearErrors();
    const duplicateCount = localDuplicates + Number(batch.duplicates || 0);
    const duplicateNote = duplicateCount
      ? ` - ${duplicateCount} duplicate${duplicateCount === 1 ? "" : "s"} skipped`
      : "";
    const liveNote = lineupUpdated ? " - live lineup updated" : "";
    setStatus(
      trackIds.length
        ? `${trackIds.length} unique song${trackIds.length === 1 ? "" : "s"} ready${duplicateNote}${liveNote}`
        : duplicateCount
          ? `${duplicateCount} duplicate${duplicateCount === 1 ? "" : "s"} skipped`
          : "No songs added",
      trackIds.length ? 100 : 0,
    );
  } catch (error) {
    showErrors([{ file_name: "Music import", error: error.message || "Could not analyze these MP3 files." }]);
    setStatus("Import stopped", 0);
  } finally {
    toggleBusy(false);
  }
}

function addReferenceMixes(files) {
  const audioFiles = files.filter((file) => {
    const name = file.name.toLowerCase();
    return name.endsWith(".mp3") || name.endsWith(".wav");
  });
  for (const file of audioFiles) {
    referenceMixes.set(fileKey(file), file);
  }
  renderReferenceMixes();
  setStatus(audioFiles.length ? "Reference mixes ready" : "No reference audio found", audioFiles.length ? 18 : 0);
}

function fileKey(file) {
  return `${file.webkitRelativePath || file.name}:${file.size}:${file.lastModified}`;
}

function sanitizeUploadName(name) {
  const baseName = (name || "track").split(/[\\/]/).pop().trim();
  const safeName = baseName.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[._]+|[._]+$/g, "");
  return safeName || "track";
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

async function loadInitialLibrary() {
  try {
    const results = await fetchJson("/api/tracks/search");
    renderCatalogResults(results);
  } catch {
    renderCatalogResults([]);
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

function renderReferenceMixes() {
  const files = Array.from(referenceMixes.values());
  els.referenceList.innerHTML = "";
  els.trainStyleButton.disabled = files.length === 0;

  if (!files.length) {
    const item = document.createElement("li");
    item.className = "catalog-item";
    item.innerHTML = `
      <div>
        <strong>No reference mixes selected</strong>
        <div class="catalog-meta">Reference mixes train style only; they are not added to the live queue.</div>
      </div>
    `;
    els.referenceList.appendChild(item);
    return;
  }

  for (const file of files) {
    const item = document.createElement("li");
    item.className = "catalog-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(file.name)}</strong>
        <div class="catalog-meta">${formatBytes(file.size)} - training reference only</div>
      </div>
    `;
    els.referenceList.appendChild(item);
  }
}

async function trainDJStyle() {
  const files = Array.from(referenceMixes.values());
  if (!files.length) {
    return;
  }

  try {
    toggleBusy(true);
    els.trainStyleButton.disabled = true;
    setStatus("Training DJ style profile", 30);
    const formData = new FormData();
    formData.append("name", "Reference DJ Style");
    for (const file of files) {
      formData.append("files", file, file.name);
    }
    const profile = await fetchJson("/api/style-profiles/train", {
      method: "POST",
      body: formData,
    });
    updateStyleStatus(profile);
    setStatus("DJ style trained", 100);
  } catch (error) {
    showErrors([{ file_name: "Style training", error: error.message || "Could not train from references." }]);
    setStatus("Training failed", 0);
  } finally {
    toggleBusy(false);
    els.trainStyleButton.disabled = referenceMixes.size === 0;
  }
}

async function loadStyleStatus() {
  try {
    const profile = await fetchJson("/api/style-profiles/default");
    updateStyleStatus(profile);
  } catch {
    els.styleStatus.textContent = "No profile";
  }
}

function updateStyleStatus(profile) {
  const intensity = Math.round((profile.effect_intensity || profile.sfx_density || 0) * 100);
  els.styleStatus.textContent = `${profile.reference_count} refs / FX ${intensity}%`;
  if (!blendSecondsTouched) {
    els.transitionSeconds.value = Math.round(profile.transition_duration_seconds);
  }
}

function addLibraryTrack(track, catalogResults) {
  const alreadyQueued = liveQueue.some((queued) => queued.id === `track:${track.track_id}`);
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
  if (alreadyQueued) {
    setStatus("Song already queued - duplicate skipped", 24);
    return;
  }
  if (liveSession?.playing) {
    setStatus("Adding song while Party Mode keeps playing", 48);
    researchTrack(track.track_id, false);
    scheduleLiveLineupUpdate("Song added").catch(() => {});
    return;
  }
  setStatus("Track added to queue", 24);
  researchTrack(track.track_id);
}

async function importAudioUrl() {
  const url = els.audioUrlInput.value.trim();
  if (!url) {
    return;
  }
  if (isYoutubeUrl(url)) {
    showErrors([
      {
        file_name: "Audio link",
        error: "YouTube links cannot be converted to MP3 here. Paste a direct MP3/WAV link you are allowed to use.",
      },
    ]);
    setStatus("Use direct audio link", 0);
    return;
  }

  try {
    toggleBusy(true);
    setStatus("Importing audio link", 22);
    const wasLive = Boolean(liveSession?.playing);
    const track = await fetchJson("/api/tracks/import-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    selectedLibraryTracks.set(track.track_id, track);
    analyzedTracks.set(track.track_id, track);
    ensureQueueItem({
      id: `track:${track.track_id}`,
      type: "track",
      trackId: track.track_id,
      name: track.title || track.file_name,
      meta: `${formatBpm(track.estimated_bpm)} - ${track.key?.display_name || "Unknown key"}`,
    });
    els.audioUrlInput.value = "";
    renderTracks();
    renderQueue();
    const lineupUpdated = wasLive ? await scheduleLiveLineupUpdate("Linked song added") : false;
    const research = await fetchJson(`/api/tracks/${encodeURIComponent(track.track_id)}/research`);
    trackResearch.set(track.track_id, research);
    renderTracks();
    renderTrackResearch(research);
    clearErrors();
    setStatus(lineupUpdated ? "Linked song added - live lineup updated" : "Audio link researched and ready", 100);
  } catch (error) {
    showErrors([{ file_name: "Audio link", error: error.message || "Could not import this link." }]);
    setStatus("Import failed", 0);
  } finally {
    toggleBusy(false);
  }
}

function isYoutubeUrl(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host === "youtu.be" || host === "youtube.com" || host.endsWith(".youtube.com");
  } catch {
    return false;
  }
}

function ensureQueueItem(item) {
  if (!liveQueue.some((queued) => queued.id === item.id)) {
    liveQueue.push(item);
    return true;
  }
  return false;
}

function renderFiles() {
  const files = Array.from(selectedFiles.values());
  els.fileCount.textContent = `${files.length} added`;
  els.fileList.innerHTML = "";

  if (!files.length) {
    els.fileList.appendChild(emptyItem("No recent imports."));
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
    const research = trackResearch.get(track.track_id);
    const playWindow = research?.play_window;
    const item = document.createElement("li");
    item.className = "track-item";
    item.innerHTML = `
      <strong>${escapeHtml(track.title || track.file_name)}</strong>
      <div class="track-meta">
        <span>${formatBpm(track.estimated_bpm)}</span>
        <span>${escapeHtml(track.key?.display_name || "Unknown key")}</span>
        <span>${formatDuration(track.duration_seconds)}</span>
        <span>Energy ${formatEnergy(track.overall_rms_energy)}</span>
        ${
          playWindow
            ? `<span class="track-timing">Auto ${formatDuration(playWindow.play_seconds)} - hype ${formatTime(playWindow.peak_seconds)}</span>`
            : `<span>Researching</span>`
        }
      </div>
      <div class="queue-actions">
        <button type="button" data-action="research">Research</button>
      </div>
    `;
    item.querySelector('[data-action="research"]').addEventListener("click", () => researchTrack(track.track_id));
    els.trackList.appendChild(item);
  }

  els.trackCount.textContent = `${tracks.length} track${tracks.length === 1 ? "" : "s"}`;
  if (!tracks.length) {
    els.trackList.appendChild(emptyItem("No tracks selected yet."));
  }
}

async function researchTrack(trackId, showPanel = true) {
  if (!trackId) {
    return;
  }
  try {
    if (showPanel) {
      setStatus("Researching track", 28);
    }
    const research = await fetchJson(`/api/tracks/${encodeURIComponent(trackId)}/research`);
    trackResearch.set(trackId, research);
    renderTracks();
    if (showPanel) {
      renderTrackResearch(research);
      setStatus("Track research ready", 42);
    }
  } catch (error) {
    showErrors([{ file_name: "DJ Research", error: error.message || "Could not research this track." }]);
  }
}

async function researchLibrary() {
  try {
    setStatus("Researching library", 28);
    const research = await fetchJson("/api/tracks/research");
    for (const record of research) {
      trackResearch.set(record.track_id, record);
    }
    renderTracks();
    renderLibraryResearch(research);
    setStatus(research.length ? "Library research ready" : "No tracks to research", research.length ? 42 : 0);
  } catch (error) {
    showErrors([{ file_name: "DJ Research", error: error.message || "Could not research the library." }]);
  }
}

function renderTrackResearch(research) {
  const transitions = research.recommended_transitions || [];
  const playWindow = research.play_window || null;
  els.researchPanel.innerHTML = `
    <div class="research-card">
      <strong>${escapeHtml(research.title || research.file_name)}</strong>
      <div class="catalog-meta">${formatBpm(research.bpm)} - ${escapeHtml(research.key)} - ${escapeHtml((research.likely_genres || []).join(", "))}</div>
    </div>
    ${
      playWindow
        ? `
          <div class="research-card featured">
            <strong>Auto play ${formatDuration(playWindow.play_seconds)}</strong>
            <div class="catalog-meta">Start ${formatTime(playWindow.start_seconds)} - hype ${formatTime(playWindow.peak_seconds)} - mix out ${formatTime(playWindow.end_seconds)}</div>
            <div class="catalog-meta">${escapeHtml(playWindow.reason)}</div>
          </div>
        `
        : ""
    }
    <div class="research-grid">
      ${renderCueBlock("Mix in", research.mix_in_cues || [])}
      ${renderCueBlock("Mix out", research.mix_out_cues || [])}
    </div>
    <ul class="catalog-results research-results">
      ${
        transitions.length
          ? transitions
              .map(
                (transition) => `
                  <li class="catalog-item">
                    <div>
                      <strong>${escapeHtml(transition.target_title || transition.target_file_name)}</strong>
                      <div class="catalog-meta">${escapeHtml(transition.suggested_style)} - ${Math.round(transition.compatibility_score * 100)}%</div>
                      <div class="catalog-meta">${escapeHtml(transition.expected_sound)}</div>
                      <div class="catalog-meta">Out ${formatTime(transition.source_cue_seconds)} -> In ${formatTime(transition.target_cue_seconds)}</div>
                    </div>
                  </li>
                `,
              )
              .join("")
          : `<li class="catalog-item"><div><strong>No transition matches yet</strong><div class="catalog-meta">Add more analyzed tracks to build pairings.</div></div></li>`
      }
    </ul>
  `;
}

function renderLibraryResearch(records) {
  els.researchPanel.innerHTML = `
    <ul class="catalog-results research-results">
      ${
        records.length
          ? records
              .map(
                (record) => `
                  <li class="catalog-item">
                    <div>
                      <strong>${escapeHtml(record.title || record.file_name)}</strong>
                      <div class="catalog-meta">${(record.mix_out_cues || []).length} exits - ${(record.recommended_transitions || []).length} matches</div>
                    </div>
                    <button type="button" class="small-button" data-track-id="${escapeHtml(record.track_id)}">View</button>
                  </li>
                `,
              )
              .join("")
          : `<li class="catalog-item"><div><strong>No analyzed tracks yet</strong></div></li>`
      }
    </ul>
  `;
  for (const button of els.researchPanel.querySelectorAll("[data-track-id]")) {
    button.addEventListener("click", () => researchTrack(button.dataset.trackId));
  }
}

function renderCueBlock(title, cues) {
  const cueText = cues.length
    ? cues
        .slice(0, 3)
        .map((cue) => `${formatTime(cue.time_seconds)} (${Math.round(cue.confidence * 100)}%)`)
        .join(", ")
    : "No cue found";
  return `
    <div class="research-card">
      <strong>${escapeHtml(title)}</strong>
      <div class="catalog-meta">${escapeHtml(cueText)}</div>
    </div>
  `;
}

function renderQueue() {
  els.queueList.innerHTML = "";
  els.queueCount.textContent = `${liveQueue.length} queued`;
  syncActionAvailability();

  if (!liveQueue.length) {
    els.queueList.appendChild(emptyItem("Drop tracks or add saved songs to build the live queue."));
    updateDeckDisplay();
    return;
  }

  const currentId = liveSession?.currentItemId || null;
  for (const [index, item] of liveQueue.entries()) {
    const row = document.createElement("li");
    row.className = `queue-item${item.id === currentId ? " current" : ""}`;
    row.draggable = true;
    row.dataset.queueId = item.id;
    row.innerHTML = `
      <span class="queue-number">${String(index + 1).padStart(2, "0")}</span>
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
  updateDeckDisplay();
}

function updateDeckDisplay() {
  const currentIndex = liveQueue.findIndex((item) => item.id === liveSession?.currentItemId);
  const isLive = Boolean(liveSession?.playing && currentIndex >= 0);
  const current = isLive ? liveQueue[currentIndex] : null;
  const next = isLive ? liveQueue[currentIndex + 1] : liveQueue[0];

  els.deckStage.classList.toggle("is-live", isLive);
  els.deckState.textContent = isLive ? "Live on air" : liveQueue.length ? "Set ready" : "Deck ready";
  els.nowPlayingTitle.textContent = current?.name || (liveQueue.length ? "Ready when you are" : "Nothing playing yet");
  els.nowPlayingMeta.textContent = current?.meta || (
    liveQueue.length ? `${liveQueue.length} songs lined up` : "Add at least two songs to start a live mix"
  );
  els.upNextTitle.textContent = next?.name || "Waiting for your queue";
  els.upNextMeta.textContent = next?.meta || "AI will line up the set";
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
  if (liveSession?.playing && itemId === liveSession.currentItemId) {
    setStatus("The playing song stays on deck", 48);
    return;
  }
  const index = liveQueue.findIndex((item) => item.id === itemId);
  if (index < 0) {
    return;
  }
  liveQueue.splice(index, 1);
  selectedLibraryTracks.delete(itemId.replace("track:", ""));
  syncLiveDecodedOrder();
  renderTracks();
  renderQueue();
  if (liveSession?.playing) {
    scheduleLiveLineupUpdate("Song removed").catch(() => {});
  }
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

function scheduleLiveLineupUpdate(reason = "Lineup changed") {
  if (!liveSession?.playing) {
    return Promise.resolve(false);
  }
  liveLineupUpdatePromise = liveLineupUpdatePromise
    .catch(() => false)
    .then(() => refreshLiveLineup(reason));
  return liveLineupUpdatePromise;
}

async function refreshLiveLineup(reason) {
  const session = liveSession;
  if (!session?.playing || !session.currentItemId) {
    return false;
  }

  const decodedByQueueId = new Map(session.decodedQueue.map((track) => [track.queueId, track]));
  const initialPlayedIds = new Set(
    session.decodedQueue.slice(0, Math.max(0, session.currentIndex)).map((track) => track.queueId),
  );
  const initialCurrentId = session.currentItemId;
  const pendingItems = uniqueQueueItems(
    liveQueue.filter((item) => !initialPlayedIds.has(item.id) && item.id !== initialCurrentId),
  );

  for (const item of pendingItems) {
    if (decodedByQueueId.has(item.id)) {
      continue;
    }
    const source = sourceFromQueueItem(item);
    if (!source) {
      continue;
    }
    setStatus(`Preparing ${item.name} - music keeps playing`, 54);
    const arrayBuffer = await source.loadArrayBuffer();
    if (liveSession !== session || !session.playing) {
      return false;
    }
    const buffer = await session.context.decodeAudioData(arrayBuffer.slice(0));
    const analysis =
      selectedLibraryTracks.get(item.trackId) ||
      analyzedTracks.get(item.trackId) ||
      (item.trackId ? await fetchTrack(item.trackId) : null);
    if (analysis) {
      selectedLibraryTracks.set(analysis.track_id, analysis);
      analyzedTracks.set(analysis.track_id, analysis);
    }
    decodedByQueueId.set(item.id, {
      queueId: item.id,
      trackId: item.trackId,
      name: item.name,
      bpm: analysis?.estimated_bpm || item.bpm || null,
      keyName: analysis?.key?.display_name || item.keyName || null,
      buffer,
      startOffset: 0,
      plannedWindow: null,
    });
  }

  if (liveSession !== session || !session.playing) {
    return false;
  }

  const pendingTrackIds = unique(pendingItems.map((item) => item.trackId));
  let updatedPlan = null;
  let orderedTrackIds = pendingTrackIds;
  if (pendingTrackIds.length >= 2) {
    setStatus("AI updating what plays next - current song stays live", 62);
    updatedPlan = await createPlan(pendingTrackIds, {
      autoOrder: els.autoOrder.checked,
      mixNamePrefix: "Party Lineup",
    });
    orderedTrackIds = updatedPlan.track_order || pendingTrackIds;
  }

  if (liveSession !== session || !session.playing) {
    return false;
  }

  const latestCurrentId = session.currentItemId;
  const latestCurrent = decodedByQueueId.get(latestCurrentId);
  if (!latestCurrent) {
    return false;
  }
  const latestPlayed = session.decodedQueue
    .slice(0, Math.max(0, session.currentIndex))
    .filter((track) => track.queueId !== latestCurrentId);
  const latestPlayedIds = new Set(latestPlayed.map((track) => track.queueId));
  const latestFutureItems = uniqueQueueItems(
    liveQueue.filter((item) => !latestPlayedIds.has(item.id) && item.id !== latestCurrentId),
  );
  const futureByTrackId = new Map(
    latestFutureItems
      .filter((item) => item.trackId)
      .map((item) => [item.trackId, item]),
  );
  const plannedFuture = orderedTrackIds.map((trackId) => futureByTrackId.get(trackId)).filter(Boolean);
  const remainingFuture = latestFutureItems.filter(
    (item) => !plannedFuture.some((planned) => planned.id === item.id),
  );
  const orderedFutureItems = [...plannedFuture, ...remainingFuture];
  const decodedFuture = orderedFutureItems.map((item) => decodedByQueueId.get(item.id)).filter(Boolean);

  if (updatedPlan) {
    for (const track of decodedFuture) {
      const placement = plannedPlacementForTrack(updatedPlan, track.trackId);
      track.startOffset = placement?.source_start_time || 0;
      track.plannedWindow =
        placement && placement.source_end_time > placement.source_start_time
          ? placement.source_end_time - placement.source_start_time
          : null;
    }
    session.plan = updatedPlan;
    applyPlanToLiveControls(updatedPlan);
  }

  const queueById = new Map(liveQueue.map((item) => [item.id, item]));
  const displayedPlayed = latestPlayed.map((track) => queueById.get(track.queueId)).filter(Boolean);
  const displayedCurrent = queueById.get(latestCurrentId);
  const displayedFuture = orderedFutureItems.filter((item) => queueById.has(item.id));
  liveQueue.splice(
    0,
    liveQueue.length,
    ...displayedPlayed,
    ...(displayedCurrent ? [displayedCurrent] : []),
    ...displayedFuture,
  );
  session.decodedQueue = [...latestPlayed, latestCurrent, ...decodedFuture];
  session.currentIndex = latestPlayed.length;
  renderTracks();
  renderQueue();
  setStatus(`${reason} - music kept playing`, 68);
  return true;
}

function uniqueQueueItems(items) {
  const seenTrackIds = new Set();
  const seenQueueIds = new Set();
  return items.filter((item) => {
    if (seenQueueIds.has(item.id) || (item.trackId && seenTrackIds.has(item.trackId))) {
      return false;
    }
    seenQueueIds.add(item.id);
    if (item.trackId) {
      seenTrackIds.add(item.trackId);
    }
    return true;
  });
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

  setMixBusy(true);
  clearErrors();
  stopLiveMix();
  if (!live) hidePlayer();

  try {
    analyzedTracks.clear();
    const fileItems = liveQueue.filter((item) => item.type === "file");
    const fileTrackIdsByQueueId = new Map();

    if (fileItems.length) {
      setStatus(live ? "AI analyzing tracks" : "Uploading and analyzing", 32);
      const files = fileItems.map((item) => selectedFiles.get(item.key)).filter(Boolean);
      const fileItemsBySafeName = new Map();
      for (const item of fileItems) {
        const file = selectedFiles.get(item.key);
        const safeName = sanitizeUploadName(file?.name || item.name);
        if (!fileItemsBySafeName.has(safeName)) {
          fileItemsBySafeName.set(safeName, []);
        }
        fileItemsBySafeName.get(safeName).push(item);
      }
      const batch = await analyzeFiles(files);
      showErrors(batch.errors || []);
      const batchTracks = batch.tracks || [];
      const unmatchedResults = [];
      for (const result of batchTracks) {
        const queueMatches = fileItemsBySafeName.get(result.file_name) || [];
        const queueItem = queueMatches.shift();
        if (queueItem?.id && result.track_id) {
          fileTrackIdsByQueueId.set(queueItem.id, result.track_id);
        } else {
          unmatchedResults.push(result);
        }
      }
      const unmappedItems = fileItems.filter((item) => !fileTrackIdsByQueueId.has(item.id));
      for (let index = 0; index < unmatchedResults.length && index < unmappedItems.length; index += 1) {
        if (unmatchedResults[index]?.track_id) {
          fileTrackIdsByQueueId.set(unmappedItems[index].id, unmatchedResults[index].track_id);
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

    setStatus(live ? "AI reading BPM, key, and energy" : "Loading track details", 52);
    const tracks = await Promise.all(trackIds.map(fetchTrack));
    for (const track of tracks) {
      analyzedTracks.set(track.track_id, track);
    }
    renderTracks();

    setStatus(live ? "AI lining up the live mix" : "Planning transitions", 68);
    const plan = await createPlan(trackIds);

    if (live) {
      const plannedQueue = queueOrderedByPlan(plan, fileTrackIdsByQueueId, tracks);
      applyPlanToLiveControls(plan);
      renderQueue();
      setStatus("Starting AI-lined live deck", 76);
      await startBrowserLiveMix(plannedQueue, plan);
    }

    setStatus(live ? "Live playing, rendering download" : "Rendering audio", 84);
    const record = await renderMix(plan.mix_id);

    setStatus(live ? "Live mix playing. Download ready." : "Mix ready", 100);
    showPlayer(record, !live);
  } catch (error) {
    setStatus(live && liveSession?.playing ? "Live playing, render stopped" : "Stopped", live ? 34 : 0);
    showErrors([{ file_name: "Mix", error: error.message || "Something went wrong." }]);
  } finally {
    setMixBusy(false);
  }
}

function queueOrderedByPlan(plan, fileTrackIdsByQueueId, tracks) {
  const trackById = new Map(tracks.map((track) => [track.track_id, track]));
  const queueByTrackId = new Map();

  for (const item of liveQueue) {
    const trackId = item.type === "track" ? item.trackId : fileTrackIdsByQueueId.get(item.id);
    if (!trackId || queueByTrackId.has(trackId)) {
      continue;
    }
    const track = trackById.get(trackId);
    queueByTrackId.set(trackId, {
      ...item,
      trackId,
      bpm: track?.estimated_bpm || item.bpm || null,
      keyName: track?.key?.display_name || item.keyName || null,
      meta: track ? `${formatBpm(track.estimated_bpm)} - ${track.key?.display_name || "Unknown key"}` : item.meta,
    });
  }

  const ordered = plan.track_order.map((trackId) => queueByTrackId.get(trackId)).filter(Boolean);
  const missing = liveQueue
    .map((item) => {
      const trackId = item.type === "track" ? item.trackId : fileTrackIdsByQueueId.get(item.id);
      return trackId ? queueByTrackId.get(trackId) : item;
    })
    .filter((item) => item && !ordered.some((queued) => queued.id === item.id));

  liveQueue.splice(0, liveQueue.length, ...ordered, ...missing);
  return liveQueue.slice();
}

function applyPlanToLiveControls(plan) {
  if (plan.max_play_seconds_per_track) {
    els.playSeconds.value = Math.round(plan.max_play_seconds_per_track);
    els.autoTimingNote.textContent = `${Math.round(plan.max_play_seconds_per_track)} sec manual`;
  } else if (plan.placements?.length) {
    const windows = plan.placements.map(
      (placement) => placement.source_end_time - placement.source_start_time,
    );
    const shortest = Math.round(Math.min(...windows));
    const longest = Math.round(Math.max(...windows));
    els.autoTimingNote.textContent = shortest === longest ? `${shortest} sec AI pick` : `${shortest}-${longest} sec AI picks`;
  }
  if (plan.transitions?.length) {
    const averageTransition =
      plan.transitions.reduce((sum, transition) => sum + transition.duration_seconds, 0) / plan.transitions.length;
    els.transitionSeconds.value = Math.round(averageTransition);
  }
}

async function startBrowserLiveMix(queueItems, plan = null) {
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
    currentChannel: null,
    timers: [],
    activeSources: new Set(),
    playing: false,
    transitioning: false,
    plan,
    segmentSeconds: numericValue(els.playSeconds, 90),
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
    const placement = plannedPlacementForTrack(plan, sources[index].trackId);
    liveSession.decodedQueue.push({
      queueId: sources[index].queueId,
      trackId: sources[index].trackId,
      name: sources[index].name,
      bpm: sources[index].bpm,
      keyName: sources[index].keyName,
      buffer,
      startOffset: placement?.source_start_time || 0,
      plannedWindow:
        placement && placement.source_end_time > placement.source_start_time
          ? placement.source_end_time - placement.source_start_time
          : null,
    });
  }

  playLiveTrackAtIndex(0, 0.8);
  updateBusyControls();
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
      trackId: item.trackId,
      name: item.name,
      bpm: item.bpm,
      keyName: item.keyName,
      loadArrayBuffer: () => file.arrayBuffer(),
    };
  }

  if (item.type === "track") {
    return {
      queueId: item.id,
      trackId: item.trackId,
      name: item.name,
      bpm: item.bpm,
      keyName: item.keyName,
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
  const nextTrack = decodedQueue[index + 1] || null;
  const transitionSeconds = nextTrack ? transitionSecondsBetween(track, nextTrack) : liveSession.transitionSeconds;
  const duration = livePreTransitionWindow(track, transitionSeconds);
  const offset = liveTrackStartOffset(track);
  const playbackDuration = livePlaybackDuration(track, duration, transitionSeconds, 1);
  const source = context.createBufferSource();
  const channel = createLiveChannel(context, now);

  source.buffer = track.buffer;
  source.connect(channel.eq);
  channel.gain.gain.setValueAtTime(0.0001, now);
  scheduleEqualPowerFade(channel.gain.gain, now, Math.min(fadeInSeconds, 2.0), true);
  source.start(now, offset, playbackDuration);
  liveSession.activeSources.add(source);

  liveSession.currentIndex = index;
  liveSession.currentItemId = track.queueId;
  liveSession.currentSource = source;
  liveSession.currentGain = channel.gain;
  liveSession.currentChannel = channel;
  liveSession.playing = true;
  liveSession.transitioning = false;

  source.addEventListener("ended", () => {
    liveSession?.activeSources?.delete(source);
    if (liveSession?.currentSource === source && !liveSession.transitioning) {
      transitionToNextTrack(false);
    }
  });

  const autoMs = Math.max(1000, duration * 1000);
  liveSession.timers.push(window.setTimeout(() => transitionToNextTrack(false), autoMs));
  renderQueue();
}

function liveTrackStartOffset(track) {
  const requested = Number.isFinite(track.startOffset) ? track.startOffset : 0;
  const latest = Math.max(0, track.buffer.duration - 1);
  return Math.max(0, Math.min(requested, latest));
}

function livePreTransitionWindow(track, transitionSeconds) {
  const available = Math.max(1, track.buffer.duration - liveTrackStartOffset(track));
  const controlSeconds = Math.max(30, numericValue(els.playSeconds, liveSession?.segmentSeconds || 90));
  const plannedSeconds =
    els.timingAuto.checked && Number.isFinite(track.plannedWindow)
      ? Math.max(4, track.plannedWindow - transitionSeconds)
      : null;
  const preferred = plannedSeconds || controlSeconds;
  return Math.max(4, Math.min(preferred, Math.max(4, available - Math.min(transitionSeconds, available * 0.5))));
}

function livePlaybackDuration(track, preTransitionSeconds, transitionSeconds, playbackRate) {
  const available = Math.max(0, track.buffer.duration - liveTrackStartOffset(track));
  const requested = Math.max(1, preTransitionSeconds + transitionSeconds + 0.2) * Math.max(0.1, playbackRate);
  return Math.min(available, requested);
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
  const nextTrack = liveSession.decodedQueue[nextIndex];
  const currentTrack = liveSession.decodedQueue[liveSession.currentIndex];
  const transition = transitionSecondsBetween(currentTrack, nextTrack);
  const transitionEffects = liveTransitionEffects(currentTrack, nextTrack);
  const playbackRate = aiPlaybackRateForNext(nextTrack);
  const nextOffset = liveTrackStartOffset(nextTrack);
  const nextWindow = livePreTransitionWindow(
    nextTrack,
    liveSession.decodedQueue[nextIndex + 1] ? transitionSecondsBetween(nextTrack, liveSession.decodedQueue[nextIndex + 1]) : transition,
  );
  const nextSource = context.createBufferSource();
  const nextChannel = createLiveChannel(context, now, -10);

  nextSource.buffer = nextTrack.buffer;
  nextSource.playbackRate.setValueAtTime(playbackRate, now);
  nextSource.connect(nextChannel.eq);
  nextChannel.gain.gain.setValueAtTime(0.0001, now);
  scheduleEqualPowerFade(nextChannel.gain.gain, now, transition, true);
  nextChannel.eq.gain.linearRampToValueAtTime(0, now + transition * 0.7);
  nextSource.start(now, nextOffset, livePlaybackDuration(nextTrack, nextWindow, transition, playbackRate));
  liveSession.activeSources.add(nextSource);

  if (liveSession.currentGain) {
    liveSession.currentGain.gain.cancelScheduledValues(now);
    scheduleEqualPowerFade(liveSession.currentGain.gain, now, transition, false);
  }
  if (liveSession.currentChannel) {
    liveSession.currentChannel.eq.gain.cancelScheduledValues(now);
    liveSession.currentChannel.eq.gain.setValueAtTime(0, now);
    liveSession.currentChannel.eq.gain.linearRampToValueAtTime(-14, now + transition * 0.55);
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
        liveSession?.activeSources?.delete(oldSource);
      }, transition * 1000 + 80),
    );
  }

  nextSource.addEventListener("ended", () => {
    liveSession?.activeSources?.delete(nextSource);
    if (liveSession?.currentSource === nextSource && !liveSession.transitioning) {
      transitionToNextTrack(false);
    }
  });

  if (liveSession.withSfx) {
    try {
      scheduleBrowserChannelEffects(liveSession.currentChannel, now, transition, transitionEffects);
      scheduleBrowserSfx(context, now, transition, transitionEffects);
    } catch (error) {
      console.warn("A live DJ effect was skipped so the transition could continue.", error);
    }
  }

  liveSession.currentIndex = nextIndex;
  liveSession.currentItemId = nextTrack.queueId;
  liveSession.currentSource = nextSource;
  liveSession.currentGain = nextChannel.gain;
  liveSession.currentChannel = nextChannel;
  liveSession.timers.push(
    window.setTimeout(() => {
      if (liveSession?.currentSource === nextSource) {
        liveSession.transitioning = false;
      }
    }, transition * 1000 + 120),
  );
  liveSession.timers.push(window.setTimeout(() => transitionToNextTrack(false), Math.max(1000, nextWindow * 1000)));
  setStatus(manual ? "Manual transition" : "AI transition", 52);
  renderQueue();
}

function plannedPlacementForTrack(plan, trackId) {
  if (!plan || !trackId) {
    return null;
  }
  return plan.placements?.find((placement) => placement.track_id === trackId) || null;
}

function plannedTransitionBetween(sourceTrack, targetTrack) {
  if (!liveSession?.plan || !sourceTrack?.trackId || !targetTrack?.trackId) {
    return null;
  }
  return (
    liveSession.plan.transitions?.find(
      (transition) =>
        transition.source_track_id === sourceTrack.trackId && transition.target_track_id === targetTrack.trackId,
    ) || null
  );
}

function transitionSecondsBetween(sourceTrack, targetTrack) {
  if (!blendSecondsTouched) {
    const planned = plannedTransitionBetween(sourceTrack, targetTrack);
    if (planned?.duration_seconds) {
      return Math.max(2, Math.min(45, planned.duration_seconds));
    }
  }
  return Math.max(2, numericValue(els.transitionSeconds, liveSession.transitionSeconds));
}

function aiPlaybackRateForNext(nextTrack) {
  const current = liveSession?.decodedQueue?.[liveSession.currentIndex];
  if (!current?.bpm || !nextTrack?.bpm) {
    return 1;
  }
  const ratio = current.bpm / nextTrack.bpm;
  return ratio >= 0.94 && ratio <= 1.06 ? ratio : 1;
}

function createLiveChannel(context, now, initialBassDb = 0) {
  const eq = context.createBiquadFilter();
  const gain = context.createGain();
  const delay = context.createDelay(1.2);
  const feedback = context.createGain();
  const delayWet = context.createGain();
  eq.type = "lowshelf";
  eq.frequency.setValueAtTime(180, now);
  eq.gain.setValueAtTime(initialBassDb, now);
  delay.delayTime.setValueAtTime(0.18, now);
  feedback.gain.setValueAtTime(0.0001, now);
  delayWet.gain.setValueAtTime(0.0001, now);
  eq.connect(gain);
  gain.connect(context.destination);
  gain.connect(delay);
  delay.connect(feedback);
  feedback.connect(delay);
  delay.connect(delayWet).connect(context.destination);
  return { eq, gain, delay, feedback, delayWet };
}

function scheduleEqualPowerFade(gainParam, startTime, duration, fadeIn) {
  const steps = 14;
  gainParam.cancelScheduledValues(startTime);
  gainParam.setValueAtTime(fadeIn ? 0.0001 : 1.0, startTime);
  for (let step = 1; step <= steps; step += 1) {
    const progress = step / steps;
    const curve = fadeIn ? Math.sin(progress * Math.PI * 0.5) : Math.cos(progress * Math.PI * 0.5);
    gainParam.linearRampToValueAtTime(Math.max(0.0001, curve), startTime + duration * progress);
  }
}

function liveTransitionEffects(sourceTrack, targetTrack) {
  const planned = plannedTransitionBetween(sourceTrack, targetTrack);
  return planned?.sfx?.length ? planned.sfx : ["filter_sweep", "echo_tail", "reverse_swell", "impact"];
}

function scheduleBrowserChannelEffects(channel, transitionStart, transitionSeconds, effects) {
  if (!channel || (!effects.includes("echo_tail") && !effects.includes("echo_freeze"))) {
    return;
  }
  const freeze = effects.includes("echo_freeze");
  const echoTime = freeze ? Math.max(0.1, Math.min(0.22, transitionSeconds / 12)) : Math.max(0.12, Math.min(0.38, transitionSeconds / 8));
  channel.delay.delayTime.cancelScheduledValues(transitionStart);
  channel.feedback.gain.cancelScheduledValues(transitionStart);
  channel.delayWet.gain.cancelScheduledValues(transitionStart);
  channel.delay.delayTime.setValueAtTime(echoTime, transitionStart);
  channel.feedback.gain.setValueAtTime(0.0001, transitionStart);
  channel.feedback.gain.linearRampToValueAtTime(freeze ? 0.48 : 0.32, transitionStart + transitionSeconds * 0.35);
  channel.feedback.gain.exponentialRampToValueAtTime(0.0001, transitionStart + transitionSeconds + 1.2);
  channel.delayWet.gain.setValueAtTime(0.0001, transitionStart);
  channel.delayWet.gain.linearRampToValueAtTime(freeze ? 0.24 : 0.18, transitionStart + transitionSeconds * 0.45);
  channel.delayWet.gain.exponentialRampToValueAtTime(0.0001, transitionStart + transitionSeconds + 1.4);
}

function scheduleBrowserSfx(context, transitionStart, transitionSeconds, effects = []) {
  const hasSweep = effects.some((effect) => ["filter_sweep", "noise_sweep", "soft_sweep"].includes(effect));
  if (hasSweep) {
    scheduleBrowserSweep(context, transitionStart, transitionSeconds, effects.includes("soft_sweep") ? 0.018 : 0.034);
  }
  if (effects.includes("reverb_riser")) {
    scheduleBrowserRiser(context, transitionStart, transitionSeconds);
  }
  if (effects.includes("reverse_swell")) {
    scheduleBrowserReverseSwell(context, transitionStart, transitionSeconds);
  }
  if (effects.includes("loop_roll")) {
    scheduleBrowserRollTicks(context, transitionStart, transitionSeconds);
  }
  if (effects.includes("brake_cut")) {
    scheduleBrowserBrakeCut(context, transitionStart, transitionSeconds);
  }
  if (effects.includes("impact")) {
    scheduleBrowserImpact(context, transitionStart + transitionSeconds - 0.04);
  }
}

function scheduleBrowserSweep(context, transitionStart, transitionSeconds, amplitude) {
  const sweepDuration = Math.max(0.8, Math.min(transitionSeconds, 7.5));
  const sweep = context.createOscillator();
  const sweepGain = context.createGain();
  sweep.type = "sawtooth";
  sweep.frequency.setValueAtTime(420, transitionStart);
  sweep.frequency.exponentialRampToValueAtTime(4200, transitionStart + sweepDuration);
  sweepGain.gain.setValueAtTime(0.0001, transitionStart);
  sweepGain.gain.linearRampToValueAtTime(amplitude, transitionStart + sweepDuration * 0.65);
  sweepGain.gain.exponentialRampToValueAtTime(0.0001, transitionStart + sweepDuration);
  sweep.connect(sweepGain).connect(context.destination);
  sweep.start(transitionStart);
  sweep.stop(transitionStart + sweepDuration + 0.05);
  liveSession?.timers.push(window.setTimeout(() => sweep.disconnect(), (sweepDuration + 0.2) * 1000));
}

function scheduleBrowserRiser(context, transitionStart, transitionSeconds) {
  const duration = Math.max(0.6, Math.min(transitionSeconds, 5));
  const buffer = context.createBuffer(1, Math.max(1, Math.floor(context.sampleRate * duration)), context.sampleRate);
  const data = buffer.getChannelData(0);
  for (let index = 0; index < data.length; index += 1) {
    data[index] = (Math.random() * 2 - 1) * (index / data.length);
  }
  const noise = context.createBufferSource();
  const filter = context.createBiquadFilter();
  const gain = context.createGain();
  noise.buffer = buffer;
  filter.type = "highpass";
  filter.frequency.setValueAtTime(460, transitionStart);
  filter.frequency.exponentialRampToValueAtTime(5200, transitionStart + duration);
  gain.gain.setValueAtTime(0.0001, transitionStart);
  gain.gain.linearRampToValueAtTime(0.035, transitionStart + duration * 0.76);
  gain.gain.exponentialRampToValueAtTime(0.0001, transitionStart + duration);
  noise.connect(filter).connect(gain).connect(context.destination);
  noise.start(transitionStart);
  noise.stop(transitionStart + duration + 0.05);
}

function scheduleBrowserReverseSwell(context, transitionStart, transitionSeconds) {
  const duration = Math.max(0.5, Math.min(transitionSeconds * 0.75, 4.5));
  const buffer = context.createBuffer(1, Math.max(1, Math.floor(context.sampleRate * duration)), context.sampleRate);
  const data = buffer.getChannelData(0);
  for (let index = 0; index < data.length; index += 1) {
    const progress = index / Math.max(data.length - 1, 1);
    data[index] = (Math.random() * 2 - 1) * progress * progress;
  }
  const source = context.createBufferSource();
  const filter = context.createBiquadFilter();
  const gain = context.createGain();
  source.buffer = buffer;
  filter.type = "bandpass";
  filter.frequency.setValueAtTime(720, transitionStart);
  filter.frequency.exponentialRampToValueAtTime(3600, transitionStart + duration);
  gain.gain.setValueAtTime(0.0001, transitionStart);
  gain.gain.linearRampToValueAtTime(0.03, transitionStart + duration * 0.82);
  gain.gain.exponentialRampToValueAtTime(0.0001, transitionStart + duration);
  source.connect(filter).connect(gain).connect(context.destination);
  source.start(transitionStart);
  source.stop(transitionStart + duration + 0.05);
}

function scheduleBrowserRollTicks(context, transitionStart, transitionSeconds) {
  const start = transitionStart + transitionSeconds * 0.58;
  const step = Math.max(0.09, Math.min(0.18, transitionSeconds / 32));
  for (let time = start; time < transitionStart + transitionSeconds - 0.08; time += step) {
    const tick = context.createOscillator();
    const gain = context.createGain();
    tick.type = "triangle";
    tick.frequency.setValueAtTime(190 + (time - start) * 260, time);
    gain.gain.setValueAtTime(0.0001, time);
    gain.gain.linearRampToValueAtTime(0.026, time + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, time + 0.075);
    tick.connect(gain).connect(context.destination);
    tick.start(time);
    tick.stop(time + 0.08);
  }
}

function scheduleBrowserBrakeCut(context, transitionStart, transitionSeconds) {
  const start = transitionStart + transitionSeconds * 0.84;
  const brake = context.createOscillator();
  const gain = context.createGain();
  brake.type = "sawtooth";
  brake.frequency.setValueAtTime(220, start);
  brake.frequency.exponentialRampToValueAtTime(42, start + 0.38);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.linearRampToValueAtTime(0.018, start + 0.04);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.42);
  brake.connect(gain).connect(context.destination);
  brake.start(start);
  brake.stop(start + 0.46);
}

function scheduleBrowserImpact(context, impactTime) {
  if (!context || !Number.isFinite(impactTime)) {
    return;
  }
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
  const sources = liveSession.activeSources?.size ? Array.from(liveSession.activeSources) : [liveSession.currentSource];
  for (const source of sources) {
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

async function createPlan(trackIds, options = {}) {
  const targetMinutes = Number.parseFloat(els.targetMinutes.value);
  const playSeconds = numericValue(els.playSeconds, 90);
  const useAiTiming = els.timingAuto.checked;
  const autoOrder = options.autoOrder ?? els.autoOrder.checked;
  const mixNamePrefix = options.mixNamePrefix || "Party Mix";
  const body = {
    track_ids: trackIds,
    mix_name: `${mixNamePrefix} ${new Date().toLocaleString()}`,
    transition_bars: 8,
    target_duration_minutes: Number.isFinite(targetMinutes) ? targetMinutes : null,
    max_play_seconds_per_track: useAiTiming ? null : playSeconds,
    auto_order: autoOrder,
    mix_direction: els.mixDirection.value.trim() || null,
    use_transition_sfx: els.useSfx.checked,
    use_trained_style: els.useTrainedStyle.checked,
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
  trackResearch.clear();
  referenceMixes.clear();
  blendSecondsTouched = false;
  els.audioUrlInput.value = "";
  els.timingAuto.checked = true;
  els.timingManual.checked = false;
  els.playSeconds.value = "";
  liveQueue.splice(0, liveQueue.length);
  stopLiveMix();
  renderFiles();
  renderTracks();
  renderQueue();
  renderCatalogResults([]);
  renderReferenceMixes();
  hidePlayer();
  clearErrors();
  setStatus("Ready", 0);
  updateTimingMode();
}

function updateTimingMode() {
  const isManual = els.timingManual.checked;
  els.playSeconds.disabled = !isManual;
  els.autoTimingNote.textContent = isManual ? "Your timing" : "Research controlled";
}

function setStatus(text, progress) {
  els.statusText.textContent = text;
  els.progressBar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
}

function toggleBusy(isBusy) {
  appBusy = isBusy;
  updateBusyControls();
}

function setMixBusy(isBusy) {
  mixBusy = isBusy;
  updateBusyControls();
}

function updateBusyControls() {
  const setupBusy = appBusy || (mixBusy && !liveSession?.playing);
  for (const button of [
    els.chooseFilesButton,
    els.chooseFolderButton,
    els.loadLibraryButton,
    els.catalogSearchButton,
    els.importUrlButton,
    els.chooseReferenceButton,
  ]) {
    button.disabled = setupBusy;
  }
  els.clearButton.disabled = appBusy || mixBusy;
  syncActionAvailability();
}

function syncActionAvailability() {
  const needsMoreSongs = liveQueue.length < 2;
  els.liveMixButton.disabled = appBusy || mixBusy || needsMoreSongs;
  els.downloadMixButton.disabled = appBusy || mixBusy || needsMoreSongs;
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

function formatTime(seconds) {
  return formatDuration(seconds);
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
loadInitialLibrary();
renderReferenceMixes();
updateTimingMode();
loadStyleStatus();
