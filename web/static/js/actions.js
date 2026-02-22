/**
 * Actions sidebar, TOC, pills, footnotes, and progress indicator.
 * Depends on: utils.js (escapeHtml, isAtBottom, scrollToBottom)
 */

// Actions sidebar state
let actionIndex = 0;
let actionsMap = new Map(); // actionIndex -> {toolUse, toolResult, category, icon}
let pendingToolUses = []; // Queue for tool_use waiting for their results (supports parallel calls)
let lastAssistantBlock = null; // Track last assistant block for footnotes
let currentTurnActions = []; // Actions in current turn (for footnotes)
let streamingBlock = null; // Current block being streamed into
let streamingText = ''; // Accumulated markdown during streaming
let actionsFilterMode = localStorage.getItem('actionsFilterMode') || 'data';

// TOC (table of contents) state
let tocEntries = []; // Array of {headingElement, text, element}
let currentSidebarTab = localStorage.getItem('sidebarTab') || 'toc';

// Progress indicator state
let progressIndicator = null;
let progressDots = '';

// Store full values for expand buttons (indexed)
let expandDataStore = [];

/**
 * Icon mapping for tool categories
 */
const CATEGORY_ICONS = {
  'API:': 'ri-cloud-line',
  'Read:': 'ri-file-text-line',
  'Write:': 'ri-file-add-line',
  'Edit:': 'ri-edit-line',
  'Search:': 'ri-search-line',
  'Execute:': 'ri-play-line',
  'Query:': 'ri-database-2-line',
  'Shell:': 'ri-terminal-line',
  'Skill:': 'ri-magic-line',
  'Thinking:': 'ri-lightbulb-line',
  'System:': 'ri-settings-3-line',
  'Web:': 'ri-global-line',
  'Interaction:': 'ri-question-line',
};

/**
 * French translations for tool categories
 */
const CATEGORY_TRANSLATIONS = {
  // API
  'API: Matomo': 'API Matomo',
  'API: Metabase': 'API Metabase',
  'API: Matomo + Metabase': 'API Matomo + Metabase',
  'API: Matomo (curl)': 'API Matomo (curl)',
  'API: GitHub': 'API GitHub',
  'API: GitHub (clone)': 'API GitHub (clone)',
  'API: curl': 'API curl',
  // Read
  'Read: knowledge': 'Lecture de la base de connaissances',
  'Read: skill definition': 'Lecture d\'une définition de skill',
  'Read: skill code': 'Lecture du code d\'un skill',
  'Read: code': 'Lecture du code',
  'Read: docs': 'Lecture de la documentation',
  'Read: temp': 'Lecture d\'un fichier temporaire',
  'Read: other': 'Lecture d\'un fichier',
  // Write
  'Write: temp': 'Écriture d\'un fichier temporaire',
  'Write: interactive': 'Écriture d\'une appli',
  'Write: script': 'Rédaction d\'un programme',
  'Write: knowledge': 'Écriture dans la base de connaissances',
  'Write: other': 'Écriture d\'un fichier',
  // Edit
  'Edit: knowledge': 'Modification de la base de connaissances',
  'Edit: skill': 'Modification d\'un skill',
  'Edit: code': 'Modification du code',
  'Edit: other': 'Modification d\'un fichier',
  // Execute
  'Execute: script': 'Exécution d\'un programme',
  // Query
  'Query: SQLite': 'Requête SQLite',
  // Search
  'Search: codebase': 'Recherche dans le code',
  // System
  'Thinking: todo': 'Réflexion',
  'System: task': 'Liste de tâches',
  'Web: fetch': 'Requête web',
  'Interaction: ask user': 'Interaction',
};

// =============================================================================
// Category helpers
// =============================================================================

/**
 * Translate a category to French
 */
function translateCategory(category) {
  if (!category) return 'Action';
  // Exact match
  if (CATEGORY_TRANSLATIONS[category]) {
    return CATEGORY_TRANSLATIONS[category];
  }
  // Shell, Skill, Other: keep as-is
  if (category.startsWith('Shell: ') || category.startsWith('Skill: ') || category.startsWith('Other: ')) {
    return category;
  }
  return category;
}

/**
 * Get icon class for a category
 */
function getIconForCategory(category) {
  if (!category) return 'ri-tools-line';
  for (const [prefix, icon] of Object.entries(CATEGORY_ICONS)) {
    if (category.startsWith(prefix)) return icon;
  }
  return 'ri-tools-line';
}

// =============================================================================
// Filter
// =============================================================================

/**
 * Check if an action is a "data" type (knowledge read or has API calls)
 */
function isDataAction(toolUse, toolResult) {
  // Knowledge reads
  if (toolUse.category === 'Read: knowledge') return true;
  // Any action with API calls (Matomo, Metabase queries)
  if (toolResult?.api_calls?.length > 0) return true;
  return false;
}

/**
 * Apply the current filter to all pills (visibility + label updates)
 */
function applyActionsFilter() {
  const pills = document.querySelectorAll('.action-pill');
  pills.forEach(pill => {
    const idx = parseInt(pill.dataset.actionIndex);
    const action = actionsMap.get(idx);
    if (!action) return;

    const isData = isDataAction(action.toolUse, action.toolResult);
    if (actionsFilterMode === 'data' && !isData) {
      pill.classList.add('filtered-out');
    } else {
      pill.classList.remove('filtered-out');
    }

    // Re-render label (main/sub swap depends on filter mode)
    const labelEl = pill.querySelector('.action-pill-label');
    if (labelEl) {
      labelEl.innerHTML = pillLabelHtml(action.pillData);
    }
  });
}

/**
 * Initialize filter toggle listeners
 */
function initActionsFilterToggle() {
  const toggle = document.getElementById('actionsFilterToggle');
  if (!toggle) return;

  // Remove existing listeners by cloning
  const newToggle = toggle.cloneNode(true);
  toggle.replaceWith(newToggle);

  // Sync UI with current filter mode
  newToggle.querySelectorAll('.actions-filter-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.filter === actionsFilterMode);
  });

  newToggle.addEventListener('click', (e) => {
    const btn = e.target.closest('.actions-filter-btn');
    if (!btn) return;

    const filter = btn.dataset.filter;
    if (filter === actionsFilterMode) return;

    // Update active state
    newToggle.querySelectorAll('.actions-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    actionsFilterMode = filter;
    localStorage.setItem('actionsFilterMode', filter);
    applyActionsFilter();
  });
}

/**
 * Switch to detailed filter mode if needed
 */
function switchToDetailedMode() {
  if (actionsFilterMode === 'detailed') return;

  actionsFilterMode = 'detailed';

  // Update toggle UI
  const toggle = document.getElementById('actionsFilterToggle');
  if (toggle) {
    toggle.querySelectorAll('.actions-filter-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.filter === 'detailed');
    });
  }

  applyActionsFilter();
}

// =============================================================================
// Sidebar tabs (TOC / Actions)
// =============================================================================

/**
 * Initialize sidebar tab toggle (TOC / Actions)
 */
function initSidebarTabToggle() {
  const toggle = document.getElementById('sidebarTabToggle');
  const sidebar = document.getElementById('actionsSidebar');
  if (!toggle || !sidebar) return;

  // Remove existing listeners by cloning
  const newToggle = toggle.cloneNode(true);
  toggle.replaceWith(newToggle);

  // Sync UI with current tab (CSS uses data-active-tab for content visibility)
  syncSidebarTabState();

  newToggle.addEventListener('click', (e) => {
    const btn = e.target.closest('.sidebar-tab-btn');
    if (!btn) return;

    const tab = btn.dataset.tab;
    if (tab === currentSidebarTab) return;

    currentSidebarTab = tab;
    localStorage.setItem('sidebarTab', tab);
    syncSidebarTabState();
  });
}

/**
 * Switch to a specific sidebar tab
 */
function switchSidebarTab(tab) {
  if (tab === currentSidebarTab) return;

  currentSidebarTab = tab;
  localStorage.setItem('sidebarTab', tab);
  syncSidebarTabState();
}

/**
 * Force-sync sidebar tab visibility from localStorage.
 * CSS uses [data-active-tab] on the sidebar as single source of truth for content visibility.
 */
function syncSidebarTabState() {
  const sidebar = document.getElementById('actionsSidebar');
  const toggle = document.getElementById('sidebarTabToggle');

  if (sidebar) sidebar.dataset.activeTab = currentSidebarTab;
  if (toggle) {
    toggle.querySelectorAll('.sidebar-tab-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.tab === currentSidebarTab);
    });
  }
}

// =============================================================================
// TOC (Table of Contents)
// =============================================================================

/**
 * Add a TOC entry for an <h2> heading from an assistant message
 */
function addTocEntry(headingElement, text) {
  const tocContent = document.getElementById('tocContent');
  if (!tocContent) return;

  // Remove empty state if present
  const emptyState = tocContent.querySelector('.toc-empty');
  if (emptyState) emptyState.remove();

  const entry = document.createElement('div');
  entry.className = 'toc-entry';

  entry.innerHTML = `
    <div class="toc-entry-content">
      <div class="toc-entry-text">${escapeHtml(text)}</div>
    </div>
  `;

  // Click to scroll to the heading and update URL hash
  entry.addEventListener('click', () => {
    if (headingElement && headingElement.id) {
      history.replaceState(null, '', `#${headingElement.id}`);
      headingElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });

  tocContent.appendChild(entry);
  tocEntries.push({ headingElement, text, element: entry });
}

/**
 * Scan an assistant message block for <h2> headings and add them to the TOC
 */
function scanHeadingsForToc(block) {
  const headings = block.querySelectorAll('h2');
  for (const h2 of headings) {
    const text = h2.textContent.trim();
    if (!text) continue;

    const slug = generateSlug(text);
    h2.id = ensureUniqueId(slug);
    addTocEntry(h2, text);
  }
}

/**
 * Generate a URL-friendly slug from text
 */
function generateSlug(text) {
  return text
    .toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .substring(0, 60) || 'section';
}

/**
 * Ensure an element ID is unique in the document
 */
function ensureUniqueId(baseId) {
  if (!document.getElementById(baseId)) return baseId;
  let counter = 2;
  while (document.getElementById(`${baseId}-${counter}`)) {
    counter++;
  }
  return `${baseId}-${counter}`;
}

/**
 * Scroll to URL hash section on page load
 */
function scrollToHashSection() {
  const hash = window.location.hash;
  if (!hash) return;

  const element = document.getElementById(hash.substring(1));
  if (element) {
    // Delay to ensure DOM is ready
    setTimeout(() => {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 100);
  }
}

/**
 * Reset TOC state for new conversation
 */
function resetTocState() {
  tocEntries = [];

  const tocContent = document.getElementById('tocContent');
  if (tocContent) {
    tocContent.innerHTML = '<div class="toc-empty">Aucune section</div>';
  }
}

// =============================================================================
// Pill labels
// =============================================================================

/**
 * Extract label data for a pill (pure data, no presentation logic)
 * Returns { label: string, apiSummary: string|null }
 */
function extractPillData(toolUse, toolResult) {
  const category = toolUse.category || '';
  let label = translateCategory(category) || toolUse.tool || 'Action';
  let apiSummary = null;

  // For Read operations, show the filename
  if (category.startsWith('Read:') && toolUse.input?.file_path) {
    label = toolUse.input.file_path.split('/').pop();
  }

  // For direct API calls, show the method
  if (category.startsWith('API:') && toolResult?.api_calls?.length > 0) {
    const call = toolResult.api_calls[0];
    if (call.method) label = call.method;
    else if (call.sql) label = 'Requête SQL';
  }

  // Summarize API calls from non-API tools (scripts, etc.)
  if (toolResult?.api_calls?.length > 0 && !category.startsWith('API:')) {
    const counts = {};
    for (const call of toolResult.api_calls) {
      const source = call.source || 'API';
      counts[source] = (counts[source] || 0) + 1;
    }
    apiSummary = Object.entries(counts)
      .map(([source, count]) => {
        const name = source.charAt(0).toUpperCase() + source.slice(1);
        return `${count} requête${count > 1 ? 's' : ''} ${name}`;
      })
      .join(', ');
  }

  return { label, apiSummary };
}

/**
 * Render pill label HTML from pill data.
 * In data mode: API summary is prominent. In detailed mode: tool label is prominent.
 */
function pillLabelHtml({ label, apiSummary }) {
  const main = (actionsFilterMode === 'data' && apiSummary) ? apiSummary : label;
  const sub = (actionsFilterMode === 'data' && apiSummary) ? label : apiSummary;
  let html = `<span class="action-pill-label-main">${escapeHtml(main)}</span>`;
  if (sub) html += `<span class="action-pill-label-sub">${escapeHtml(sub)}</span>`;
  return html;
}

// =============================================================================
// Pills: creation, content, listeners
// =============================================================================

/**
 * Create an action pill and append to sidebar
 */
function createAndAppendAction(toolUse, toolResult) {
  actionIndex++;
  const idx = actionIndex;
  const category = toolUse.category || `Other: ${toolUse.tool}`;
  const icon = getIconForCategory(category);
  const pillData = extractPillData(toolUse, toolResult);

  // Store in map
  actionsMap.set(idx, { toolUse, toolResult, category, icon, pillData });
  currentTurnActions.push(idx);

  // Create pill element
  const pill = createActionPill(idx, icon, pillData, toolUse, toolResult);

  // Apply filter
  const isData = isDataAction(toolUse, toolResult);
  if (actionsFilterMode === 'data' && !isData) {
    pill.classList.add('filtered-out');
  }

  // Append to sidebar and keep it anchored at the bottom
  const actionsContent = document.getElementById('actionsContent');
  if (actionsContent) {
    actionsContent.appendChild(pill);
    scrollActionsToBottom();
  }

  // Also append to mobile offcanvas
  const offcanvasContent = document.getElementById('actionsOffcanvasContent');
  if (offcanvasContent) {
    offcanvasContent.appendChild(pill.cloneNode(true));
    // Re-attach event listeners to cloned element
    const clonedPill = offcanvasContent.lastElementChild;
    attachPillListeners(clonedPill, idx);
  }

  // Add footnote to current assistant block immediately (progressive)
  if (lastAssistantBlock) {
    let footnotes = lastAssistantBlock.querySelector('.action-footnotes');
    if (!footnotes) {
      footnotes = document.createElement('div');
      footnotes.className = 'action-footnotes';
      lastAssistantBlock.appendChild(footnotes);
    }
    const footnote = createFootnoteIcon(idx);
    if (footnote) footnotes.appendChild(footnote);
  }

}

/**
 * Create a pill element for an action
 */
function createActionPill(idx, icon, pillData, toolUse, toolResult) {
  const pill = document.createElement('div');
  pill.className = 'action-pill';
  pill.dataset.actionIndex = idx;

  const header = document.createElement('div');
  header.className = 'action-pill-header';

  header.innerHTML = `
    <i class="${icon}"></i>
    <div class="action-pill-label">${pillLabelHtml(pillData)}</div>
  `;

  const content = document.createElement('div');
  content.className = 'action-pill-content';
  content.innerHTML = formatPillContent(toolUse, toolResult);

  pill.appendChild(header);
  pill.appendChild(content);

  attachPillListeners(pill, idx);

  return pill;
}

/**
 * Attach event listeners to a pill
 */
function attachPillListeners(pill, idx) {
  const header = pill.querySelector('.action-pill-header');

  // Click to expand/collapse
  header.addEventListener('click', () => {
    pill.classList.toggle('expanded');
  });

  // Hover to highlight footnote
  pill.addEventListener('mouseenter', () => {
    highlightFootnote(idx, true);
  });
  pill.addEventListener('mouseleave', () => {
    highlightFootnote(idx, false);
  });
}

/**
 * Format the expanded content of a pill
 */
function formatPillContent(toolUse, toolResult) {
  let html = '';
  const category = toolUse.category || '';
  let hasKnowledgeLink = false;

  // Knowledge files: show link to open in connaissances section
  if (category === 'Read: knowledge' && toolUse.input?.file_path) {
    const fullPath = toolUse.input.file_path;
    const match = fullPath.match(/\/knowledge\/(.+)$/);
    if (match) {
      hasKnowledgeLink = true;
      const relativePath = match[1];
      const fileName = relativePath.split('/').pop();
      html += `<a href="/connaissances/${escapeHtml(relativePath)}" target="_blank" class="action-knowledge-link">
        <i class="ri-book-open-line"></i>
        <span>Ouvrir ${escapeHtml(fileName)}</span>
        <i class="ri-external-link-line"></i>
      </a>`;
    }
  }

  // API calls: show clickable links + SQL preview
  if (toolResult?.api_calls?.length > 0) {
    html += '<div class="action-api-links">';
    for (const call of toolResult.api_calls) {
      const linkText = call.method || (call.sql?.replace(/^[\s\\n]+/, '').substring(0, 50) + '...') || 'View';
      const icon = call.source === 'matomo' ? 'ri-bar-chart-line' : 'ri-database-2-line';
      html += `<a href="${escapeHtml(call.url)}" target="_blank" class="action-api-link">
        <i class="${icon}"></i>
        <span>${escapeHtml(linkText)}</span>
        <i class="ri-external-link-line"></i>
      </a>`;
      // Show SQL preview for Metabase queries
      if (call.sql) {
        const sqlClean = call.sql.replace(/^[\s\\n]+/, '');
        const sqlPreview = sqlClean.length > 200 ? sqlClean.substring(0, 200) + '...' : sqlClean;
        html += `<pre class="action-sql-preview">${escapeHtml(sqlPreview)}</pre>`;
        if (sqlClean.length > 200) {
          const expandIdx = registerExpandData('SQL', sqlClean, true);
          html += `<button class="action-expand-btn" data-expand-idx="${expandIdx}">
            <i class="ri-expand-diagonal-line"></i> Voir la requete complète
          </button>`;
        }
      }
    }
    html += '</div>';
  }

  // Show input as key-value pairs
  if (toolUse.input && typeof toolUse.input === 'object') {
    html += '<div class="action-kv-list">';
    // Sort keys with "description" first
    const entries = Object.entries(toolUse.input).sort(([a], [b]) => {
      if (a === 'description') return -1;
      if (b === 'description') return 1;
      return 0;
    });
    for (const [key, value] of entries) {
      // Skip file_path if we already show a knowledge link
      if (key === 'file_path' && hasKnowledgeLink) continue;

      const displayValue = typeof value === 'object'
        ? JSON.stringify(value)
        : String(value);
      const MAX_INLINE = 500;
      const needsTruncation = displayValue.length > MAX_INLINE;
      const truncated = needsTruncation
        ? displayValue.substring(0, MAX_INLINE) + '...'
        : displayValue;

      // Expand button before the value when truncated
      let expandBtnHtml = '';
      if (needsTruncation) {
        const isCode = key === 'command' || key === 'query' || key === 'content';
        const expandIdx = registerExpandData(key.toUpperCase(), displayValue, isCode);
        expandBtnHtml = `<button class="action-expand-btn" data-expand-idx="${expandIdx}">
          <i class="ri-expand-diagonal-line"></i> Voir tout
        </button>`;
      }

      // Description: no header, different styling
      if (key === 'description') {
        html += `<div class="action-description">${escapeHtml(truncated)}</div>`;
      } else {
        html += `<div class="action-kv">
          <div class="action-kv-key">${escapeHtml(key.toUpperCase())}${expandBtnHtml}</div>
          <div class="action-kv-value">${escapeHtml(truncated)}</div>
        </div>`;
      }
    }
    html += '</div>';
  } else if (toolUse.input) {
    // Fallback for non-object input
    html += `<div class="action-kv-list">
      <div class="action-kv">
        <div class="action-kv-key">INPUT</div>
        <div class="action-kv-value">${escapeHtml(String(toolUse.input))}</div>
      </div>
    </div>`;
  }

  return html || '<em>No details available</em>';
}

// =============================================================================
// Expand modal
// =============================================================================

/**
 * Register a value for the expand button and return its index
 */
function registerExpandData(title, value, isCode) {
  const idx = expandDataStore.length;
  expandDataStore.push({ title, value, isCode });
  return idx;
}

/**
 * Open the detail modal with full content
 */
function openActionModal(title, content, isCode) {
  const modal = document.getElementById('actionDetailModal');
  if (!modal) return;

  document.getElementById('actionDetailModalTitle').textContent = title;
  const body = document.getElementById('actionDetailModalBody');
  if (isCode) {
    body.innerHTML = `<pre class="action-modal-pre"><code>${escapeHtml(content)}</code></pre>`;
  } else {
    body.innerHTML = `<div class="action-modal-text">${escapeHtml(content)}</div>`;
  }
  new bootstrap.Modal(modal).show();
}

// Event delegation for expand buttons
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.action-expand-btn');
  if (!btn) return;
  const idx = parseInt(btn.dataset.expandIdx, 10);
  if (isNaN(idx) || !expandDataStore[idx]) return;
  const { title, value, isCode } = expandDataStore[idx];
  openActionModal(title, value, isCode);
});

// =============================================================================
// Footnotes & highlighting
// =============================================================================

/**
 * Create a single footnote icon element for an action
 */
function createFootnoteIcon(idx) {
  const action = actionsMap.get(idx);
  if (!action) return null;

  const footnote = document.createElement('span');
  footnote.className = 'action-footnote';
  footnote.dataset.actionIndex = idx;
  footnote.innerHTML = `<i class="${action.icon}"></i>`;
  footnote.title = action.pillData.label;
  footnote.addEventListener('click', () => scrollToPillAndExpand(idx));
  footnote.addEventListener('mouseenter', () => highlightPill(idx, true));
  footnote.addEventListener('mouseleave', () => highlightPill(idx, false));
  return footnote;
}

/**
 * Add footnotes to the last assistant block (batch, for loaded conversations)
 */
function addFootnotesToLastAssistant() {
  if (!lastAssistantBlock || currentTurnActions.length === 0) return;

  // Skip if footnotes were already added progressively during streaming
  if (lastAssistantBlock.querySelector('.action-footnotes')) {
    currentTurnActions = [];
    return;
  }

  const footnotes = document.createElement('div');
  footnotes.className = 'action-footnotes';

  for (const idx of currentTurnActions) {
    const footnote = createFootnoteIcon(idx);
    if (footnote) footnotes.appendChild(footnote);
  }

  lastAssistantBlock.appendChild(footnotes);
  currentTurnActions = [];
}

/**
 * Highlight a pill by index
 */
function highlightPill(idx, highlight) {
  const pills = document.querySelectorAll(`.action-pill[data-action-index="${idx}"]`);
  pills.forEach(pill => {
    pill.classList.toggle('highlighted', highlight);
  });
}

/**
 * Highlight a footnote by index
 */
function highlightFootnote(idx, highlight) {
  const footnotes = document.querySelectorAll(`.action-footnote[data-action-index="${idx}"]`);
  footnotes.forEach(fn => {
    fn.classList.toggle('highlighted', highlight);
  });
}

/**
 * Scroll to a pill and expand it
 */
function scrollToPillAndExpand(idx) {
  // Switch to Actions tab first
  switchSidebarTab('actions');

  // Check if pill is filtered out - switch to detailed mode
  const pill = document.querySelector(`#actionsContent .action-pill[data-action-index="${idx}"]`);
  if (pill && pill.classList.contains('filtered-out')) {
    switchToDetailedMode();
  }

  // On mobile, open offcanvas first
  const offcanvas = document.getElementById('actionsOffcanvas');
  if (offcanvas && window.innerWidth < 992) {
    const bsOffcanvas = bootstrap.Offcanvas.getOrCreateInstance(offcanvas);
    bsOffcanvas.show();

    // Wait for offcanvas to open, then scroll
    setTimeout(() => {
      const mobilePill = offcanvas.querySelector(`.action-pill[data-action-index="${idx}"]`);
      if (mobilePill) {
        mobilePill.scrollIntoView({ behavior: 'smooth', block: 'center' });
        mobilePill.classList.add('expanded');
      }
    }, 300);
  } else {
    // Desktop: scroll in sidebar
    if (pill) {
      pill.scrollIntoView({ behavior: 'smooth', block: 'center' });
      pill.classList.add('expanded');
    }
  }
}

// =============================================================================
// Progress indicator
// =============================================================================

/**
 * Update or create progress indicator for hidden tool activity
 */
function updateProgressIndicator() {
  const chatOutput = document.getElementById('chatOutput');
  if (!chatOutput) return;

  // Check scroll position BEFORE modifying DOM
  const wasAtBottom = isAtBottom();

  progressDots += '.';
  if (progressDots.length > 20) {
    progressDots = '.';
  }

  if (!progressIndicator) {
    progressIndicator = document.createElement('div');
    progressIndicator.className = 'progress-indicator';
    progressIndicator.id = 'progressIndicator';
    chatOutput.appendChild(progressIndicator);
  }

  progressIndicator.innerHTML = `<span class="dots">${progressDots}</span>`;

  // Only scroll if user was at bottom
  if (wasAtBottom) {
    scrollToBottom();
  }
}

/**
 * Remove progress indicator
 */
function removeProgressIndicator() {
  if (progressIndicator) {
    progressIndicator.remove();
    progressIndicator = null;
    progressDots = '';
  }
}

// =============================================================================
// Final answer marking
// =============================================================================

/**
 * Mark the last assistant message as a final answer
 * Called when streaming completes
 */
function markFinalAnswer() {
  // Add footnotes to the last assistant message
  addFootnotesToLastAssistant();

  const chatOutput = document.getElementById('chatOutput');
  if (!chatOutput) return;

  // Find the last assistant message (that's not already a report)
  const assistantMessages = chatOutput.querySelectorAll('.event-assistant:not(.event-report)');
  if (assistantMessages.length > 0) {
    const lastAssistant = assistantMessages[assistantMessages.length - 1];
    lastAssistant.classList.add('event-final-answer');
  }
}

/**
 * Mark final answers in a loaded conversation
 * Final answer = last assistant message before each user message, or the very last one
 */
function markFinalAnswersInConversation() {
  const chatOutput = document.getElementById('chatOutput');
  if (!chatOutput) return;

  const blocks = chatOutput.querySelectorAll('.event-block');
  let lastAssistant = null;

  blocks.forEach((block) => {
    if (block.classList.contains('event-assistant') && !block.classList.contains('event-report')) {
      lastAssistant = block;
    } else if (block.classList.contains('event-user') && lastAssistant) {
      // Mark the last assistant before this user message as final
      lastAssistant.classList.add('event-final-answer');
      lastAssistant = null;
    }
  });

  // Mark the very last assistant message if any
  if (lastAssistant) {
    lastAssistant.classList.add('event-final-answer');
  }
}

// =============================================================================
// Reset & misc
// =============================================================================

/**
 * Scroll the actions sidebar tab content to the bottom.
 */
function scrollActionsToBottom() {
  const actionsContent = document.getElementById('actionsContent');
  if (actionsContent) {
    actionsContent.scrollTop = actionsContent.scrollHeight;
  }
}

/**
 * Reset actions state for new conversation
 */
function resetActionsState() {
  actionIndex = 0;
  actionsMap.clear();
  pendingToolUses = [];
  lastAssistantBlock = null;
  currentTurnActions = [];
  streamingBlock = null;
  streamingText = '';

  // Reset TOC state
  resetTocState();

  // Clear sidebar content
  const actionsContent = document.getElementById('actionsContent');
  if (actionsContent) actionsContent.innerHTML = '';

  const offcanvasContent = document.getElementById('actionsOffcanvasContent');
  if (offcanvasContent) offcanvasContent.innerHTML = '';

  // Reset expand data store
  expandDataStore = [];

  // Re-sync tab visibility from localStorage (fixes desync after htmx swap)
  syncSidebarTabState();
}

// Hide public warning banner if previously dismissed - runs on every htmx load
document.body.addEventListener('htmx:afterSettle', () => {
  if (localStorage.getItem('publicWarningDismissed') === 'true') {
    const warning = document.getElementById('publicWarning');
    if (warning) warning.style.display = 'none';
  }
});
