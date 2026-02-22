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
