/**
 * Matometa Chat Interface
 * Handles conversation creation, SSE streaming, and UI updates
 */

let currentConversationId = null;
let eventSource = null;
let eventSourceConversationId = null;  // Track which conversation the eventSource belongs to
let progressIndicator = null;
let progressDots = '';
let retryCount = 0;
let lastUserMessage = null;
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

// File upload state
let pendingFiles = [];  // Files waiting to be uploaded
const MAX_FILE_SIZE = 200 * 1024 * 1024;  // 200 MB

// Scroll position management for htmx navigation
let isPopState = false;

// Actions sidebar state
let actionIndex = 0;
let actionsMap = new Map(); // actionIndex -> {toolUse, toolResult, category, icon}
let pendingToolUses = []; // Queue for tool_use waiting for their results (supports parallel calls)
let lastAssistantBlock = null; // Track last assistant block for footnotes
let currentTurnActions = []; // Actions in current turn (for footnotes)
let actionsFilterMode = 'data'; // 'data' or 'detailed'

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
    applyActionsFilter();
  });
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

  // Clear sidebar content
  const actionsContent = document.getElementById('actionsContent');
  if (actionsContent) actionsContent.innerHTML = '';

  const offcanvasContent = document.getElementById('actionsOffcanvasContent');
  if (offcanvasContent) offcanvasContent.innerHTML = '';

  updateActionCountBadge();
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
    // Save current scroll position in history state
    const state = { scrollY: window.scrollY, ...history.state };
    history.replaceState(state, '');
  }
});

// htmx integration - only add listener once
document.body.addEventListener('htmx:afterSwap', (e) => {
  if (e.detail.target.id === 'main') {
    const path = window.location.pathname;
    const convMatch = path.match(/^\/explorations\/([a-f0-9-]+)$/);
    const previousConvId = currentConversationId;

    // Close EventSource when navigating away from a conversation
    if (previousConvId && (!convMatch || convMatch[1] !== previousConvId)) {
      closeEventSource();
    }

    // Set currentConversationId BEFORE initChat (needed for fork button)
    if (convMatch) {
      currentConversationId = convMatch[1];
    } else if (path === '/explorations' || path === '/explorations/new') {
      currentConversationId = null;
    }

    initChat();
    initKnowledge();

    // Load conversation if navigated to a different one
    if (convMatch && convMatch[1] !== previousConvId) {
      // Don't scroll to top yet - loadConversation will handle scroll for running convs
      loadConversation(convMatch[1]).then(() => {
        // Only scroll to top for non-running conversations
        // (running convs are scrolled to bottom in loadConversation)
      });
    } else {
      // Scroll to top on new navigation, unless it's a back/forward
      if (!isPopState) {
        window.scrollTo(0, 0);
      }
      if (path === '/explorations/new') {
        const input = document.getElementById('chatInput');
        if (input) input.focus();
      }
    }
    isPopState = false;
  }
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
  // Fork button works on all conversation pages (including readonly)
  initForkButton();

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

  // Actions sidebar toggle
  initActionsSidebar();

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
    if (input) input.classList.remove('has-pending-files');
    return;
  }

  container.style.display = 'flex';
  if (input) input.classList.add('has-pending-files');
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
 * Truncate a filename for display
 */
function truncateFilename(name, maxLen = 25) {
  if (name.length <= maxLen) return name;
  const ext = name.includes('.') ? '.' + name.split('.').pop() : '';
  const stem = name.slice(0, name.length - ext.length);
  const truncated = stem.slice(0, maxLen - ext.length - 3) + '...';
  return truncated + ext;
}

/**
 * Format file size for display
 */
function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' o';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' Ko';
  return (bytes / (1024 * 1024)).toFixed(1) + ' Mo';
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

/**
 * Auto-grow textarea to fit content
 */
function autoGrow(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
}

/**
 * Send a message to the agent
 */
async function sendMessage() {
  const input = document.getElementById('chatInput');
  const message = input.value.trim();
  const hasFiles = pendingFiles.length > 0;

  if (!message && !hasFiles) {
    input.focus();
    return;
  }

  // Create conversation if needed
  if (!currentConversationId) {
    try {
      const response = await fetch('/api/conversations', { method: 'POST' });
      const data = await response.json();
      currentConversationId = data.id;

      // If we have pending files, we need to upload them first, then redirect
      if (hasFiles) {
        // Upload files to the new conversation
        const fileContexts = await uploadPendingFiles();
        const fullMessage = buildMessageWithFiles(message, fileContexts);

        // Redirect with the full message
        window.location.href = `/explorations/${currentConversationId}?message=${encodeURIComponent(fullMessage)}`;
      } else {
        // Redirect to conversation page (refreshes sidebar with new conversation)
        window.location.href = `/explorations/${currentConversationId}?message=${encodeURIComponent(message)}`;
      }
      return;
    } catch (error) {
      console.error('Failed to create conversation:', error);
      showError('Impossible de créer la conversation');
      return;
    }
  }

  // Clear input
  input.value = '';
  autoGrow(input);

  // Hide empty state
  hideEmptyState();

  // Upload pending files first (if any)
  let fullMessage = message;
  if (hasFiles) {
    setStreamingState(true);  // Show loading during upload
    const fileContexts = await uploadPendingFiles();
    fullMessage = buildMessageWithFiles(message, fileContexts);
    setStreamingState(false);
  }

  // Show user message (with file info if any)
  appendEvent('user', { content: fullMessage });

  // Save message for potential retry
  lastUserMessage = fullMessage;
  retryCount = 0;

  // Send message to API
  await sendToAgent(fullMessage);
}

/**
 * Build the message content with file context prepended
 */
function buildMessageWithFiles(userMessage, fileContexts) {
  if (!fileContexts || fileContexts.length === 0) {
    return userMessage;
  }

  const fileSection = fileContexts.join('\n\n');
  if (!userMessage) {
    return fileSection;
  }

  return `${fileSection}\n\n---\n\n${userMessage}`;
}

/**
 * Send message to agent API and start streaming
 */
async function sendToAgent(message) {
  try {
    const response = await fetch(`/api/conversations/${currentConversationId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: message }),
    });

    const data = await response.json();

    if (!response.ok) {
      // If conversation not found, try to recover
      if (response.status === 404) {
        await recoverConversation(message);
        return;
      }
      showError(data.error || 'Erreur lors de l\'envoi');
      return;
    }

    // Start streaming
    startStream();

  } catch (error) {
    console.error('Failed to send message:', error);
    showError('Erreur de connexion');
  }
}

/**
 * Close any existing EventSource connection
 */
function closeEventSource() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
    eventSourceConversationId = null;
  }
}

/**
 * Start SSE streaming for the current conversation
 */
function startStream() {
  if (!currentConversationId) return;

  // Close any existing connection first
  closeEventSource();

  setStreamingState(true);

  // Show loading indicator
  showLoading();

  // Connect to SSE endpoint
  eventSource = new EventSource(`/api/conversations/${currentConversationId}/stream`);
  eventSourceConversationId = currentConversationId;

  // Handle different event types
  const eventTypes = ['assistant', 'tool_use', 'tool_result', 'system', 'error'];
  eventTypes.forEach(type => {
    eventSource.addEventListener(type, (e) => {
      const data = JSON.parse(e.data);
      appendEvent(type, data);

      // Only hide loading when we get actual content (assistant response or error)
      if (type === 'assistant' || type === 'error') {
        hideLoading();
      }
    });
  });

  // Handle completion
  eventSource.addEventListener('done', async () => {
    eventSource.close();
    eventSource = null;
    eventSourceConversationId = null;
    setStreamingState(false);
    hideLoading();
    removeProgressIndicator();
    markFinalAnswer();
  });

  // Handle errors
  eventSource.onerror = async (e) => {
    console.error('SSE error:', e);
    eventSource.close();
    eventSource = null;
    eventSourceConversationId = null;

    // Try to retry if we haven't exceeded max retries
    if (retryCount < MAX_RETRIES && lastUserMessage) {
      retryCount++;
      console.log(`Retrying (${retryCount}/${MAX_RETRIES})...`);

      // Wait before retrying (exponential backoff)
      await new Promise(resolve => setTimeout(resolve, RETRY_DELAY_MS * retryCount));

      // Check if conversation still exists, recover if not
      try {
        const checkResponse = await fetch(`/api/conversations/${currentConversationId}`);
        if (checkResponse.status === 404) {
          console.log('Conversation lost, recovering...');
          await recoverConversation(lastUserMessage);
          return;
        }
      } catch (err) {
        console.error('Failed to check conversation:', err);
      }

      // Conversation exists, just retry the stream
      startStream();
      return;
    }

    // Max retries exceeded or no message to retry
    setStreamingState(false);
    hideLoading();
    removeProgressIndicator();

    // Show error with recovery option
    appendRecoveryMessage();
  };
}

/**
 * Show a recovery message with option to restart
 */
function appendRecoveryMessage() {
  const chatOutput = document.getElementById('chatOutput');
  if (!chatOutput) return;

  const block = document.createElement('div');
  block.className = 'event-block event-error';
  block.innerHTML = `
    <div>Connexion interrompue.</div>
    <button class="btn btn-sm btn-outline-primary mt-2" onclick="retryLastMessage()">
      Réessayer
    </button>
    <button class="btn btn-sm btn-outline-secondary mt-2 ms-2" onclick="startNewConversation()">
      Nouvelle conversation
    </button>
  `;

  chatOutput.appendChild(block);
  scrollToBottom();
}

/**
 * Retry the last message
 */
async function retryLastMessage() {
  if (!lastUserMessage) {
    showError('Pas de message à réessayer');
    return;
  }

  // Remove the recovery message
  const chatOutput = document.getElementById('chatOutput');
  const lastBlock = chatOutput.lastElementChild;
  if (lastBlock && lastBlock.classList.contains('event-error')) {
    lastBlock.remove();
  }

  retryCount = 0;
  setStreamingState(true);
  showLoading();

  // Try with existing conversation first, recover if needed
  await sendToAgent(lastUserMessage);
}

/**
 * Start a completely new conversation
 */
async function startNewConversation() {
  // Remove the recovery message
  const chatOutput = document.getElementById('chatOutput');
  const lastBlock = chatOutput.lastElementChild;
  if (lastBlock && lastBlock.classList.contains('event-error')) {
    lastBlock.remove();
  }

  // Reset state
  currentConversationId = null;
  retryCount = 0;

  // Create new conversation
  try {
    const response = await fetch('/api/conversations', { method: 'POST' });
    const data = await response.json();
    currentConversationId = data.id;

    // Re-send the last message
    if (lastUserMessage) {
      setStreamingState(true);
      showLoading();
      await sendToAgent(lastUserMessage);
    }
  } catch (error) {
    console.error('Failed to create conversation:', error);
    showError('Impossible de créer une nouvelle conversation');
  }
}

/**
 * Recover from a lost conversation by creating a new one
 */
async function recoverConversation(message) {
  console.log('Conversation not found, creating new one...');

  // Reset conversation
  currentConversationId = null;

  try {
    const response = await fetch('/api/conversations', { method: 'POST' });
    const data = await response.json();
    currentConversationId = data.id;

    // Re-send the message
    await sendToAgent(message);
  } catch (error) {
    console.error('Failed to recover conversation:', error);
    setStreamingState(false);
    hideLoading();
    showError('Impossible de reprendre la conversation');
  }
}

/**
 * Cancel the current stream
 */
async function cancelStream() {
  if (!currentConversationId) return;

  try {
    await fetch(`/api/conversations/${currentConversationId}/cancel`, { method: 'POST' });
  } catch (error) {
    console.error('Failed to cancel:', error);
  }

  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }

  setStreamingState(false);
  hideLoading();
  removeProgressIndicator();
  appendEvent('error', { content: 'Annulé par l\'utilisateur' });
}

/**
 * Kill an agent from list/notification views
 * @param {string} convId - Conversation ID to kill
 * @param {HTMLElement|null} alertElement - Alert container to remove (for background notification)
 * @param {HTMLElement|null} cardElement - Card element to update (for conversation card)
 */
async function killAgent(convId, alertElement, cardElement) {
  try {
    const response = await fetch(`/api/conversations/${convId}/cancel`, { method: 'POST' });
    const data = await response.json();

    if (response.ok) {
      // Remove the background alert if provided
      if (alertElement) {
        alertElement.remove();
      }

      // Update the card if provided - remove running badge and kill button
      if (cardElement) {
        const runningBadge = cardElement.querySelector('.running-badge');
        const killBtn = cardElement.querySelector('.kill-agent-btn');
        if (runningBadge) runningBadge.remove();
        if (killBtn) killBtn.remove();
      }
    }
  } catch (error) {
    console.error('Failed to kill agent:', error);
  }
}

/**
 * Update token display with new usage data
 */
function updateTokenDisplay(usage) {
  const tokenDisplay = document.getElementById('tokenDisplay');
  const tokenCount = document.getElementById('tokenCount');
  if (!tokenDisplay || !tokenCount) return;

  // Get current values from data attributes
  let currentInput = parseInt(tokenDisplay.dataset.input) || 0;
  let currentOutput = parseInt(tokenDisplay.dataset.output) || 0;

  // Add new usage
  const newInput = usage.input_tokens || 0;
  const newOutput = usage.output_tokens || 0;
  currentInput += newInput;
  currentOutput += newOutput;

  // Update data attributes
  tokenDisplay.dataset.input = currentInput;
  tokenDisplay.dataset.output = currentOutput;

  // Update display
  const total = currentInput + currentOutput;
  tokenCount.textContent = total.toLocaleString();
  tokenDisplay.title = `Tokens utilisés: ${currentInput.toLocaleString()} entrée, ${currentOutput.toLocaleString()} sortie`;

  // Show if hidden
  tokenDisplay.classList.remove('d-none');
}

/**
 * Append an event to the chat output
 */
function appendEvent(type, data) {
  const chatOutput = document.getElementById('chatOutput');
  if (!chatOutput) return;

  // System events: check for usage data, then skip display
  if (type === 'system') {
    if (data.raw && data.raw.usage) {
      updateTokenDisplay(data.raw.usage);
    }
    return;
  }

  // Tool events: add to sidebar instead of main chat
  if (type === 'tool_use') {
    // Queue tool_use - supports parallel tool calls
    pendingToolUses.push(data.content);
    return;
  }

  if (type === 'tool_result') {
    if (pendingToolUses.length > 0) {
      // Pair with first queued tool_use (FIFO order)
      const toolUse = pendingToolUses.shift();
      const toolResult = data.content;
      createAndAppendAction(toolUse, toolResult);
    }
    return;
  }

  // When user speaks, add footnotes to previous assistant message and reset turn
  if (type === 'user') {
    addFootnotesToLastAssistant();
    currentTurnActions = [];
    lastAssistantBlock = null;
  }

  // When assistant speaks, track the block for footnotes
  if (type === 'assistant') {
    // Add footnotes to previous assistant block if any
    addFootnotesToLastAssistant();
  }

  const block = document.createElement('div');
  block.className = `event-block event-${type}`;

  if (type === 'user') {
    block.innerHTML = formatUserContent(data.content);
  } else if (type === 'assistant') {
    // Store raw markdown for report creation
    block.dataset.rawContent = data.content;
    // Check if this is a report (has YAML front-matter)
    const reportInfo = detectReport(data.content);
    if (reportInfo) {
      block.classList.add('event-report');
      block.innerHTML = formatReport(data.content, reportInfo);
    } else {
      block.innerHTML = formatAssistantContent(data.content);
    }
    // Track for footnotes
    lastAssistantBlock = block;
    // Render mermaid diagrams and options after adding to DOM
    setTimeout(() => {
      renderMermaid(block);
      renderOptions(block);
    }, 0);
  } else if (type === 'error') {
    block.innerHTML = escapeHtml(data.content || '');
  } else if (type === 'report') {
    // Report card - parse JSON content
    let reportData = data.content;
    if (typeof reportData === 'string') {
      try { reportData = JSON.parse(reportData); } catch { }
    }
    block.innerHTML = formatReportCard(reportData);
  }

  chatOutput.appendChild(block);
  scrollToBottom();
}

/**
 * Create an action pill and append to sidebar
 */
function createAndAppendAction(toolUse, toolResult) {
  actionIndex++;
  const idx = actionIndex;
  const category = toolUse.category || `Other: ${toolUse.tool}`;
  const icon = getIconForCategory(category);
  const label = extractPillLabel(toolUse, toolResult);

  // Store in map
  actionsMap.set(idx, { toolUse, toolResult, category, icon, label });
  currentTurnActions.push(idx);

  // Create pill element
  const pill = createActionPill(idx, icon, label, toolUse, toolResult);

  // Apply filter
  const isData = isDataAction(toolUse, toolResult);
  if (actionsFilterMode === 'data' && !isData) {
    pill.classList.add('filtered-out');
  }

  // Append to sidebar
  const actionsContent = document.getElementById('actionsContent');
  if (actionsContent) {
    actionsContent.appendChild(pill);
  }

  // Also append to mobile offcanvas
  const offcanvasContent = document.getElementById('actionsOffcanvasContent');
  if (offcanvasContent) {
    offcanvasContent.appendChild(pill.cloneNode(true));
    // Re-attach event listeners to cloned element
    const clonedPill = offcanvasContent.lastElementChild;
    attachPillListeners(clonedPill, idx);
  }

  updateActionCountBadge();
}

/**
 * Create a pill element for an action
 */
function createActionPill(idx, icon, label, toolUse, toolResult) {
  const pill = document.createElement('div');
  pill.className = 'action-pill';
  pill.dataset.actionIndex = idx;

  const header = document.createElement('div');
  header.className = 'action-pill-header';

  // Handle { main, sub } label format
  const mainLabel = typeof label === 'object' ? label.main : label;
  const subLabel = typeof label === 'object' ? label.sub : null;

  let labelHtml = `<span class="action-pill-label-main">${escapeHtml(mainLabel)}</span>`;
  if (subLabel) {
    labelHtml += `<span class="action-pill-label-sub">${escapeHtml(subLabel)}</span>`;
  }

  header.innerHTML = `
    <i class="${icon}"></i>
    <div class="action-pill-label">${labelHtml}</div>
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

  // API calls: show clickable links (regardless of category - scripts can make API calls)
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
      const truncated = displayValue.length > 500
        ? displayValue.substring(0, 500) + '...'
        : displayValue;

      // Description: no header, different styling
      if (key === 'description') {
        html += `<div class="action-description">${escapeHtml(truncated)}</div>`;
      } else {
        html += `<div class="action-kv">
          <div class="action-kv-key">${escapeHtml(key.toUpperCase())}</div>
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

/**
 * Add footnotes to the last assistant block
 */
function addFootnotesToLastAssistant() {
  if (!lastAssistantBlock || currentTurnActions.length === 0) return;

  const footnotes = document.createElement('div');
  footnotes.className = 'action-footnotes';

  for (const idx of currentTurnActions) {
    const action = actionsMap.get(idx);
    if (!action) continue;

    const footnote = document.createElement('span');
    footnote.className = 'action-footnote';
    footnote.dataset.actionIndex = idx;
    footnote.innerHTML = `<i class="${action.icon}"></i>`;
    footnote.title = action.label;

    // Click to scroll to pill and expand
    footnote.addEventListener('click', () => {
      scrollToPillAndExpand(idx);
    });

    // Hover to highlight pill
    footnote.addEventListener('mouseenter', () => {
      highlightPill(idx, true);
    });
    footnote.addEventListener('mouseleave', () => {
      highlightPill(idx, false);
    });

    footnotes.appendChild(footnote);
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

/**
 * Scroll to a pill and expand it
 */
function scrollToPillAndExpand(idx) {
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

/**
 * Update the action count badge
 */
function updateActionCountBadge() {
  const badge = document.getElementById('actionCountBadge');
  if (badge) {
    const count = actionsMap.size;
    badge.textContent = count;
    badge.style.display = count > 0 ? '' : 'none';
  }
}

/**
 * Update or create progress indicator for hidden tool activity
 */
function updateProgressIndicator() {
  const chatOutput = document.getElementById('chatOutput');
  if (!chatOutput) return;

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
  scrollToBottom();
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

/**
 * Detect if content is a report (has YAML front-matter)
 * Returns report info object or null
 */
function detectReport(content) {
  if (!content) return null;

  // Check for YAML front-matter (starts with ---)
  const fmMatch = content.match(/^---\n([\s\S]*?)\n---\n/);
  if (!fmMatch) return null;

  const frontMatter = fmMatch[1];
  const info = { frontMatter: {} };

  // Parse front-matter fields
  const lines = frontMatter.split('\n');
  for (const line of lines) {
    const match = line.match(/^(\w[\w\s]*?):\s*(.+)$/);
    if (match) {
      info.frontMatter[match[1].trim()] = match[2].trim();
    }
  }

  // Try to find report filename (YYYY-MM-*.md pattern)
  const filenameMatch = content.match(/(\d{4}-\d{2}-[\w-]+\.md)/);
  if (filenameMatch) {
    info.filename = filenameMatch[1];
  }

  return info;
}

/**
 * Format a report with special styling and link
 */
function formatReport(content, reportInfo) {
  // Remove YAML front-matter for display
  const bodyContent = content.replace(/^---\n[\s\S]*?\n---\n/, '');

  // Build report header with metadata
  let header = '<div class="report-header">';
  header += '<div class="report-title">';
  header += '<i class="ri-file-text-line"></i> ';
  header += reportInfo.frontMatter['query category'] || 'Rapport';
  header += '</div>';

  if (reportInfo.frontMatter.date) {
    header += `<div class="report-meta"><i class="ri-calendar-line"></i> ${reportInfo.frontMatter.date}</div>`;
  }
  if (reportInfo.frontMatter.website) {
    header += `<div class="report-meta"><i class="ri-global-line"></i> ${reportInfo.frontMatter.website}</div>`;
  }

  // Add link to view full report if filename detected
  if (reportInfo.filename) {
    header += `<a href="/api/reports/${reportInfo.filename}" target="_blank" class="report-link">`;
    header += '<i class="ri-external-link-line"></i> Voir le rapport complet';
    header += '</a>';
  }

  header += '</div>';

  // Format the body content
  const formattedBody = formatAssistantContent(bodyContent);

  return header + '<div class="report-body">' + formattedBody + '</div>';
}

/**
 * Format assistant content using marked.js for proper markdown
 */
function formatAssistantContent(content) {
  if (!content) return '';

  // Use marked.js if available, fallback to simple formatting
  if (typeof marked !== 'undefined') {
    // Configure marked for safe rendering
    marked.setOptions({
      breaks: true,  // GFM line breaks
      gfm: true,     // GitHub Flavored Markdown
    });

    return marked.parse(content);
  }

  // Fallback: simple markdown-ish
  let html = escapeHtml(content);
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\n/g, '<br>');
  return html;
}

/**
 * Render mermaid diagrams in an element
 */
async function renderMermaid(element) {
  if (typeof mermaid === 'undefined') return;

  // Find code blocks with mermaid language
  const codeBlocks = element.querySelectorAll('pre code.language-mermaid');

  for (const block of codeBlocks) {
    const code = block.textContent;
    const container = document.createElement('div');
    container.className = 'mermaid';

    try {
      const { svg } = await mermaid.render('mermaid-' + Date.now(), code);
      container.innerHTML = svg;
      block.parentElement.replaceWith(container);
    } catch (err) {
      console.error('Mermaid rendering failed:', err);
      // Keep original code block if rendering fails
    }
  }
}

/**
 * Render options blocks as clickable buttons
 * Format: ```options\nLabel\nLabel | full request text\n```
 * Text after | is the full prompt (editable by user), defaults to label
 */
function renderOptions(element) {
  const codeBlocks = element.querySelectorAll('pre code.language-options');

  for (const block of codeBlocks) {
    const code = block.textContent.trim();
    const lines = code.split('\n').filter(line => line.trim());

    const container = document.createElement('div');
    container.className = 'options-buttons';

    lines.forEach((line, index) => {
      const parts = line.split('|').map(p => p.trim());
      const label = parts[0];
      const fullPrompt = parts[1] || label;

      const button = document.createElement('button');
      // Last button is primary (recommended action), rest are outline
      const isLast = index === lines.length - 1;
      button.className = isLast ? 'btn btn-primary btn-sm' : 'btn btn-outline-primary btn-sm';
      button.textContent = label;
      button.dataset.prompt = fullPrompt;

      button.addEventListener('click', () => {
        const chatInput = document.getElementById('chatInput');
        if (chatInput) {
          chatInput.value = button.dataset.prompt;
          chatInput.focus();
          // Auto-resize textarea if needed
          chatInput.style.height = 'auto';
          chatInput.style.height = chatInput.scrollHeight + 'px';
        }
      });

      container.appendChild(button);
    });

    // Replace the code block with buttons
    const preElement = block.parentElement;
    preElement.replaceWith(container);
  }
}

/**
 * Format tool use event - collapsible with tool name on first line
 */
function formatToolUse(content) {
  if (!content) return '';

  const tool = content.tool || 'Unknown';
  const input = content.input || {};

  let inputStr = typeof input === 'object' ? JSON.stringify(input, null, 2) : String(input);
  const lines = inputStr.split('\n');
  const isLong = lines.length > 2;

  // Preview: first 2 lines
  const preview = lines.slice(0, 2).join('\n') + (isLong ? '\n…' : '');

  let html = `<div class="tool-header" onclick="toggleToolContent(this)">`;
  html += `<span class="tool-name">${escapeHtml(tool)}</span>`;
  if (isLong) {
    html += `<span class="tool-toggle"><i class="ri-arrow-down-s-line"></i></span>`;
  }
  html += `</div>`;

  html += `<div class="tool-content tool-preview">${escapeHtml(preview)}</div>`;
  if (isLong) {
    html += `<div class="tool-content tool-full">${escapeHtml(inputStr)}</div>`;
  }

  return html;
}

/**
 * Format tool result event - collapsible with tool name on first line
 */
function formatToolResult(content) {
  if (!content) return '';

  const tool = content.tool || '';
  const output = content.output || '';

  let outputStr = typeof output === 'object' ? JSON.stringify(output, null, 2) : String(output);
  const lines = outputStr.split('\n');
  const isLong = lines.length > 2;

  // Preview: first 2 lines
  const preview = lines.slice(0, 2).join('\n') + (isLong ? '\n…' : '');

  let html = `<div class="tool-header" onclick="toggleToolContent(this)">`;
  if (tool) {
    html += `<span class="tool-name">${escapeHtml(tool)}</span>`;
  }
  if (isLong) {
    html += `<span class="tool-toggle"><i class="ri-arrow-down-s-line"></i></span>`;
  }
  html += `</div>`;

  html += `<div class="tool-content tool-preview">${escapeHtml(preview)}</div>`;
  if (isLong) {
    html += `<div class="tool-content tool-full">${escapeHtml(outputStr)}</div>`;
  }

  return html;
}

/**
 * Toggle tool content visibility
 */
function toggleToolContent(header) {
  const block = header.closest('.event-block');
  if (!block) return;

  block.classList.toggle('tool-expanded');

  // Update icon
  const icon = header.querySelector('.tool-toggle i');
  if (icon) {
    if (block.classList.contains('tool-expanded')) {
      icon.className = 'ri-arrow-up-s-line';
    } else {
      icon.className = 'ri-arrow-down-s-line';
    }
  }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Show/hide streaming state
 */
function setStreamingState(streaming) {
  const sendBtn = document.getElementById('chatSendBtn');
  const cancelBtn = document.getElementById('chatCancelBtn');
  const input = document.getElementById('chatInput');

  if (sendBtn) sendBtn.style.display = streaming ? 'none' : 'flex';
  if (cancelBtn) cancelBtn.style.display = streaming ? 'flex' : 'none';
  if (input) input.disabled = streaming;
}

/**
 * Show loading indicator
 */
function showLoading() {
  const chatOutput = document.getElementById('chatOutput');
  if (!chatOutput) return;

  // Remove existing loading
  hideLoading();

  const loading = document.createElement('div');
  loading.className = 'loading-indicator';
  loading.id = 'loadingIndicator';
  loading.innerHTML = '<div class="spinner"></div> Matometa réfléchit…';

  chatOutput.appendChild(loading);
  scrollToBottom();
}

/**
 * Hide loading indicator
 */
function hideLoading() {
  const loading = document.getElementById('loadingIndicator');
  if (loading) loading.remove();
}

/**
 * Hide empty state
 */
function hideEmptyState() {
  const emptyState = document.getElementById('emptyState');
  if (emptyState) emptyState.style.display = 'none';
}

/**
 * Find a scroll anchor element (for Safari which lacks overflow-anchor support)
 * Returns the last user message or first visible event block
 */
function findScrollAnchor(chatOutput) {
  // Prefer last user message as anchor (always visible in all modes)
  const userMessages = chatOutput.querySelectorAll('.event-user');
  if (userMessages.length > 0) {
    return userMessages[userMessages.length - 1];
  }
  // Fallback to first event block
  return chatOutput.querySelector('.event-block');
}

/**
 * Format user message content, converting file context blocks to pills
 */
function formatUserContent(content) {
  // Pattern to match file context blocks:
  // [Uploaded file: filename]
  // - Size: ...
  // - Type: ...
  // - Path: ...
  // - Content (...): (optional, with code block)
  // - Note: ... (optional)
  const fileBlockPattern = /\[Uploaded file: ([^\]]+)\]\n(?:- [^\n]+\n)+(?:```[\s\S]*?```\n?)?/g;

  let result = content;
  const matches = content.match(fileBlockPattern);

  if (matches) {
    for (const match of matches) {
      // Extract filename from the match
      const filenameMatch = match.match(/\[Uploaded file: ([^\]]+)\]/);
      const filename = filenameMatch ? filenameMatch[1] : 'Fichier';

      // Extract file size
      const sizeMatch = match.match(/- Size: ([\d,]+) bytes/);
      const size = sizeMatch ? formatFileSize(parseInt(sizeMatch[1].replace(/,/g, ''))) : '';

      // Extract file type
      const typeMatch = match.match(/- Type: ([^\n]+)/);
      const mimeType = typeMatch ? typeMatch[1] : '';

      // Determine icon based on mime type
      let icon = 'ri-file-line';
      if (mimeType.startsWith('image/')) icon = 'ri-image-line';
      else if (mimeType.startsWith('text/') || mimeType.includes('json') || mimeType.includes('xml')) icon = 'ri-file-text-line';
      else if (mimeType.includes('pdf')) icon = 'ri-file-pdf-line';
      else if (mimeType.includes('spreadsheet') || mimeType.includes('excel') || mimeType.includes('csv')) icon = 'ri-file-excel-line';
      else if (mimeType.includes('word') || mimeType.includes('document')) icon = 'ri-file-word-line';

      // Create pill HTML
      const pill = `<span class="file-context-pill" title="${escapeHtml(mimeType)}"><i class="${icon}"></i> ${escapeHtml(filename)}${size ? ` <span class="file-context-size">(${size})</span>` : ''}</span>`;

      result = result.replace(match, pill);
    }
  }

  // Handle remaining content (the actual user message after ---)
  // Split by --- separator if present
  const parts = result.split(/\n---\n/);
  if (parts.length > 1) {
    // Pills are in first part, user message in second
    const pills = parts[0];
    const userText = parts.slice(1).join('\n---\n').trim();
    if (userText) {
      return `<div class="file-context-pills">${pills}</div><div class="user-text">${escapeHtml(userText)}</div>`;
    } else {
      return `<div class="file-context-pills">${pills}</div>`;
    }
  }

  // If no file blocks found, just escape and return
  if (!matches) {
    return escapeHtml(content);
  }

  return result;
}

/**
 * Show error message
 */
function showError(message) {
  appendEvent('error', { content: message });
}

/**
 * Scroll chat to bottom
 */
function scrollToBottom() {
  const chatOutput = document.getElementById('chatOutput');
  if (chatOutput) {
    chatOutput.scrollTop = chatOutput.scrollHeight;
  }
}

/**
 * Load an existing conversation by ID
 */
async function loadConversation(convId) {
  // Close any existing EventSource before loading new conversation
  closeEventSource();

  // Reset actions sidebar state
  resetActionsState();

  try {
    const response = await fetch(`/api/conversations/${convId}`);
    if (!response.ok) {
      console.error('Failed to load conversation:', response.status);
      return;
    }

    const conv = await response.json();
    currentConversationId = conv.id;

    // Clear loading indicator
    const loadingIndicator = document.getElementById('loadingConversation');
    if (loadingIndicator) {
      loadingIndicator.remove();
    }

    // Hide empty state
    hideEmptyState();

    // Render existing messages
    const chatOutput = document.getElementById('chatOutput');
    if (chatOutput && conv.messages) {
      // Clear existing content first
      chatOutput.innerHTML = '';

      for (const msg of conv.messages) {
        if (msg.type === 'user') {
          appendEvent('user', { content: msg.content });
        } else if (msg.type === 'assistant') {
          appendEvent('assistant', { content: msg.content });
        } else if (msg.type === 'tool_use') {
          try {
            const content = JSON.parse(msg.content);
            appendEvent('tool_use', { content });
          } catch {
            appendEvent('tool_use', { content: { tool: 'unknown', input: msg.content } });
          }
        } else if (msg.type === 'tool_result') {
          try {
            const content = JSON.parse(msg.content);
            appendEvent('tool_result', { content });
          } catch {
            appendEvent('tool_result', { content: { output: msg.content } });
          }
        } else if (msg.type === 'report') {
          appendEvent('report', { content: msg.content });
        }
      }

      // Add footnotes to the last assistant message
      addFootnotesToLastAssistant();
    }

    // Update URL without reload
    window.history.replaceState({}, '', `/explorations/${convId}`);

    // If conversation is running, resume the stream and scroll to bottom
    if (conv.is_running) {
      console.log('Conversation is running, resuming stream...');
      // Delay scroll to ensure DOM is fully laid out after HTMX swap
      setTimeout(() => {
        scrollToBottom();
        // Also scroll window to show the chat input area
        window.scrollTo(0, document.body.scrollHeight);
      }, 50);
      startStream();
    }

  } catch (error) {
    console.error('Failed to load conversation:', error);
  }
}

/**
 * Start a fresh conversation (clear current state)
 */
function startFreshConversation() {
  closeEventSource();
  currentConversationId = null;
  lastUserMessage = null;
  retryCount = 0;

  // Reset actions sidebar
  resetActionsState();

  // Deselect active conversation in sidebar
  document.querySelectorAll('.nav-sublink.active').forEach(el => el.classList.remove('active'));

  // Clear chat output
  const chatOutput = document.getElementById('chatOutput');
  if (chatOutput) {
    chatOutput.innerHTML = `
      <div class="empty-state" id="emptyState">
        <i class="ri-chat-3-line ri-4x text-disabled mb-3"></i>
        <p class="mb-0 text-muted">Posez une question pour commencer</p>
        <p class="small text-muted">Ex : « Combien de visiteurs sur les Emplois en décembre ? »</p>
      </div>
    `;
  }

  // Update URL
  window.history.replaceState({}, '', '/explorations/new');

  // Focus input
  const input = document.getElementById('chatInput');
  if (input) {
    input.focus();
  }
}

/**
 * Format a report card for display in conversation
 */
function formatReportCard(data) {
  const reportId = data.report_id || data.id;
  const title = data.title || 'Rapport';
  const viewUrl = `/rapports/${reportId}`;

  return `
    <div class="report-card-inline">
      <a href="${viewUrl}" class="report-card-link">
        <i class="ri-file-text-line"></i>
        <span class="report-card-title">${escapeHtml(title)}</span>
        <i class="ri-arrow-right-s-line"></i>
      </a>
    </div>
  `;
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
