const selectedFiles = new Map();
const selectedLibraryTracks = new Map();
const analyzedTracks = new Map();
const trackResearch = new Map();
const liveQueue = [];
const referenceMixes = new Map();
const catalogGenres = new Set();
const commonGenres = [
  "Open Format",
  "Pop",
  "Electronic / Dance",
  "House",
  "Techno",
  "Trance",
  "Drum & Bass",
  "Dubstep",
  "Hip-Hop / Rap",
  "R&B / Soul",
  "Afrobeats / Amapiano",
  "Latin",
  "Reggae / Dancehall",
  "Rock",
  "Jazz",
  "Country",
];

let liveSession = null;
let draggedQueueId = null;
let blendSecondsTouched = false;
let appBusy = false;
let mixBusy = false;
let liveLineupUpdatePromise = Promise.resolve(false);
let lastCatalogResults = [];
let recommendTimer = null;
let recommendRequestId = 0;
let autoPickPending = false;

// Blend timing limits (seconds). Planned blends for locked tempo+key pairs can ride
// up to 16 s; manual blend input is capped the same way.
const MAX_BLEND_SECONDS = 16;
const SAFE_TEMPO_RATIO = [0.94, 1.06];
// Moves where the outgoing song does its own exit and the next song lands on the "1".
const SLAM_MOVES = new Set(["kill_cut", "spinback", "power_down", "roll_build", "reverb_wash"]);
// Moves whose length is fixed in bars by the planner (never stretched by the blend-seconds box).
const BAR_LOCKED_MOVES = new Set([
  ...SLAM_MOVES,
  "quick_cut",
  "double_play",
  "vocal_over",
  "filter_swap",
  "loop_riser",
  "key_lift",
  "beat_juggle",
]);

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
  genreFilter: document.getElementById("genreFilter"),
  catalogResults: document.getElementById("catalogResults"),
  audioUrlInput: document.getElementById("audioUrlInput"),
  importUrlButton: document.getElementById("importUrlButton"),
  researchLibraryButton: document.getElementById("researchLibraryButton"),
  researchPanel: document.getElementById("researchPanel"),
  mixDirection: document.getElementById("mixDirection"),
  autoOrder: document.getElementById("autoOrder"),
  useSfx: document.getElementById("useSfx"),
  useTrainedStyle: document.getElementById("useTrainedStyle"),
  autoDj: document.getElementById("autoDj"),
  recommendList: document.getElementById("recommendList"),
  recommendAnchor: document.getElementById("recommendAnchor"),
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
els.loadLibraryButton.addEventListener("click", () => {
  els.catalogSearch.value = "";
  els.genreFilter.value = "";
  searchCatalog("");
});
els.catalogSearchButton.addEventListener("click", () => searchCatalog(els.catalogSearch.value));
els.genreFilter.addEventListener("change", () => searchCatalog(els.catalogSearch.value));
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
els.mixDirection.addEventListener("input", scheduleRecommendations);
els.autoDj.addEventListener("change", () => {
  updateDeckDisplay();
  if (els.autoDj.checked) {
    maybeAutoPick();
  }
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
        meta: formatTrackMeta(track),
      });
    }
    updateGenreOptions(tracks);

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
    const params = new URLSearchParams();
    if (query.trim()) {
      params.set("query", query.trim());
    }
    if (els.genreFilter.value) {
      params.set("genre", els.genreFilter.value);
    }
    const queryString = params.toString();
    const results = await fetchJson(`/api/tracks/search${queryString ? `?${queryString}` : ""}`);
    renderCatalogResults(results);
    setStatus(results.length ? "Library results ready" : "No saved matches", results.length ? 20 : 0);
  } catch (error) {
    showErrors([{ file_name: "Search", error: error.message || "Library search failed." }]);
  }
}

async function loadInitialLibrary() {
  try {
    const results = await fetchJson("/api/tracks/search");
    updateGenreOptions(results);
    renderCatalogResults(results);
  } catch {
    renderCatalogResults([]);
  }
}

function renderCatalogResults(results) {
  lastCatalogResults = results;
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
        <div class="catalog-meta">${escapeHtml(formatTrackMeta(track))} - ${formatDuration(track.duration_seconds)}</div>
      </div>
      <div class="catalog-actions">
        <label class="genre-editor-label">
          <span>Genre</span>
          <select class="genre-editor" aria-label="Genre for ${escapeHtml(track.title || track.file_name)}">
            ${genreOptionsHtml(track.genre)}
          </select>
        </label>
        <button type="button" class="small-button">${isSelected ? "Added" : "Add"}</button>
      </div>
    `;
    const button = item.querySelector("button");
    const genreEditor = item.querySelector(".genre-editor");
    button.disabled = isSelected;
    button.addEventListener("click", () => addLibraryTrack(track, results));
    genreEditor.addEventListener("change", () => updateTrackGenre(track, genreEditor.value));
    els.catalogResults.appendChild(item);
  }
}

function genreOptionsHtml(currentGenre) {
  const genres = new Set(commonGenres);
  if (currentGenre) {
    genres.add(currentGenre);
  }
  return Array.from(genres)
    .sort((left, right) => left.localeCompare(right))
    .map((genre) => `<option value="${escapeHtml(genre)}"${genre === currentGenre ? " selected" : ""}>${escapeHtml(genre)}</option>`)
    .join("");
}

async function updateTrackGenre(track, genre) {
  try {
    setStatus("Saving genre", 16);
    const updated = await fetchJson(`/api/tracks/${encodeURIComponent(track.track_id)}/genre`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ genre }),
    });
    catalogGenres.add(updated.genre);
    if (selectedLibraryTracks.has(updated.track_id)) {
      selectedLibraryTracks.set(updated.track_id, updated);
      renderTrackList();
    }
    const queueEntry = trackQueue.find((entry) => entry.trackId === updated.track_id);
    if (queueEntry) {
      queueEntry.track = updated;
      renderQueue();
    }
    updateGenreOptions([updated]);
    await searchCatalog(els.catalogSearch.value);
    setStatus("Genre saved", 20);
  } catch (error) {
    showErrors([{ file_name: track.file_name, error: error.message || "Could not save the genre." }]);
  }
}

function updateGenreOptions(tracks) {
  const selected = els.genreFilter.value;
  for (const track of tracks) {
    if (track.genre) {
      catalogGenres.add(track.genre);
    }
  }
  els.genreFilter.innerHTML = '<option value="">All genres</option>';
  for (const genre of Array.from(catalogGenres).sort((left, right) => left.localeCompare(right))) {
    const option = document.createElement("option");
    option.value = genre;
    option.textContent = genre;
    els.genreFilter.appendChild(option);
  }
  els.genreFilter.value = catalogGenres.has(selected) ? selected : "";
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
    els.transitionSeconds.value = Math.round(Math.min(8, profile.transition_duration_seconds));
  }
}

function addLibraryTrack(track, catalogResults) {
  const alreadyQueued = liveQueue.some((queued) => queued.id === `track:${track.track_id}`);
  selectedLibraryTracks.set(track.track_id, track);
  ensureQueueItem(queueItemForTrack(track));
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
    updateGenreOptions([track]);
    ensureQueueItem(queueItemForTrack(track));
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
        <span class="genre-badge">${escapeHtml(track.genre || "Open Format")}</span>
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
    scheduleRecommendations();
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
  scheduleRecommendations();
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
  els.upNextMeta.textContent = next?.meta || (els.autoDj.checked ? "Auto DJ will pick from your library" : "AI will line up the set");
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
  if (liveSession?.playing) {
    scheduleLiveLineupUpdate("Queue reordered", { keepOrder: true }).catch(() => {});
  }
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
  if (liveSession?.playing) {
    scheduleLiveLineupUpdate("Next song cued", { pinnedNextId: item.id }).catch(() => {});
  }
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

function scheduleLiveLineupUpdate(reason = "Lineup changed", options = {}) {
  if (!liveSession?.playing) {
    return Promise.resolve(false);
  }
  liveLineupUpdatePromise = liveLineupUpdatePromise
    .catch(() => false)
    .then(() => refreshLiveLineup(reason, options));
  return liveLineupUpdatePromise;
}

// Decode any newly queued songs and re-plan everything after the playing song.
// The playing song is always sent first and locked, so the plan includes the
// transition out of it. options.pinnedNextId keeps a Play Next pick next;
// options.keepOrder follows the queue exactly (after a manual drag).
async function refreshLiveLineup(reason, options = {}) {
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
    let buffer;
    let analysis;
    try {
      const arrayBuffer = await source.loadArrayBuffer();
      if (liveSession !== session || !session.playing) {
        return false;
      }
      buffer = await session.context.decodeAudioData(arrayBuffer.slice(0));
      analysis = await fullAnalysis(item.trackId);
    } catch (error) {
      // One bad file should not stall the party: drop it and keep going.
      const index = liveQueue.findIndex((queued) => queued.id === item.id);
      if (index >= 0) {
        liveQueue.splice(index, 1);
      }
      showErrors([{ file_name: item.name, error: error.message || "Could not load this song for the live deck." }]);
      continue;
    }
    decodedByQueueId.set(item.id, decodedDeckTrack(item, buffer, analysis, null));
  }

  if (liveSession !== session || !session.playing) {
    return false;
  }

  const decodedPending = pendingItems.filter((item) => decodedByQueueId.has(item.id));
  const pinnedItem = decodedPending.find((item) => item.id === options.pinnedNextId) || null;
  const pendingTrackIds = unique([
    pinnedItem?.trackId,
    ...decodedPending.map((item) => item.trackId),
  ]);
  const currentTrackId = decodedByQueueId.get(initialCurrentId)?.trackId || null;
  let updatedPlan = null;
  let orderedTrackIds = pendingTrackIds;
  const planTrackIds = unique([currentTrackId, ...pendingTrackIds]);
  if (currentTrackId && planTrackIds.length >= 2) {
    setStatus("AI updating what plays next - current song stays live", 62);
    try {
      updatedPlan = await createPlan(planTrackIds, {
        autoOrder: els.autoOrder.checked && !options.keepOrder,
        lockedTrackCount: pinnedItem?.trackId ? 2 : 1,
        mixNamePrefix: "Party Lineup",
      });
      orderedTrackIds = (updatedPlan.track_order || planTrackIds).filter((trackId) => trackId !== currentTrackId);
    } catch (error) {
      console.warn("Live re-plan failed; keeping the queue order.", error);
    }
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
      applyPlacementToDeckTrack(track, plannedPlacementForTrack(updatedPlan, track.trackId));
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

async function fullAnalysis(trackId) {
  if (!trackId) {
    return null;
  }
  const cached = analyzedTracks.get(trackId) || selectedLibraryTracks.get(trackId);
  // Search results are summaries; the live deck needs the beat grid.
  const analysis = cached?.beats ? cached : await fetchTrack(trackId);
  selectedLibraryTracks.set(analysis.track_id, analysis);
  analyzedTracks.set(analysis.track_id, analysis);
  return analysis;
}

function decodedDeckTrack(item, buffer, analysis, placement) {
  const track = {
    queueId: item.queueId || item.id,
    trackId: item.trackId,
    name: item.name,
    bpm: analysis?.estimated_bpm || item.bpm || null,
    keyName: analysis?.key?.display_name || item.keyName || null,
    bars: (analysis?.beats?.approximate_bars || []).map((bar) => bar.start_time),
    beats: analysis?.beats?.beat_timestamps || [],
    buffer,
    startOffset: 0,
    plannedWindow: null,
  };
  applyPlacementToDeckTrack(track, placement);
  return track;
}

function applyPlacementToDeckTrack(track, placement) {
  track.startOffset = placement?.source_start_time || 0;
  track.plannedWindow =
    placement && placement.source_end_time > placement.source_start_time
      ? placement.source_end_time - placement.source_start_time
      : null;
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

// ---- Recommended next songs & Auto DJ -------------------------------------

function recommendationAnchor() {
  if (liveSession?.playing) {
    const current = liveSession.decodedQueue[liveSession.currentIndex];
    if (current?.trackId) {
      return { trackId: current.trackId, label: `After ${current.name}` };
    }
  }
  const last = [...liveQueue].reverse().find((item) => item.trackId);
  return last ? { trackId: last.trackId, label: `After ${last.name}` } : null;
}

function playedTrackIds() {
  if (!liveSession?.decodedQueue?.length) {
    return [];
  }
  return unique(liveSession.decodedQueue.slice(0, Math.max(0, liveSession.currentIndex)).map((track) => track.trackId));
}

async function fetchRecommendations(currentTrackId, limit = 5) {
  return fetchJson("/api/mixes/recommend-next", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_track_id: currentTrackId,
      played_track_ids: playedTrackIds(),
      queued_track_ids: unique(liveQueue.map((item) => item.trackId)),
      mix_direction: els.mixDirection.value.trim() || null,
      limit,
    }),
  });
}

function scheduleRecommendations() {
  window.clearTimeout(recommendTimer);
  recommendTimer = window.setTimeout(() => {
    refreshRecommendations().catch(() => {});
  }, 350);
}

async function refreshRecommendations() {
  const requestId = ++recommendRequestId;
  const anchor = recommendationAnchor();
  if (!anchor) {
    els.recommendAnchor.textContent = "After your queue";
    renderRecommendations([], "Queue an analyzed song and the AI will suggest what mixes best after it.");
    return;
  }
  els.recommendAnchor.textContent = anchor.label;
  try {
    const picks = await fetchRecommendations(anchor.trackId, 5);
    if (requestId === recommendRequestId) {
      renderRecommendations(picks, "No other saved songs to suggest yet - add more to the library.");
    }
  } catch {
    if (requestId === recommendRequestId) {
      renderRecommendations([], "Suggestions are unavailable right now.");
    }
  }
}

function renderRecommendations(picks, emptyText) {
  els.recommendList.innerHTML = "";
  if (!picks.length) {
    els.recommendList.appendChild(emptyItem(emptyText));
    return;
  }
  for (const [index, pick] of picks.entries()) {
    const row = document.createElement("li");
    row.className = `queue-item recommend-item${index === 0 ? " top" : ""}`;
    const keyText = pick.camelot ? `${pick.key} (${pick.camelot})` : pick.key;
    row.innerHTML = `
      <span class="recommend-score">${Math.round(pick.score * 100)}%</span>
      <div>
        <strong>${escapeHtml(pick.title || pick.file_name)}</strong>
        <div class="queue-meta">${escapeHtml(pick.genre)} - ${formatBpm(pick.bpm)} - ${escapeHtml(keyText)} - ${escapeHtml(
          transitionTechniqueLabel(pick.suggested_technique),
        )}</div>
        <div class="reason-tags">${pick.reasons.map((reason) => `<span>${escapeHtml(reason)}</span>`).join("")}</div>
      </div>
      <div class="queue-actions">
        <button type="button" data-action="next">Play Next</button>
        <button type="button" data-action="add">Add</button>
      </div>
    `;
    row.querySelector('[data-action="next"]').addEventListener("click", () => addRecommendedTrack(pick, true));
    row.querySelector('[data-action="add"]').addEventListener("click", () => addRecommendedTrack(pick, false));
    els.recommendList.appendChild(row);
  }
}

async function addRecommendedTrack(pick, playNext) {
  try {
    const track = await fetchTrack(pick.track_id);
    if (playNext) {
      // Add quietly, then cue: cueing triggers one live re-plan with the pick pinned next.
      selectedLibraryTracks.set(track.track_id, track);
      ensureQueueItem(queueItemForTrack(track));
      renderTracks();
      cueQueueItemNext(`track:${track.track_id}`);
      return;
    }
    addLibraryTrack(track, lastCatalogResults);
  } catch (error) {
    showErrors([{ file_name: pick.title || "Recommendation", error: error.message || "Could not add this song." }]);
  }
}

function queueItemForTrack(track) {
  return {
    id: `track:${track.track_id}`,
    type: "track",
    trackId: track.track_id,
    name: track.title || track.file_name,
    meta: formatTrackMeta(track),
  };
}

// Auto DJ: once the playing song is the last one queued, add the best match
// from the library so the set keeps going without a gap.
async function maybeAutoPick() {
  const session = liveSession;
  if (!session?.playing || !els.autoDj.checked || autoPickPending) {
    return;
  }
  const currentIndex = liveQueue.findIndex((item) => item.id === session.currentItemId);
  const upcoming = currentIndex >= 0 ? liveQueue.length - currentIndex - 1 : 0;
  const current = session.decodedQueue[session.currentIndex];
  if (upcoming > 0 || !current?.trackId) {
    return;
  }

  autoPickPending = true;
  try {
    const picks = await fetchRecommendations(current.trackId, 3);
    const pick = picks.find((candidate) => !liveQueue.some((item) => item.trackId === candidate.track_id));
    if (!pick || liveSession !== session || !session.playing) {
      if (!pick && liveSession === session) {
        setStatus("Auto DJ has no new songs left - add more to keep going", 46);
      }
      return;
    }
    const track = await fullAnalysis(pick.track_id);
    if (liveSession !== session || !session.playing) {
      return;
    }
    ensureQueueItem(queueItemForTrack(track));
    renderTracks();
    renderQueue();
    await scheduleLiveLineupUpdate(`Auto DJ picked ${track.title || track.file_name}`);
  } catch (error) {
    console.warn("Auto DJ could not pick a song.", error);
  } finally {
    autoPickPending = false;
  }
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
      meta: track ? formatTrackMeta(track) : item.meta,
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
  const master = context.createDynamicsCompressor();
  master.threshold.setValueAtTime(-10, context.currentTime);
  master.knee.setValueAtTime(12, context.currentTime);
  master.ratio.setValueAtTime(3, context.currentTime);
  master.attack.setValueAtTime(0.008, context.currentTime);
  master.release.setValueAtTime(0.28, context.currentTime);
  master.connect(context.destination);
  liveSession = {
    context,
    master,
    decodedQueue: [],
    currentIndex: -1,
    currentItemId: null,
    currentSource: null,
    currentGain: null,
    currentChannel: null,
    ratePlan: null,
    timers: [],
    activeSources: new Set(),
    playing: false,
    transitioning: false,
    plan,
    segmentSeconds: numericValue(els.playSeconds, 90),
    transitionSeconds: numericValue(els.transitionSeconds, 6),
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
    const analysis = sources[index].trackId ? await fullAnalysis(sources[index].trackId).catch(() => null) : null;
    liveSession.decodedQueue.push(
      decodedDeckTrack(sources[index], buffer, analysis, plannedPlacementForTrack(plan, sources[index].trackId)),
    );
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
  const playbackDuration = livePlaybackDuration(track);
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
  liveSession.ratePlan = { startedAt: now, offset, rate: 1, glideStart: null, glideEnd: null };
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
  maybeAutoPick();
}

// Start each song on a downbeat: snap the planned entry to the nearest bar line.
function liveTrackStartOffset(track) {
  const requested = Number.isFinite(track.startOffset) ? track.startOffset : 0;
  const barSeconds = 240 / (track.bpm || 120);
  let offset = requested;
  let bestDistance = Infinity;
  for (const barStart of track.bars || []) {
    const distance = Math.abs(barStart - requested);
    if (distance <= barSeconds && distance < bestDistance) {
      offset = barStart;
      bestDistance = distance;
    }
    if (barStart > requested + barSeconds) {
      break;
    }
  }
  const latest = Math.max(0, track.buffer.duration - 1);
  return Math.max(0, Math.min(offset, latest));
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

// Play the rest of the song; transitions stop the outgoing source explicitly.
// If nothing is queued yet, the song simply keeps going instead of cutting out.
function livePlaybackDuration(track) {
  return Math.max(0.1, track.buffer.duration - liveTrackStartOffset(track));
}

function playbackRateAt(time) {
  const plan = liveSession?.ratePlan;
  if (!plan) {
    return 1;
  }
  if (!plan.glideStart || time <= plan.glideStart) {
    return plan.rate;
  }
  if (time >= plan.glideEnd) {
    return 1;
  }
  return plan.rate + (1 - plan.rate) * ((time - plan.glideStart) / (plan.glideEnd - plan.glideStart));
}

// Where the playing song's playhead is (in song seconds) at a context time,
// accounting for the post-blend glide back to its native tempo.
function bufferPositionAt(time) {
  const plan = liveSession?.ratePlan;
  if (!plan) {
    return 0;
  }
  const t = Math.max(plan.startedAt, time);
  if (!plan.glideStart || t <= plan.glideStart) {
    return plan.offset + (t - plan.startedAt) * plan.rate;
  }
  const glideLength = plan.glideEnd - plan.glideStart;
  const inGlide = Math.min(t, plan.glideEnd) - plan.glideStart;
  let position = plan.offset + (plan.glideStart - plan.startedAt) * plan.rate;
  position += inGlide * plan.rate + ((1 - plan.rate) * inGlide * inGlide) / (2 * glideLength);
  if (t > plan.glideEnd) {
    position += t - plan.glideEnd;
  }
  return position;
}

// Seconds to wait so the blend starts on the outgoing song's next bar line.
// Manual "Mix Next Now" falls back to the next beat when bar data is missing.
function quantizedTransitionDelay(track, earliest) {
  const bars = track?.bars || [];
  const beats = track?.beats || [];
  if (!bars.length && !beats.length) {
    return 0;
  }
  const rate = Math.max(0.5, playbackRateAt(earliest));
  const position = bufferPositionAt(earliest);
  const barSeconds = 240 / (track.bpm || 120);
  const nextBar = bars.find((time) => time >= position + 0.01);
  if (nextBar !== undefined && nextBar - position <= barSeconds * 1.02) {
    return (nextBar - position) / rate;
  }
  const nextBeat = beats.find((time) => time >= position + 0.01);
  if (nextBeat !== undefined && nextBeat - position <= 1.5) {
    return (nextBeat - position) / rate;
  }
  return 0;
}

function foldedTempoRatio(fromBpm, toBpm) {
  if (!fromBpm || !toBpm) {
    return 1;
  }
  return [toBpm / fromBpm, toBpm / 2 / fromBpm, (toBpm * 2) / fromBpm].reduce((best, ratio) =>
    Math.abs(ratio - 1) < Math.abs(best - 1) ? ratio : best,
  );
}

function isSafeTempoRatio(ratio) {
  return ratio >= SAFE_TEMPO_RATIO[0] && ratio <= SAFE_TEMPO_RATIO[1];
}

function transitionToNextTrack(manual) {
  if (!liveSession) {
    return;
  }
  if (liveSession.transitioning) {
    if (manual) {
      setStatus("Still blending - the next mix is available when this blend lands", 50);
    }
    return;
  }

  const nextIndex = liveSession.currentIndex + 1;
  if (nextIndex >= liveSession.decodedQueue.length) {
    handleQueueRunningOut(manual);
    return;
  }

  clearLiveTimers();
  liveSession.transitioning = true;
  const { context } = liveSession;
  const nextTrack = liveSession.decodedQueue[nextIndex];
  const currentTrack = liveSession.decodedQueue[liveSession.currentIndex];
  const earliest = context.currentTime + 0.05;
  const downbeatDelay = quantizedTransitionDelay(currentTrack, earliest);
  // "now" is when the blend starts: the outgoing song's next downbeat.
  const now = earliest + downbeatDelay;
  const transition = transitionSecondsBetween(currentTrack, nextTrack);
  const plannedTransition = plannedTransitionBetween(currentTrack, nextTrack);
  const technique = plannedTransition?.technique || "phrase_blend";
  const transitionEffects = liveTransitionEffects(currentTrack, nextTrack);
  const outgoingRate = playbackRateAt(now);
  const playbackRate = aiPlaybackRateForNext(currentTrack, outgoingRate, nextTrack, technique);
  const nextOffset = liveTrackStartOffset(nextTrack);
  const nextWindow = livePreTransitionWindow(
    nextTrack,
    liveSession.decodedQueue[nextIndex + 1] ? transitionSecondsBetween(nextTrack, liveSession.decodedQueue[nextIndex + 1]) : transition,
  );
  const nextSource = context.createBufferSource();
  const slamMove = SLAM_MOVES.has(technique);
  const laneMove = Boolean(plannedTransition?.automation?.length);
  const nextChannel = createLiveChannel(context, now, laneMove || slamMove || technique === "eq_blend" ? 0 : -12);

  nextSource.buffer = nextTrack.buffer;
  nextSource.playbackRate.setValueAtTime(playbackRate, now);
  nextSource.connect(nextChannel.eq);
  nextChannel.gain.gain.setValueAtTime(0.0001, now);
  nextSource.start(now, nextOffset, livePlaybackDuration(nextTrack));
  const glide = scheduleTempoGlideHome(nextSource, nextTrack, playbackRate, now + transition);
  liveSession.activeSources.add(nextSource);

  holdPlaybackRate(liveSession.currentSource, now, outgoingRate);
  const outgoing = {
    track: currentTrack,
    source: liveSession.currentSource,
    channel: liveSession.currentChannel,
    rate: outgoingRate,
  };
  // One beat of the outgoing song in real (wall-clock) seconds.
  const beatSeconds = (plannedTransition?.beat_seconds || 60 / (currentTrack.bpm || 120)) / Math.max(0.5, outgoingRate);
  let stopAt;
  if (plannedTransition?.automation?.length) {
    stopAt = performAutomation(plannedTransition.automation, outgoing, nextChannel, now, transition, beatSeconds, plannedTransition.beat_seconds);
  } else if (slamMove) {
    const entry = plannedTransition?.incoming_entry_position ?? (technique === "reverb_wash" ? 0.5 : 1);
    scheduleSlamIn(nextChannel.gain.gain, now, now + transition * entry);
    stopAt = scheduleOutgoingMove(technique, outgoing, now, transition, beatSeconds);
  } else if (technique === "eq_blend") {
    scheduleEqBlend(outgoing.channel, nextChannel, now, transition);
    stopAt = now + transition + 0.08;
  } else {
    scheduleEqualPowerFade(nextChannel.gain.gain, now, transition, true, technique);
    const bassSwap = Math.max(0.25, Math.min(0.82, plannedTransition?.bass_swap_position || 0.58));
    scheduleBassHandoff(nextChannel.eq.gain, now, transition, bassSwap, true);
    if (outgoing.channel) {
      outgoing.channel.gain.gain.cancelScheduledValues(now);
      scheduleEqualPowerFade(outgoing.channel.gain.gain, now, transition, false, technique);
      scheduleBassHandoff(outgoing.channel.eq.gain, now, transition, bassSwap, false);
    }
    scheduleTempoHandoff(outgoing.source, outgoingRate, currentTrack, nextTrack, now, transition, technique);
    scheduleTechniqueFilters(outgoing.channel, nextChannel, now, transition, technique);
    const loopBed = scheduleOutgoingLoopBed(currentTrack, now, transition, plannedTransition);
    stopAt = now + transition + (loopBed ? 0.18 : 0.08);
  }
  if (outgoing.source) {
    try {
      outgoing.source.stop(stopAt);
    } catch {
      // Source may already have reached its scheduled ending.
    }
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
  liveSession.ratePlan = {
    startedAt: now,
    offset: nextOffset,
    rate: playbackRate,
    glideStart: glide?.start ?? null,
    glideEnd: glide?.end ?? null,
  };
  liveSession.timers.push(
    window.setTimeout(() => {
      if (liveSession?.currentSource === nextSource) {
        liveSession.transitioning = false;
      }
    }, (downbeatDelay + transition) * 1000 + 120),
  );
  liveSession.timers.push(
    window.setTimeout(() => transitionToNextTrack(false), Math.max(1000, (downbeatDelay + nextWindow) * 1000)),
  );
  const onBeat = downbeatDelay > 0 ? " on the downbeat" : "";
  setStatus(`${manual ? "Manual" : "AI"} ${transitionTechniqueLabel(technique)}${onBeat} - ${transition.toFixed(1)} sec`, 52);
  renderQueue();
  maybeAutoPick();
}

// Nothing left to blend into. With Auto DJ on, pick a song and retry while the
// current one keeps playing; otherwise let it play out and end the set.
function handleQueueRunningOut(manual) {
  const session = liveSession;
  const current = session?.decodedQueue?.[session.currentIndex];
  const position = bufferPositionAt(session.context.currentTime);
  const stillPlaying = current && position < current.buffer.duration - 0.25;
  if (stillPlaying && (els.autoDj.checked || autoPickPending)) {
    setStatus(manual ? "Auto DJ is finding the next song" : "Auto DJ picking the next song - music keeps playing", 46);
    maybeAutoPick();
    session.timers.push(window.setTimeout(() => transitionToNextTrack(false), 2000));
    return;
  }
  if (stillPlaying) {
    if (manual) {
      setStatus("No next track queued - turn on Auto DJ or add a song", 45);
    }
    return;
  }
  stopLiveMix();
  setStatus("Set complete", 100);
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
  const planned = plannedTransitionBetween(sourceTrack, targetTrack);
  if (planned?.duration_seconds && (!blendSecondsTouched || BAR_LOCKED_MOVES.has(planned.technique))) {
    // Bar-locked moves keep their exact planned length so the next song lands on the "1".
    return Math.max(0.5, Math.min(MAX_BLEND_SECONDS, planned.duration_seconds));
  }
  return Math.max(2, Math.min(MAX_BLEND_SECONDS, numericValue(els.transitionSeconds, liveSession.transitionSeconds)));
}

// Rate for the incoming song so its beats match what the room hears right now
// (the outgoing song's native BPM times its current playback rate).
function aiPlaybackRateForNext(currentTrack, currentRate, nextTrack, technique = null) {
  if (technique === "tempo_handoff" || !currentTrack?.bpm || !nextTrack?.bpm) {
    return 1;
  }
  const rate = 1 / foldedTempoRatio(currentTrack.bpm * currentRate, nextTrack.bpm);
  return isSafeTempoRatio(rate) ? rate : 1;
}

// After the blend, ease a pitched song back to its own tempo over ~16 beats so
// small adjustments never pile up from song to song.
function scheduleTempoGlideHome(source, track, rate, startTime) {
  if (!source?.playbackRate || Math.abs(rate - 1) < 0.002) {
    return null;
  }
  const glideSeconds = Math.max(6, Math.min(14, (16 * 60) / (track.bpm || 120)));
  source.playbackRate.setValueAtTime(rate, startTime);
  source.playbackRate.linearRampToValueAtTime(1, startTime + glideSeconds);
  return { start: startTime, end: startTime + glideSeconds };
}

// Freeze the outgoing song's tempo for the blend (it may still be gliding home).
function holdPlaybackRate(source, time, rate) {
  const param = source?.playbackRate;
  if (!param) {
    return;
  }
  if (typeof param.cancelAndHoldAtTime === "function") {
    param.cancelAndHoldAtTime(time);
  } else {
    param.cancelScheduledValues(time);
  }
  param.setValueAtTime(rate, time);
}

function scheduleTempoHandoff(source, currentRate, currentTrack, nextTrack, startTime, duration, technique) {
  if (technique !== "tempo_handoff" || !source?.playbackRate || !currentTrack?.bpm || !nextTrack?.bpm) {
    return;
  }
  const targetRate = foldedTempoRatio(currentTrack.bpm, nextTrack.bpm);
  if (!isSafeTempoRatio(targetRate)) {
    return;
  }
  source.playbackRate.cancelScheduledValues(startTime);
  source.playbackRate.setValueAtTime(Math.max(0.94, Math.min(1.06, currentRate)), startTime);
  source.playbackRate.linearRampToValueAtTime(targetRate, startTime + duration * 0.72);
  source.playbackRate.setValueAtTime(targetRate, startTime + duration);
}

function createLiveChannel(context, now, initialBassDb = 0) {
  const eq = context.createBiquadFilter();
  const mid = context.createBiquadFilter();
  const treble = context.createBiquadFilter();
  const hpf = context.createBiquadFilter();
  const filter = context.createBiquadFilter();
  const gain = context.createGain();
  const delay = context.createDelay(1.2);
  const feedback = context.createGain();
  const delayWet = context.createGain();
  eq.type = "lowshelf";
  eq.frequency.setValueAtTime(180, now);
  eq.gain.setValueAtTime(initialBassDb, now);
  mid.type = "peaking";
  mid.frequency.setValueAtTime(1000, now);
  mid.Q.setValueAtTime(0.7, now);
  mid.gain.setValueAtTime(0, now);
  hpf.type = "highpass";
  hpf.frequency.setValueAtTime(10, now);
  hpf.Q.setValueAtTime(1.1, now);
  treble.type = "highshelf";
  treble.frequency.setValueAtTime(3000, now);
  treble.gain.setValueAtTime(0, now);
  filter.type = "lowpass";
  filter.frequency.setValueAtTime(20000, now);
  filter.Q.setValueAtTime(0.5, now);
  delay.delayTime.setValueAtTime(0.18, now);
  feedback.gain.setValueAtTime(0.0001, now);
  delayWet.gain.setValueAtTime(0.0001, now);
  eq.connect(mid);
  mid.connect(treble);
  treble.connect(hpf);
  hpf.connect(filter);
  filter.connect(gain);
  gain.connect(liveSession?.master || context.destination);
  gain.connect(delay);
  delay.connect(feedback);
  feedback.connect(delay);
  delay.connect(delayWet).connect(liveSession?.master || context.destination);
  return { eq, mid, treble, hpf, filter, gain, delay, feedback, delayWet };
}

// ---- Automation lanes (deep moves) ------------------------------------------
// The planner sends each deep transition as lanes; the WAV renderer performs the
// same lanes in Python (automation_engine.py), so live and download match.

const LANE_STEPS = 96;

function sampleLane(points, param, steps = LANE_STEPS) {
  const sorted = [...points].sort((a, b) => a[0] - b[0]);
  const curve = new Float32Array(steps);
  const logScale = param === "hpf" || param === "lpf";
  for (let step = 0; step < steps; step += 1) {
    const x = step / (steps - 1);
    curve[step] = laneValueAt(sorted, x, param, logScale);
  }
  return curve;
}

function laneValueAt(sorted, x, param, logScale = param === "hpf" || param === "lpf") {
  if (x <= sorted[0][0]) {
    return param === "loop" && x < sorted[0][0] ? 0 : sorted[0][1];
  }
  for (let index = 1; index < sorted.length; index += 1) {
    const [x1, y1] = sorted[index];
    if (x <= x1) {
      const [x0, y0] = sorted[index - 1];
      if (param === "loop") {
        return x === x1 ? y1 : y0;
      }
      const t = x1 > x0 ? (x - x0) / (x1 - x0) : 1;
      return logScale
        ? Math.exp(Math.log(Math.max(1, y0)) + (Math.log(Math.max(1, y1)) - Math.log(Math.max(1, y0))) * t)
        : y0 + (y1 - y0) * t;
    }
  }
  return sorted[sorted.length - 1][1];
}

function dbToGain(db) {
  return 10 ** (db / 20);
}

function channelParam(channel, param) {
  switch (param) {
    case "gain":
      return channel.gain.gain;
    case "low":
      return channel.eq.gain;
    case "mid":
      return channel.mid.gain;
    case "high":
      return channel.treble.gain;
    case "hpf":
      return channel.hpf.frequency;
    case "lpf":
      channel.filter.type = "lowpass";
      return channel.filter.frequency;
    default:
      return null;
  }
}

// Run every lane for both decks. Returns when the outgoing source can stop.
function performAutomation(lanes, out, inChannel, start, duration, beatSeconds, beatInBuffer) {
  const decks = { out: out.channel, in: inChannel };
  let stopAt = start + duration + 0.05;
  for (const lane of lanes) {
    const channel = decks[lane.deck];
    if (!channel || !lane.points?.length) {
      continue;
    }
    if (lane.param === "echo") {
      scheduleEchoLane(channel, lane.points, start, duration, beatSeconds);
      continue;
    }
    if (lane.param === "rate" || lane.param === "loop") {
      continue; // handled together below
    }
    const target = channelParam(channel, lane.param);
    if (!target) {
      continue;
    }
    const curve = sampleLane(lane.points, lane.param);
    if (lane.param === "gain") {
      for (let index = 0; index < curve.length; index += 1) {
        curve[index] = Math.max(0.0001, curve[index]);
      }
    }
    target.cancelScheduledValues(start);
    target.setValueAtTime(curve[0], start);
    target.setValueCurveAtTime(curve, start, Math.max(0.05, duration));
  }

  const rateLane = lanes.find((lane) => lane.deck === "out" && lane.param === "rate");
  const loopLane = lanes.find((lane) => lane.deck === "out" && lane.param === "loop");
  const rateCurve = rateLane ? sampleLane(rateLane.points, "rate").map((value) => value * out.rate) : null;
  if (rateCurve && out.source?.playbackRate) {
    out.source.playbackRate.cancelScheduledValues(start);
    out.source.playbackRate.setValueAtTime(rateCurve[0], start);
    out.source.playbackRate.setValueCurveAtTime(rateCurve, start, Math.max(0.05, duration));
  }
  if (loopLane && out.track?.buffer) {
    const engaged = scheduleLoopLane(out, loopLane.points, rateLane?.points || null, start, duration, beatInBuffer);
    if (engaged !== null) {
      stopAt = engaged + 0.004;
    }
  }
  return stopAt;
}

// Echo send: 3/4-beat delay; feedback rings on after the lane ends, then dies away.
function scheduleEchoLane(channel, points, start, duration, beatSeconds) {
  const send = sampleLane(points, "echo");
  const wet = send.map((value) => Math.max(0.0001, value * 0.6));
  const feedback = send.map((value) => Math.max(0.0001, Math.min(0.5, value * 0.9)));
  channel.delay.delayTime.cancelScheduledValues(start);
  channel.delay.delayTime.setValueAtTime(Math.min(1.1, beatSeconds * 0.75), start);
  for (const [param, curve] of [
    [channel.delayWet.gain, wet],
    [channel.feedback.gain, feedback],
  ]) {
    param.cancelScheduledValues(start);
    param.setValueAtTime(curve[0], start);
    param.setValueCurveAtTime(curve, start, Math.max(0.05, duration));
    param.setValueAtTime(curve[curve.length - 1], start + duration + 0.01);
    param.exponentialRampToValueAtTime(0.0001, start + duration + 2.5);
  }
}

// Loop lane: once the loop engages the outgoing song stays on a loop of the given
// length (in beats), re-anchored at the same point, following the rate lane.
function scheduleLoopLane(out, loopPoints, ratePoints, start, duration, beatInBuffer) {
  const sorted = [...loopPoints].sort((a, b) => a[0] - b[0]);
  const rateSorted = ratePoints ? [...ratePoints].sort((a, b) => a[0] - b[0]) : null;
  const rateAt = (x) => (rateSorted ? laneValueAt(rateSorted, x, "rate") : 1) * out.rate;
  const segments = [];
  for (let index = 0; index < sorted.length; index += 1) {
    const [x, beats] = sorted[index];
    const next = index + 1 < sorted.length ? sorted[index + 1][0] : 1;
    if (beats > 0 && next > x) {
      segments.push({ from: x, to: next, beats });
    }
  }
  if (!segments.length) {
    return null;
  }
  // Where the playhead is when the loop engages (integrate the rate up to that point).
  const engageX = segments[0].from;
  let anchor = bufferPositionAt(start);
  const integrationSteps = 32;
  for (let step = 0; step < integrationSteps; step += 1) {
    const x = (engageX * (step + 0.5)) / integrationSteps;
    anchor += rateAt(x) * ((engageX * duration) / integrationSteps);
  }
  const { context } = liveSession;
  const beatBuffer = beatInBuffer || 60 / (out.track.bpm || 120);
  for (const segment of segments) {
    const segStart = start + segment.from * duration;
    const segEnd = start + segment.to * duration;
    const loop = context.createBufferSource();
    loop.buffer = out.track.buffer;
    loop.loop = true;
    loop.loopStart = anchor;
    loop.loopEnd = Math.min(out.track.buffer.duration, anchor + Math.max(0.02, segment.beats * beatBuffer));
    const steps = 24;
    const rates = new Float32Array(steps);
    for (let step = 0; step < steps; step += 1) {
      rates[step] = rateAt(segment.from + ((segment.to - segment.from) * step) / (steps - 1));
    }
    loop.playbackRate.setValueAtTime(rates[0], segStart);
    loop.playbackRate.setValueCurveAtTime(rates, segStart, Math.max(0.02, segEnd - segStart));
    loop.connect(out.channel.eq);
    loop.start(segStart, anchor);
    loop.stop(segEnd + 0.003);
    trackLiveSource(loop);
  }
  return start + engageX * duration;
}

// ---- Party moves -----------------------------------------------------------

// Smoothstep from one value to another between two fractions of a window.
function scheduleSmoothRamp(param, start, duration, from, to, startFraction = 0, endFraction = 1) {
  const steps = 48;
  const curve = new Float32Array(steps);
  for (let step = 0; step < steps; step += 1) {
    const x = step / (steps - 1);
    curve[step] = from + (to - from) * x * x * (3 - 2 * x);
  }
  const rampStart = start + duration * startFraction;
  param.setValueAtTime(from, rampStart);
  param.setValueCurveAtTime(curve, rampStart, Math.max(0.01, duration * (endFraction - startFraction)));
}

// The next song stays silent, then hits full level exactly on its downbeat.
function scheduleSlamIn(gainParam, start, entryTime) {
  const rampStart = Math.max(start, entryTime - 0.006);
  gainParam.setValueAtTime(0.0001, rampStart);
  gainParam.linearRampToValueAtTime(1, Math.max(rampStart + 0.002, entryTime));
}

// Long club blend on a three-band mixer: incoming highs, then mids, a quick bass
// swap in the middle (never two basslines at once), outgoing highs leave last.
function scheduleEqBlend(outChannel, inChannel, start, duration) {
  scheduleSmoothRamp(inChannel.gain.gain, start, duration, 0.0001, 1, 0, 0.42);
  scheduleSmoothRamp(inChannel.eq.gain, start, duration, -26, 0, 0.48, 0.53);
  if (!outChannel) {
    return;
  }
  outChannel.gain.gain.cancelScheduledValues(start);
  outChannel.eq.gain.cancelScheduledValues(start);
  outChannel.treble.gain.cancelScheduledValues(start);
  scheduleSmoothRamp(outChannel.eq.gain, start, duration, 0, -26, 0.48, 0.53);
  scheduleSmoothRamp(outChannel.treble.gain, start, duration, 0, -15, 0.62, 0.95);
  scheduleSmoothRamp(outChannel.gain.gain, start, duration, 1, 0.0001, 0.55, 0.98);
}

// Outgoing exit for slam moves. Returns when the outgoing source can stop.
function scheduleOutgoingMove(technique, out, start, duration, beatSeconds) {
  const end = start + duration;
  const gain = out.channel?.gain?.gain;
  if (!gain || !out.source) {
    return end;
  }
  gain.cancelScheduledValues(start);
  gain.setValueAtTime(1, start);

  if (technique === "kill_cut") {
    // Pull the bass out over the bar so the room feels the gap, stop dead on the 1.
    out.channel.eq.gain.cancelScheduledValues(start);
    scheduleSmoothRamp(out.channel.eq.gain, start, duration, 0, -30, 0, 0.25);
    gain.setValueAtTime(1, end - 0.012);
    gain.linearRampToValueAtTime(0.0001, end);
    return end + 0.02;
  }
  if (technique === "power_down") {
    // Turntable stop over the last beat and a half.
    const stopStart = Math.max(start, end - beatSeconds * 1.5);
    out.source.playbackRate.setValueAtTime(out.rate, stopStart);
    out.source.playbackRate.exponentialRampToValueAtTime(0.03, end);
    gain.setValueAtTime(1, stopStart);
    gain.linearRampToValueAtTime(0.0001, end);
    return end + 0.02;
  }
  if (technique === "spinback") {
    const spinStart = Math.max(start, end - beatSeconds);
    scheduleBackspin(out, spinStart, end);
    gain.setValueAtTime(1, spinStart);
    gain.linearRampToValueAtTime(0.0001, spinStart + 0.015);
    return spinStart + 0.03;
  }
  if (technique === "roll_build") {
    scheduleLoopRoll(out, start, duration, beatSeconds);
    gain.linearRampToValueAtTime(0.0001, start + 0.01);
    return start + 0.03;
  }
  if (technique === "reverb_wash") {
    scheduleReverbWash(out.channel, start, duration);
    scheduleSmoothRamp(gain, start, duration, 1, 0.0001, 0.1, 0.5);
    return end + 0.05;
  }
  return end;
}

// Throw the record backwards: play the last moment of audio reversed, fast then slowing.
function scheduleBackspin(out, spinStart, end) {
  const { context } = liveSession;
  const source = out.track.buffer;
  const playhead = Math.min(source.duration, bufferPositionAt(spinStart));
  const seconds = Math.min(playhead, 1.6);
  const frames = Math.floor(seconds * source.sampleRate);
  if (frames < 64) {
    return;
  }
  const reversed = context.createBuffer(source.numberOfChannels, frames, source.sampleRate);
  const startFrame = Math.floor((playhead - seconds) * source.sampleRate);
  for (let channel = 0; channel < source.numberOfChannels; channel += 1) {
    const input = source.getChannelData(channel).subarray(startFrame, startFrame + frames);
    const output = reversed.getChannelData(channel);
    for (let index = 0; index < frames; index += 1) {
      output[index] = input[frames - 1 - index];
    }
  }
  const spin = context.createBufferSource();
  const spinGain = context.createGain();
  spin.buffer = reversed;
  spin.playbackRate.setValueAtTime(3.2, spinStart);
  spin.playbackRate.exponentialRampToValueAtTime(0.15, end);
  spinGain.gain.setValueAtTime(0.9, spinStart);
  spinGain.gain.linearRampToValueAtTime(0.0001, end);
  spin.connect(spinGain).connect(liveSession.master);
  spin.start(spinStart);
  spin.stop(end + 0.05);
  trackLiveSource(spin);
}

// Loop roll that halves every quarter (1 beat, 1/2, 1/4, 1/8) as the bass filters out.
function scheduleLoopRoll(out, start, duration, beatSeconds) {
  const { context } = liveSession;
  const playhead = bufferPositionAt(start);
  const beatInBuffer = beatSeconds * out.rate;
  const channel = createLiveChannel(context, start, 0);
  channel.filter.type = "highpass";
  channel.filter.frequency.setValueAtTime(30, start);
  channel.filter.frequency.exponentialRampToValueAtTime(550, start + duration * 0.92);
  channel.gain.gain.setValueAtTime(1, start);
  channel.gain.gain.linearRampToValueAtTime(1.35, start + duration - 0.012);
  channel.gain.gain.linearRampToValueAtTime(0.0001, start + duration);
  const quarter = duration / 4;
  for (let step = 0; step < 4; step += 1) {
    const roll = context.createBufferSource();
    roll.buffer = out.track.buffer;
    roll.loop = true;
    roll.loopStart = playhead;
    roll.loopEnd = Math.min(out.track.buffer.duration, playhead + beatInBuffer / 2 ** step);
    roll.playbackRate.setValueAtTime(out.rate, start);
    roll.connect(channel.eq);
    roll.start(start + step * quarter, playhead);
    roll.stop(start + (step + 1) * quarter + 0.004);
    trackLiveSource(roll);
  }
}

// Send the outgoing song into a big reverb, let the dry signal go, keep the wash.
function scheduleReverbWash(channel, start, duration) {
  const { context } = liveSession;
  if (!liveSession.reverb) {
    const seconds = 2.2;
    const impulse = context.createBuffer(2, Math.floor(seconds * context.sampleRate), context.sampleRate);
    for (let c = 0; c < 2; c += 1) {
      const data = impulse.getChannelData(c);
      for (let index = 0; index < data.length; index += 1) {
        data[index] = (Math.random() * 2 - 1) * Math.exp((-3.2 * index) / context.sampleRate);
      }
    }
    liveSession.reverb = context.createConvolver();
    liveSession.reverb.buffer = impulse;
    liveSession.reverbReturn = context.createGain();
    liveSession.reverbReturn.gain.setValueAtTime(0.3, context.currentTime);
    liveSession.reverb.connect(liveSession.reverbReturn).connect(liveSession.master);
  }
  const highpass = context.createBiquadFilter();
  const send = context.createGain();
  highpass.type = "highpass";
  highpass.frequency.setValueAtTime(250, start);
  send.gain.setValueAtTime(0.0001, start);
  send.gain.linearRampToValueAtTime(1, start + duration * 0.35);
  send.gain.linearRampToValueAtTime(0.0001, start + duration * 0.5);
  channel.filter.connect(highpass).connect(send).connect(liveSession.reverb);
  const disconnectAfter = (start - context.currentTime + duration + 3) * 1000;
  window.setTimeout(() => {
    try {
      highpass.disconnect();
      send.disconnect();
    } catch {
      // Already torn down with the session.
    }
  }, Math.max(0, disconnectAfter));
}

function trackLiveSource(source) {
  liveSession.activeSources.add(source);
  source.addEventListener("ended", () => liveSession?.activeSources?.delete(source));
}

function scheduleEqualPowerFade(gainParam, startTime, duration, fadeIn, technique = "phrase_blend") {
  const steps = 129;
  const curve = new Float32Array(steps);
  gainParam.cancelScheduledValues(startTime);
  for (let step = 0; step < steps; step += 1) {
    const progress = step / (steps - 1);
    let value;
    if (technique === "quick_cut") {
      const shifted = Math.max(0, Math.min(1, (progress - 0.08) / 0.84));
      const eased = shifted * shifted * (3 - 2 * shifted);
      value = fadeIn ? eased : 1 - eased;
    } else if (fadeIn) {
      const intro = Math.max(0, Math.min(1, progress / 0.3));
      const introEase = intro * intro * (3 - 2 * intro);
      const handoff = Math.max(0, Math.min(1, (progress - 0.3) / 0.7));
      const handoffEase = handoff * handoff * (3 - 2 * handoff);
      value = (0.1 * introEase) + (0.9 * handoffEase);
    } else {
      const fadeStart = ["phrase_blend", "tempo_handoff", "loop_echo_out"].includes(technique) ? 0.2 : 0.16;
      const shifted = Math.max(0, Math.min(1, (progress - fadeStart) / (0.95 - fadeStart)));
      const eased = shifted * shifted * (3 - 2 * shifted);
      value = 1 - eased;
    }
    curve[step] = Math.max(0.0001, Math.min(1, value));
  }
  gainParam.setValueCurveAtTime(curve, startTime, Math.max(0.05, duration));
}

function scheduleBassHandoff(gainParam, startTime, duration, swapPosition, incoming) {
  const steps = 97;
  const curve = new Float32Array(steps);
  const handoffWidth = 0.26;
  const start = Math.max(0.08, swapPosition - handoffWidth / 2);
  const end = Math.min(0.94, swapPosition + handoffWidth / 2);
  gainParam.cancelScheduledValues(startTime);
  for (let step = 0; step < steps; step += 1) {
    const progress = step / (steps - 1);
    const scaled = Math.max(0, Math.min(1, (progress - start) / Math.max(0.01, end - start)));
    const eased = scaled * scaled * (3 - 2 * scaled);
    curve[step] = incoming ? -12 * (1 - eased) : -12 * eased;
  }
  gainParam.setValueCurveAtTime(curve, startTime, Math.max(0.05, duration));
}

function scheduleTechniqueFilters(outgoingChannel, incomingChannel, startTime, duration, technique) {
  if (!["filter_blend", "tempo_handoff"].includes(technique) || !outgoingChannel?.filter || !incomingChannel?.filter) {
    return;
  }
  if (technique === "tempo_handoff") {
    incomingChannel.filter.type = "highpass";
    incomingChannel.filter.frequency.cancelScheduledValues(startTime);
    incomingChannel.filter.frequency.setValueAtTime(700, startTime);
    incomingChannel.filter.frequency.exponentialRampToValueAtTime(28, startTime + duration * 0.68);
    return;
  }
  outgoingChannel.filter.type = "lowpass";
  outgoingChannel.filter.frequency.cancelScheduledValues(startTime);
  outgoingChannel.filter.frequency.setValueAtTime(20000, startTime);
  outgoingChannel.filter.frequency.exponentialRampToValueAtTime(2200, startTime + duration * 0.92);

  incomingChannel.filter.type = "highpass";
  incomingChannel.filter.frequency.cancelScheduledValues(startTime);
  incomingChannel.filter.frequency.setValueAtTime(900, startTime);
  incomingChannel.filter.frequency.exponentialRampToValueAtTime(28, startTime + duration * 0.72);
}

function liveTransitionEffects(sourceTrack, targetTrack) {
  const planned = plannedTransitionBetween(sourceTrack, targetTrack);
  // An empty list is deliberate (clean moves); only fall back when there is no plan at all.
  return planned ? planned.sfx || [] : ["filter_sweep", "echo_tail"];
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
    transition_bars: 4,
    target_duration_minutes: Number.isFinite(targetMinutes) ? targetMinutes : null,
    max_play_seconds_per_track: useAiTiming ? null : playSeconds,
    auto_order: autoOrder,
    mix_direction: els.mixDirection.value.trim() || null,
    use_transition_sfx: els.useSfx.checked,
    use_trained_style: els.useTrainedStyle.checked,
    locked_track_count: options.lockedTrackCount || 0,
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

function scheduleOutgoingLoopBed(track, transitionStart, transitionSeconds, planned) {
  const loopSeconds = Number(planned?.outgoing_loop_seconds || 0);
  if (!liveSession || !track?.buffer || loopSeconds <= 0 || transitionSeconds < 2) {
    return null;
  }

  const { context } = liveSession;
  const playbackRate = Math.max(0.1, playbackRateAt(transitionStart));
  const playhead = Math.min(track.buffer.duration - 0.05, bufferPositionAt(transitionStart));
  const loopEnd = Math.max(loopSeconds, playhead);
  const loopStart = Math.max(0, loopEnd - loopSeconds);
  if (loopEnd - loopStart < 0.1) {
    return null;
  }

  const source = context.createBufferSource();
  const channel = createLiveChannel(context, transitionStart, -10);
  source.buffer = track.buffer;
  source.loop = true;
  source.loopStart = loopStart;
  source.loopEnd = loopEnd;
  source.playbackRate.setValueAtTime(playbackRate, transitionStart);
  source.connect(channel.eq);
  const loopGain = new Float32Array(97);
  for (let step = 0; step < loopGain.length; step += 1) {
    const progress = step / (loopGain.length - 1);
    let value;
    if (progress < 0.2) {
      const rise = progress / 0.2;
      value = 0.38 * Math.sin(rise * Math.PI * 0.5);
    } else if (progress < 0.68) {
      value = 0.38;
    } else {
      const fall = (progress - 0.68) / 0.32;
      value = 0.38 * Math.cos(fall * Math.PI * 0.5) ** 0.7;
    }
    loopGain[step] = Math.max(0.0001, value);
  }
  channel.gain.gain.cancelScheduledValues(transitionStart);
  channel.gain.gain.setValueCurveAtTime(loopGain, transitionStart, transitionSeconds);
  scheduleBrowserChannelEffects(channel, transitionStart, transitionSeconds, planned?.sfx || ["echo_tail"]);
  source.start(transitionStart, loopStart);
  source.stop(transitionStart + transitionSeconds + 0.18);
  liveSession.activeSources.add(source);
  source.addEventListener("ended", () => liveSession?.activeSources?.delete(source));
  return source;
}

function transitionTechniqueLabel(technique) {
  return {
    phrase_blend: "phrase blend",
    echo_fade: "echo fade",
    filter_blend: "filter blend",
    tempo_handoff: "tempo handoff",
    bass_swap: "bass-swap blend",
    loop_echo_out: "loop-and-echo blend",
    drop_swap: "drop swap",
    quick_cut: "quick cut",
    eq_blend: "EQ blend",
    kill_cut: "bass-out cut",
    roll_build: "loop roll build",
    reverb_wash: "reverb wash",
    spinback: "spinback",
    power_down: "power-down",
    double_play: "double play (both songs together)",
    vocal_over: "vocal-over mashup",
    filter_swap: "resonant filter swap",
    loop_riser: "loop riser (repeat, speed up, switch)",
    key_lift: "key-change lift",
    beat_juggle: "beat juggle",
  }[technique] || "transition";
}

function formatTrackMeta(track) {
  return `${track.genre || "Open Format"} - ${formatBpm(track.estimated_bpm)} - ${track.key?.display_name || "Unknown key"}`;
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
