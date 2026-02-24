/**
 * Matometa Chat Interface
 * Init, uploads, auth, htmx event wiring.
 * Depends on: utils.js, actions.js, render.js, stream.js
 */

// File upload state
let pendingFiles = [];  // Files waiting to be uploaded
const MAX_FILE_SIZE = 200 * 1024 * 1024;  // 200 MB

// Scroll position management for htmx navigation
let isPopState = false;

function parseConversationId(path) {
  const clean = path.split('?')[0].split('#')[0];
  const match = clean.match(/^\/explorations\/([^/]+)$/);
  return match && match[1] !== 'new' ? match[1] : null;
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

    // Update label (main/sub may swap based on filter mode)
    const label = extractPillLabel(action.toolUse, action.toolResult);
    const labelEl = pill.querySelector('.action-pill-label');
    if (labelEl) {
      const mainLabel = typeof label === 'object' ? label.main : label;
      const subLabel = typeof label === 'object' ? label.sub : null;
      let labelHtml = `<span class="action-pill-label-main">${escapeHtml(mainLabel)}</span>`;
      if (subLabel) {
        labelHtml += `<span class="action-pill-label-sub">${escapeHtml(subLabel)}</span>`;
      }
      labelEl.innerHTML = labelHtml;
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

  // Keep current tab compatible with the current page.
  // Exploration pages expose "toc/actions", expert pages expose "spec/actions".
  if (toggle) {
    const availableTabs = Array.from(toggle.querySelectorAll('.sidebar-tab-btn'))
      .map(btn => btn.dataset.tab)
      .filter(Boolean);

    if (availableTabs.length && !availableTabs.includes(currentSidebarTab)) {
      currentSidebarTab = availableTabs[0];
      localStorage.setItem('sidebarTab', currentSidebarTab);
    }
  }

  if (sidebar) sidebar.dataset.activeTab = currentSidebarTab;
  if (toggle) {
    toggle.querySelectorAll('.sidebar-tab-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.tab === currentSidebarTab);
    });
  }
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

/**
 * Extract a short label for a pill based on tool data
 * Returns { main: string, sub?: string } for potential two-line display
 */
function extractPillLabel(toolUse, toolResult) {
  const category = toolUse.category || '';
  let main = translateCategory(category) || toolUse.tool || 'Action';
  let sub = null;

  // For Read operations, show the filename
  if (category.startsWith('Read:') && toolUse.input?.file_path) {
    const path = toolUse.input.file_path;
    main = path.split('/').pop();
  }

  // For direct API calls, show the method
  if (category.startsWith('API:') && toolResult?.api_calls?.length > 0) {
    const call = toolResult.api_calls[0];
    if (call.method) main = call.method;
    else if (call.sql) main = 'Requête SQL';
  }

  // If there are API calls (from scripts, etc.), build the API count label
  if (toolResult?.api_calls?.length > 0 && !category.startsWith('API:')) {
    // Count calls by source
    const counts = {};
    for (const call of toolResult.api_calls) {
      const source = call.source || 'API';
      counts[source] = (counts[source] || 0) + 1;
    }
    // Format: "3 requêtes Matomo" or "16 requêtes Matomo, 2 requêtes Metabase"
    const parts = Object.entries(counts).map(([source, count]) => {
      const name = source.charAt(0).toUpperCase() + source.slice(1);
      return `${count} requête${count > 1 ? 's' : ''} ${name}`;
    });
    const apiLabel = parts.join(', ');

    // In data mode: API count is main, category is sub
    // In detailed mode: category is main, API count is sub
    if (actionsFilterMode === 'data') {
      sub = main;
      main = apiLabel;
    } else {
      sub = apiLabel;
    }
  }

  return { main, sub };
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

// Save scroll position before htmx request
document.body.addEventListener('htmx:beforeRequest', (e) => {
  if (e.detail.target.id === 'main' && !isPopState) {
    const state = { scrollY: window.scrollY, ...history.state };
    history.replaceState(state, '');
  }
});

// htmx navigation handler
// Use afterSettle (not afterSwap) — URL is already pushed at this point.
document.body.addEventListener('htmx:afterSettle', (e) => {
  if (e.detail.target.id !== 'main') return;

  const path = window.location.pathname;
  const convId = parseConversationId(path);

  closeEventSource();
  currentConversationId = convId;

  initChat();
  initKnowledge();

  if (convId) {
    loadConversation(convId);
  } else if (!isPopState) {
    window.scrollTo(0, 0);
    if (path === '/explorations/new') {
      document.getElementById('chatInput')?.focus();
    }
  }

  isPopState = false;
});

// Restore scroll position on back/forward
window.addEventListener('popstate', (e) => {
  isPopState = true;
  if (e.state && typeof e.state.scrollY === 'number') {
    // Delay to let htmx finish swapping content
    setTimeout(() => {
      window.scrollTo(0, e.state.scrollY);
    }, 50);
  }
});

// =============================================================================
// Init functions
// =============================================================================

/**
 * Initialize knowledge page markdown rendering
 */
async function initKnowledge() {
  const markdownContent = document.getElementById('markdownContent');
  const rawContentScript = document.getElementById('knowledgeRawContent');

  if (!markdownContent || !rawContentScript) return;

  // Render markdown
  if (typeof marked !== 'undefined') {
    marked.setOptions({
      breaks: true,
      gfm: true,
    });

    const rawContent = rawContentScript.textContent;
    markdownContent.innerHTML = marked.parse(rawContent);

    // Render mermaid diagrams if present
    if (typeof mermaid !== 'undefined') {
      const mermaidBlocks = markdownContent.querySelectorAll('pre code.language-mermaid');
      for (const block of mermaidBlocks) {
        const container = document.createElement('div');
        container.className = 'mermaid';
        container.textContent = block.textContent;
        block.parentElement.replaceWith(container);
      }
      try {
        await mermaid.run();
      } catch (e) {
        console.warn('Mermaid rendering failed:', e);
      }
    }
  }
}

/**
 * Initialize the chat interface
 */
function initChat() {
  // Fork button and sidebar work on all conversation pages (including readonly)
  initForkButton();
  initActionsSidebar();

  const input = document.getElementById('chatInput');
  const sendBtn = document.getElementById('chatSendBtn');
  const cancelBtn = document.getElementById('chatCancelBtn');

  if (!input || !sendBtn) return;

  // Skip on knowledge pages - they have their own chat handling
  if (document.getElementById('knowledgeContent')) return;

  // Check for conversation ID in URL (skip if already loaded by inline script)
  const urlParams = new URLSearchParams(window.location.search);
  const convId = urlParams.get('conv');
  if (convId && !currentConversationId) {
    currentConversationId = convId;
    loadConversation(convId);
  }

  // Auto-grow textarea
  input.addEventListener('input', () => autoGrow(input));

  // Send on button click
  sendBtn.addEventListener('click', () => sendMessage());

  // Send on Enter (Shift+Enter for newline)
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Cancel button
  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => cancelStream());
  }

  // File upload handling
  initFileUpload();

  // Title editing
  initTitleEditing();
}

/**
 * Initialize actions sidebar toggle and interactions
 */
function initActionsSidebar() {
  const sidebarToggle = document.getElementById('sidebarToggle');
  const chatWithSidebar = document.getElementById('chatWithSidebar');

  if (sidebarToggle && chatWithSidebar) {
    // Remove existing listener to prevent duplicates
    sidebarToggle.replaceWith(sidebarToggle.cloneNode(true));
    const newToggle = document.getElementById('sidebarToggle');

    newToggle.addEventListener('click', () => {
      chatWithSidebar.classList.toggle('sidebar-collapsed');
    });
  }

  // Initialize tab toggle (TOC / Actions)
  initSidebarTabToggle();

  // Initialize filter toggle (data/detailed)
  initActionsFilterToggle();
}

/**
 * Initialize fork button functionality
 */
function initForkButton() {
  const forkBtn = document.getElementById('forkConvBtn');
  if (!forkBtn) return;

  // Remove existing listener to prevent duplicates
  forkBtn.replaceWith(forkBtn.cloneNode(true));
  const newForkBtn = document.getElementById('forkConvBtn');

  newForkBtn.addEventListener('click', async () => {
    if (!currentConversationId) return;

    newForkBtn.disabled = true;
    newForkBtn.innerHTML = '<i class="ri-loader-4-line ri-spin"></i>';

    try {
      const resp = await fetch(`/api/conversations/${currentConversationId}/fork`, { method: 'POST' });
      if (resp.ok) {
        const data = await resp.json();
        window.location.href = data.links.view;
      } else {
        const err = await resp.json();
        alert('Erreur: ' + (err.error || 'Impossible de dupliquer'));
        newForkBtn.disabled = false;
        newForkBtn.innerHTML = '<i class="ri-git-branch-line"></i> <span>Dupliquer</span>';
      }
    } catch (e) {
      alert('Erreur réseau');
      newForkBtn.disabled = false;
      newForkBtn.innerHTML = '<i class="ri-git-branch-line"></i> <span>Dupliquer</span>';
    }
  });
}

/**
 * Initialize title editing functionality
 */
function initTitleEditing() {
  const editBtn = document.getElementById('editTitleBtn');
  const autoBtn = document.getElementById('autoTitleBtn');
  const titleDisplay = document.getElementById('convTitleDisplay');
  const titleEdit = document.getElementById('convTitleEdit');
  const titleInput = document.getElementById('convTitleInput');
  const saveBtn = document.getElementById('saveTitleBtn');
  const cancelBtn = document.getElementById('cancelTitleBtn');

  if (!editBtn || !titleDisplay || !titleEdit) return;

  // Show edit form
  editBtn.addEventListener('click', () => {
    titleDisplay.classList.add('d-none');
    titleEdit.classList.remove('d-none');
    editBtn.classList.add('d-none');
    if (autoBtn) autoBtn.classList.remove('d-none');
    titleInput.focus();
    titleInput.select();
  });

  // Cancel editing
  cancelBtn.addEventListener('click', () => {
    titleEdit.classList.add('d-none');
    titleDisplay.classList.remove('d-none');
    editBtn.classList.remove('d-none');
    if (autoBtn) autoBtn.classList.add('d-none');
  });

  // Save title
  saveBtn.addEventListener('click', () => saveTitle());
  titleInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      saveTitle();
    } else if (e.key === 'Escape') {
      cancelBtn.click();
    }
  });

  async function saveTitle() {
    const newTitle = titleInput.value.trim();
    if (!newTitle || !currentConversationId) return;

    try {
      const response = await fetch(`/api/conversations/${currentConversationId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle })
      });

      if (response.ok) {
        // Update displayed title
        const h1 = titleDisplay.querySelector('h1');
        if (h1) h1.textContent = newTitle;
        titleEdit.classList.add('d-none');
        titleDisplay.classList.remove('d-none');
        editBtn.classList.remove('d-none');
        if (autoBtn) autoBtn.classList.add('d-none');
      }
    } catch (error) {
      console.error('Failed to save title:', error);
    }
  }

  // Auto-generate title
  if (autoBtn) {
    autoBtn.addEventListener('click', async () => {
      if (!currentConversationId) return;

      autoBtn.disabled = true;
      autoBtn.innerHTML = '<i class="ri-loader-4-line ri-spin"></i>';

      try {
        const response = await fetch(`/api/conversations/${currentConversationId}/generate-title`, {
          method: 'POST'
        });

        if (response.ok) {
          const data = await response.json();
          const h1 = titleDisplay.querySelector('h1');
          if (h1) h1.textContent = data.title;
          titleInput.value = data.title;
        }
      } catch (error) {
        console.error('Failed to generate title:', error);
      } finally {
        autoBtn.disabled = false;
        autoBtn.innerHTML = '<i class="ri-magic-line"></i>';
      }
    });
  }
}

// =============================================================================
// File upload
// =============================================================================

/**
 * Initialize file upload functionality
 */
function initFileUpload() {
  const uploadBtn = document.getElementById('chatUploadBtn');
  const fileInput = document.getElementById('chatFileInput');

  if (!uploadBtn || !fileInput) return;

  // Remove existing listeners by cloning
  uploadBtn.replaceWith(uploadBtn.cloneNode(true));
  const newUploadBtn = document.getElementById('chatUploadBtn');

  // Click upload button to trigger file input
  newUploadBtn.addEventListener('click', () => {
    fileInput.click();
  });

  // Handle file selection
  fileInput.addEventListener('change', (e) => {
    const files = Array.from(e.target.files);
    addPendingFiles(files);
    fileInput.value = '';  // Reset so same file can be selected again
  });

  // Allow drag and drop on the chat input area
  const chatBar = document.querySelector('.chat-bar');
  if (chatBar) {
    chatBar.addEventListener('dragover', (e) => {
      e.preventDefault();
      chatBar.classList.add('drag-over');
    });

    chatBar.addEventListener('dragleave', (e) => {
      e.preventDefault();
      chatBar.classList.remove('drag-over');
    });

    chatBar.addEventListener('drop', (e) => {
      e.preventDefault();
      chatBar.classList.remove('drag-over');
      const files = Array.from(e.dataTransfer.files);
      addPendingFiles(files);
    });
  }
}

/**
 * Add files to the pending upload queue
 */
function addPendingFiles(files) {
  for (const file of files) {
    // Check file size
    if (file.size > MAX_FILE_SIZE) {
      showError(`Fichier trop volumineux: ${file.name} (max 200 Mo)`);
      continue;
    }

    // Check for duplicates
    if (pendingFiles.some(f => f.name === file.name && f.size === file.size)) {
      continue;
    }

    pendingFiles.push(file);
  }

  updatePendingFilesUI();
}

/**
 * Remove a file from the pending queue
 */
function removePendingFile(index) {
  pendingFiles.splice(index, 1);
  updatePendingFilesUI();
}

/**
 * Update the UI to show pending files
 */
function updatePendingFilesUI() {
  const container = document.getElementById('chatPendingFiles');
  const input = document.getElementById('chatInput');
  if (!container) return;

  if (pendingFiles.length === 0) {
    container.innerHTML = '';
    container.style.display = 'none';
    return;
  }

  container.style.display = 'flex';
  container.innerHTML = pendingFiles.map((file, index) => `
    <div class="pending-file" data-index="${index}">
      <i class="ri-file-line"></i>
      <span class="pending-file-name" title="${escapeHtml(file.name)}">${escapeHtml(truncateFilename(file.name))}</span>
      <span class="pending-file-size">(${formatFileSize(file.size)})</span>
      <button type="button" class="pending-file-remove" onclick="removePendingFile(${index})" title="Supprimer">
        <i class="ri-close-line"></i>
      </button>
    </div>
  `).join('');
}

/**
 * Upload pending files to the conversation
 * Returns array of context messages for the uploaded files
 */
async function uploadPendingFiles() {
  if (pendingFiles.length === 0) return [];
  if (!currentConversationId) return [];

  const contextMessages = [];

  for (const file of pendingFiles) {
    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`/api/conversations/${currentConversationId}/files`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const err = await response.json();
        showError(`Erreur upload ${file.name}: ${err.error || 'Échec'}`);
        continue;
      }

      const data = await response.json();
      contextMessages.push(data.context_message);

    } catch (error) {
      console.error(`Failed to upload ${file.name}:`, error);
      showError(`Erreur upload ${file.name}`);
    }
  }

  // Clear pending files
  pendingFiles = [];
  updatePendingFilesUI();

  return contextMessages;
}

/**
 * Clear pending files (used when navigating away)
 */
function clearPendingFiles() {
  pendingFiles = [];
  updatePendingFilesUI();
}

// =============================================================================
// Auth Management
// =============================================================================

let authModal = null;
let isAuthenticated = false;

/**
 * Check authentication status on page load
 * Only shows auth banner when using CLI backend (not SDK/API)
 */
async function checkAuthStatus() {
  try {
    const resp = await fetch('/api/auth/status');
    const data = await resp.json();
    isAuthenticated = data.authenticated;

    const banner = document.getElementById('authBanner');
    if (banner) {
      // Only show banner if auth is required (CLI backend) AND not authenticated
      const showBanner = data.auth_required && !data.authenticated;
      banner.classList.toggle('d-none', !showBanner);
    }

    return isAuthenticated;
  } catch (e) {
    console.error('Failed to check auth status:', e);
    return false;
  }
}

/**
 * Show auth modal
 */
function showAuthModal() {
  // Reset modal to step 1
  document.getElementById('authStep1').classList.remove('d-none');
  document.getElementById('authStep2').classList.add('d-none');
  document.getElementById('authStep3').classList.add('d-none');
  document.getElementById('authStep4').classList.add('d-none');
  document.getElementById('authError').classList.add('d-none');
  document.getElementById('authCodeInput').value = '';

  // Show modal
  if (!authModal) {
    authModal = new bootstrap.Modal(document.getElementById('authModal'));
  }
  authModal.show();
}

/**
 * Start authentication flow
 */
async function startAuth() {
  const step1 = document.getElementById('authStep1');
  const step2 = document.getElementById('authStep2');
  const step3 = document.getElementById('authStep3');
  const loadingText = document.getElementById('authLoadingText');

  // Show loading
  step1.classList.add('d-none');
  step3.classList.remove('d-none');
  loadingText.textContent = 'Démarrage de l\'authentification...';

  try {
    const resp = await fetch('/api/auth/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true })
    });
    const data = await resp.json();

    if (data.status === 'waiting_for_code' && data.oauth_url) {
      // Show step 2 with OAuth URL
      step3.classList.add('d-none');
      step2.classList.remove('d-none');
      document.getElementById('authOauthUrl').href = data.oauth_url;
    } else if (data.status === 'already_authenticated') {
      // Already authenticated
      isAuthenticated = true;
      document.getElementById('authBanner').classList.add('d-none');
      step3.classList.add('d-none');
      document.getElementById('authStep4').classList.remove('d-none');
      setTimeout(() => authModal.hide(), 1500);
    } else {
      // Error
      step3.classList.add('d-none');
      step1.classList.remove('d-none');
      alert('Erreur: ' + (data.error || 'Impossible de démarrer l\'authentification'));
    }
  } catch (e) {
    step3.classList.add('d-none');
    step1.classList.remove('d-none');
    alert('Erreur réseau: ' + e.message);
  }
}

/**
 * Complete authentication with code
 */
async function completeAuth() {
  const code = document.getElementById('authCodeInput').value.trim();
  if (!code) {
    document.getElementById('authError').textContent = 'Veuillez entrer le code';
    document.getElementById('authError').classList.remove('d-none');
    return;
  }

  const step2 = document.getElementById('authStep2');
  const step3 = document.getElementById('authStep3');
  const step4 = document.getElementById('authStep4');
  const loadingText = document.getElementById('authLoadingText');
  const errorDiv = document.getElementById('authError');

  // Show loading
  step2.classList.add('d-none');
  step3.classList.remove('d-none');
  loadingText.textContent = 'Validation du code...';
  errorDiv.classList.add('d-none');

  try {
    const resp = await fetch('/api/auth/complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code })
    });
    const data = await resp.json();

    if (data.status === 'done') {
      // Success
      isAuthenticated = true;
      document.getElementById('authBanner').classList.add('d-none');
      step3.classList.add('d-none');
      step4.classList.remove('d-none');
      setTimeout(() => authModal.hide(), 1500);
    } else {
      // Error - go back to step 2
      step3.classList.add('d-none');
      step2.classList.remove('d-none');
      errorDiv.textContent = data.error || 'Code invalide';
      errorDiv.classList.remove('d-none');
    }
  } catch (e) {
    step3.classList.add('d-none');
    step2.classList.remove('d-none');
    errorDiv.textContent = 'Erreur réseau: ' + e.message;
    errorDiv.classList.remove('d-none');
  }
}

// Check auth status on page load
document.addEventListener('DOMContentLoaded', checkAuthStatus);
// Also check after htmx navigations
document.body.addEventListener('htmx:afterSettle', checkAuthStatus);
