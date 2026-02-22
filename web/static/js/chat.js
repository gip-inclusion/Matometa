/**
 * Matometa Chat Interface
 * Init, uploads, auth, streaming, page wiring.
 * Depends on: utils.js, actions.js
 */

let currentConversationId = null;
let eventSource = null;
let eventSourceConversationId = null;  // Track which conversation the eventSource belongs to
let retryCount = 0;
let lastUserMessage = null;
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

// File upload state
let pendingFiles = [];  // Files waiting to be uploaded
const MAX_FILE_SIZE = 200 * 1024 * 1024;  // 200 MB

// Scroll position management for htmx navigation
let isPopState = false;

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

    // Start streaming from after the user message we just sent
    startStream(data.after_id || 0);

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
 * Return the ID of the last message the client already has from a conv payload.
 */
function lastLoadedMsgId(conv) {
  return conv?.messages?.length
    ? conv.messages[conv.messages.length - 1].id
    : 0;
}

/**
 * Start SSE streaming for the current conversation
 */
function startStream(afterMsgId = 0) {
  if (!currentConversationId) return;

  // Close any existing connection first
  closeEventSource();

  setStreamingState(true);

  // Show loading indicator
  showLoading();

  // Connect to SSE endpoint (after= tells server where client left off)
  const afterParam = afterMsgId ? `?after=${afterMsgId}` : '';
  eventSource = new EventSource(`/api/conversations/${currentConversationId}/stream${afterParam}`);
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
  eventSource.addEventListener('done', async (e) => {
    eventSource.close();
    eventSource = null;
    eventSourceConversationId = null;
    setStreamingState(false);
    hideLoading();
    removeProgressIndicator();

    // Check if server says to reload (e.g., after wait_stream reconnection)
    let shouldReload = retryCount > 0;
    try {
      const data = JSON.parse(e.data || '{}');
      if (data.reload) shouldReload = true;
    } catch {}

    if (shouldReload && currentConversationId) {
      await loadConversation(currentConversationId, { autoStream: false });
    }

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

      // Conversation exists — reload from DB to catch missed events, then retry stream
      const reloaded = await loadConversation(currentConversationId, { autoStream: false });
      startStream(lastLoadedMsgId(reloaded));
      return;
    }

    // Max retries exceeded — but check if agent is still running before giving up
    try {
      const checkResponse = await fetch(`/api/conversations/${currentConversationId}`);
      if (checkResponse.ok) {
        const conv = await checkResponse.json();
        if (conv.is_running) {
          // Agent still running, reset retries and keep waiting
          console.log('Agent still running, resetting retries...');
          retryCount = 0;
          const reloaded = await loadConversation(currentConversationId, { autoStream: false });
          startStream(lastLoadedMsgId(reloaded));
          return;
        }
      }
    } catch (err) {
      console.error('Failed to check if agent is running:', err);
    }

    // Agent truly stopped or unreachable
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

  // Check scroll position BEFORE modifying DOM
  const wasAtBottom = isAtBottom();

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

  // Only scroll if user was at bottom
  if (wasAtBottom) {
    scrollToBottom();
  }
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
 * Show/hide streaming state
 */
function setStreamingState(streaming) {
  const sendBtn = document.getElementById('chatSendBtn');
  const cancelBtn = document.getElementById('chatCancelBtn');
  const input = document.getElementById('chatInput');

  if (sendBtn) sendBtn.style.display = streaming ? 'none' : 'flex';
  if (cancelBtn) cancelBtn.style.display = streaming ? 'flex' : 'none';
  if (input) input.disabled = streaming;

  // Finalize streaming block when streaming ends
  if (!streaming && streamingBlock) {
    renderMermaid(streamingBlock);
    renderOptions(streamingBlock);
    streamingBlock = null;
    streamingText = '';
  }
}

/**
 * Show loading indicator
 */
function showLoading() {
  const chatOutput = document.getElementById('chatOutput');
  if (!chatOutput) return;

  // Check scroll position BEFORE modifying DOM
  const wasAtBottom = isAtBottom();

  // Remove existing loading
  hideLoading();

  const loading = document.createElement('div');
  loading.className = 'loading-indicator';
  loading.id = 'loadingIndicator';
  loading.innerHTML = '<div class="spinner"></div> Matometa réfléchit…';

  chatOutput.appendChild(loading);

  // Only scroll if user was at bottom
  if (wasAtBottom) {
    scrollToBottom();
  }
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
 * Load an existing conversation by ID
 */
async function loadConversation(convId, { autoStream = true } = {}) {
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
          appendEvent('user', { content: msg.content, timestamp: msg.timestamp });
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

      // Mark final answers
      markFinalAnswersInConversation();

      // Reset streaming state after DB load — these are static events, not a live stream
      streamingBlock = null;
      streamingText = '';
    }

    // Update URL without reload (preserve hash if present)
    const hash = window.location.hash;
    window.history.replaceState({}, '', `/explorations/${convId}${hash}`);

    // Scroll handling: if URL has a section hash, scroll to it; otherwise scroll to bottom
    // Use longer delay to ensure DOM is fully rendered
    setTimeout(() => {
      if (hash) {
        const element = document.getElementById(hash.substring(1));
        if (element) {
          // Instant scroll on page load (no smooth)
          element.scrollIntoView({ block: 'start' });
          return;
        }
      }
      // Default: scroll to bottom
      scrollToBottom();
      window.scrollTo(0, document.body.scrollHeight);
    }, 100);

    // If conversation is running, resume the stream (unless caller handles it)
    if (autoStream && conv.is_running) {
      console.log('Conversation is running, resuming stream...');
      const lastMsgId = lastLoadedMsgId(conv);
      startStream(lastMsgId);
    }

    return conv;

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
