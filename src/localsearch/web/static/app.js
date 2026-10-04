// Plain fetch calls against our own API. No framework, no build step (research.md §5).

const $ = (id) => document.getElementById(id);
let currentResults = [];
let pollTimer = null;

// --- helpers ---------------------------------------------------------------

async function api(method, path, body) {
  const options = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) options.body = JSON.stringify(body);
  const response = await fetch(path, options);
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(payload?.error?.message || 'Something went wrong.');
    error.code = payload?.error?.code;
    throw error;
  }
  return payload;
}

function say(element, text, kind) {
  element.textContent = text;
  element.className = `message ${kind || ''}`;
  element.hidden = !text;
}

// --- configuration ---------------------------------------------------------

async function loadConfig() {
  const config = await api('GET', '/api/config');
  $('folder-path').value = config.folder_path || '';
  $('ollama-model').value = config.ollama_model || '';
  $('auto-reindex').checked = config.auto_reindex;

  if (config.index.exists) {
    $('index-summary').textContent =
      `${config.index.documents_indexed} documents indexed, ` +
      `${config.index.documents_skipped} skipped, built ${config.index.built_at}`;
  } else {
    $('index-summary').textContent = 'No index yet.';
  }
  return config;
}

async function saveConfig(patch, okText) {
  try {
    await api('PUT', '/api/config', patch);
    say($('config-message'), okText, 'ok');
    await loadConfig();
    pollStatus();
  } catch (error) {
    say($('config-message'), error.message, 'error');
  }
}

$('save-folder').onclick = () =>
  saveConfig({ folder_path: $('folder-path').value }, 'Folder saved.');

$('save-model').onclick = () =>
  saveConfig({ ollama_model: $('ollama-model').value }, 'Model saved.');

$('auto-reindex').onchange = (event) =>
  saveConfig(
    { auto_reindex: event.target.checked },
    event.target.checked ? 'Watching for changes.' : 'Automatic re-indexing is off.'
  );

// --- indexing --------------------------------------------------------------

$('start-index').onclick = async () => {
  try {
    const result = await api('POST', '/api/index');
    say(
      $('config-message'),
      result.rerun_pending
        ? 'Indexing is already running; another run is queued and will follow.'
        : 'Indexing started.',
      'ok'
    );
    pollStatus();
  } catch (error) {
    say($('config-message'), error.message, 'error');
  }
};

async function pollStatus() {
  if (pollTimer) clearTimeout(pollTimer);
  let status;
  try {
    status = await api('GET', '/api/index/status');
  } catch {
    return;
  }

  const running = status.state === 'running';
  $('progress').hidden = !running;
  $('start-index').disabled = running;

  if (running) {
    $('progress-bar').max = status.total || 1;
    $('progress-bar').value = status.processed;
    const trigger = status.trigger === 'watch' ? ' (started automatically — files changed)' : '';
    const queued = status.rerun_pending ? ' Another run is queued.' : '';
    $('progress-text').textContent =
      `${status.processed} of ${status.total}${trigger}: ${status.current_file || '…'}${queued}`;
  }

  // Changes made while the app was closed are found by comparing file details (FR-036).
  if (status.index_stale && !running) {
    $('stale-notice').hidden = false;
    $('stale-notice').textContent =
      'Your documents have changed since the index was built. Click "Start indexing" to refresh it.';
  } else {
    $('stale-notice').hidden = true;
  }

  if (status.errors && status.errors.length) {
    $('skipped-details').hidden = false;
    $('skipped-count').textContent = status.errors.length;
    $('skipped-list').innerHTML = '';
    for (const item of status.errors) {
      const li = document.createElement('li');
      li.textContent = `${item.name} — ${item.reason}`;
      $('skipped-list').appendChild(li);
    }
  }

  if (status.state === 'completed') {
    $('index-summary').textContent =
      `${status.documents_indexed} indexed, ${status.documents_skipped} skipped, ` +
      `${status.chunk_count} passages.`;
  } else if (status.state === 'failed') {
    say($('config-message'), status.message || 'Indexing failed.', 'error');
  }

  if (running) pollTimer = setTimeout(pollStatus, 700);
}

// --- search ----------------------------------------------------------------

$('search-form').onsubmit = async (event) => {
  event.preventDefault();
  $('summary').hidden = true;
  say($('search-message'), '', '');
  $('results').innerHTML = '';

  try {
    const payload = await api('POST', '/api/search', { query: $('query').value });
    currentResults = payload.results;

    // Zero results is a valid answer, not an error (FR-016).
    if (!currentResults.length) {
      say($('search-message'), 'No relevant passages found in your documents.', '');
      $('summarize').disabled = true;
      return;
    }
    renderResults(currentResults);
    await refreshSummarizeAvailability();
  } catch (error) {
    currentResults = [];
    $('summarize').disabled = true;
    say($('search-message'), error.message, 'error');
  }
};

function renderResults(results) {
  const list = $('results');
  list.innerHTML = '';
  for (const result of results) {
    const item = document.createElement('li');
    item.className = 'result';
    item.innerHTML = `
      <div class="result-head">
        <span class="result-name"></span>
        <span class="result-path"></span>
        <span class="result-score"></span>
      </div>
      <p class="result-snippet"></p>
      <div class="result-actions">
        <button class="secondary open">Open</button>
        <button class="secondary reveal">Show in Finder</button>
      </div>
      <p class="result-error" hidden></p>`;

    item.querySelector('.result-name').textContent = result.document_name;
    item.querySelector('.result-path').textContent = result.document_relative_path;
    item.querySelector('.result-score').textContent = `score ${result.score}`;
    item.querySelector('.result-snippet').textContent = result.snippet;

    const problem = item.querySelector('.result-error');
    const openWith = (mode) => async () => {
      problem.hidden = true;
      try {
        await api('POST', '/api/open', { document_path: result.document_path, mode });
      } catch (error) {
        // One missing file must not disturb the other results (FR-029).
        problem.textContent = error.message;
        problem.hidden = false;
      }
    };
    item.querySelector('.open').onclick = openWith('open');
    item.querySelector('.reveal').onclick = openWith('reveal');

    list.appendChild(item);
  }
}

// --- summarization ---------------------------------------------------------

async function refreshSummarizeAvailability() {
  try {
    const availability = await api('GET', '/api/summarize/availability');
    const usable = availability.available && currentResults.length > 0;
    $('summarize').disabled = !usable;
    // Explain rather than silently disable.
    $('summarize-reason').textContent = availability.available ? '' : availability.reason || '';
  } catch {
    $('summarize').disabled = true;
  }
}

$('summarize').onclick = async () => {
  $('summarize').disabled = true;
  $('summary').hidden = false;
  $('summary-text').textContent = 'Summarizing…';
  $('summary-model').textContent = '';
  $('summary-sources').textContent = '';

  try {
    const payload = await api('POST', '/api/summarize', {
      query: $('query').value,
      results: currentResults,
    });
    $('summary-text').textContent = payload.summary;
    $('summary-model').textContent = `via ${payload.model}`;
    $('summary-sources').textContent = `Drawn from results ${payload.source_ranks.join(', ')}.`;
  } catch (error) {
    // Results stay on screen and usable (FR-021, SC-006).
    $('summary').hidden = true;
    say($('search-message'), error.message, 'error');
  } finally {
    await refreshSummarizeAvailability();
  }
};

// --- start -----------------------------------------------------------------

loadConfig().then(pollStatus).then(refreshSummarizeAvailability);
