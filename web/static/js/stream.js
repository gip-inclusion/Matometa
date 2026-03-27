/**
 * SSE streaming, conversation management, and loading UI.
 * Depends on: utils.js (autoGrow, isAtBottom, scrollToBottom)
 *             actions.js (streamingBlock, streamingText, resetActionsState,
 *                         removeProgressIndicator, markFinalAnswer,
 *                         markFinalAnswersInConversation, addFootnotesToLastAssistant)
 *             render.js (appendEvent, showError, renderMermaid, renderOptions)
 */

let currentConversationId = null;

/**
 * Validate that a conversation ID is a valid UUID to prevent URL manipulation.
 */
function isValidConversationId(id) {
  return typeof id === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
}

let eventSource = null;
let eventSourceConversationId = null;  // Track which conversation the eventSource belongs to
let retryCount = 0;
let lastUserMessage = null;
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

// Track which conversation has the sidebar spinner active
let _sidebarSpinnerConvId = null;

// =============================================================================
// Sending messages
// =============================================================================

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
      if (response.status === 404) {
        await recover({ createNew: true });
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

// =============================================================================
// SSE streaming
// =============================================================================

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

  // Content events — reset retry counter (agent is alive and producing output)
  ['assistant', 'tool_use', 'tool_result', 'system'].forEach(type => {
    eventSource.addEventListener(type, (e) => {
      retryCount = 0;
      const data = JSON.parse(e.data);
      if (typeof window.updateLoadingLastEvent === 'function') {
        if (type === 'assistant') {
          window.updateLoadingLastEvent('assistant', data);
        } else if (type === 'tool_use') {
          window.updateLoadingLastEvent('tool_use', data);
        }
      }
      appendEvent(type, data);
    });
  });

  // Server error events — display but do NOT reset retryCount
  // (resetting would prevent onerror from ever reaching MAX_RETRIES)
  eventSource.addEventListener('error', (e) => {
    const data = JSON.parse(e.data);
    appendEvent('error', data);
    hideLoading();
  });

  // Server heartbeat — resets retry counter during quiet periods (long tool calls)
  eventSource.addEventListener('heartbeat', () => {
    retryCount = 0;
  });

  // Completion — server sends this when agent finishes (needs_response cleared)
  eventSource.addEventListener('done', async (e) => {
    eventSource.close();
    eventSource = null;
    eventSourceConversationId = null;
    setStreamingState(false);
    hideLoading();
    removeProgressIndicator();

    // Reload if we reconnected mid-stream (may have missed events)
    if (retryCount > 0 && currentConversationId) {
      await loadConversation(currentConversationId, { autoStream: false });
    }

    markFinalAnswer();

    // Reconcile all sidebar spinners (catches background conversations that finished)
    reconcileSidebarSpinners();
  });

  // Connection lost — just reconnect. The server handles liveness logic.
  eventSource.onerror = async () => {
    eventSource.close();
    eventSource = null;
    eventSourceConversationId = null;

    if (retryCount >= MAX_RETRIES) {
      setStreamingState(false);
      hideLoading();
      removeProgressIndicator();
      appendRecoveryMessage();
      return;
    }

    retryCount++;
    await new Promise(resolve => setTimeout(resolve, RETRY_DELAY_MS * retryCount));

    // Reload conversation to catch missed messages, then reconnect if still running
    const reloaded = await loadConversation(currentConversationId, { autoStream: false });
    if (reloaded && reloaded.is_running) {
      startStream(lastLoadedMsgId(reloaded));
    } else if (reloaded) {
      // Conversation finished while we were reconnecting
      setStreamingState(false);
      hideLoading();
      removeProgressIndicator();
      markFinalAnswer();
    } else {
      setStreamingState(false);
      hideLoading();
      removeProgressIndicator();
      appendRecoveryMessage();
    }
  };
}

// =============================================================================
// Recovery & cancel
// =============================================================================

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
    <button class="btn btn-sm btn-outline-primary mt-2" onclick="recover()">
      Réessayer
    </button>
    <button class="btn btn-sm btn-outline-secondary mt-2 ms-2" onclick="recover({ createNew: true })">
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
 * Remove the recovery error message if visible
 */
function removeRecoveryMessage() {
  const chatOutput = document.getElementById('chatOutput');
  if (!chatOutput) return;
  const lastBlock = chatOutput.lastElementChild;
  if (lastBlock && lastBlock.classList.contains('event-error')) {
    lastBlock.remove();
  }
}

/**
 * Retry the last message, optionally in a new conversation
 */
async function recover({ createNew = false } = {}) {
  if (!lastUserMessage) {
    showError('Pas de message à réessayer');
    return;
  }

  removeRecoveryMessage();

  if (createNew) {
    currentConversationId = null;
    try {
      const resp = await fetch('/api/conversations', { method: 'POST' });
      const data = await resp.json();
      currentConversationId = data.id;
    } catch (error) {
      console.error('Failed to create conversation:', error);
      showError('Impossible de créer une nouvelle conversation');
      return;
    }
  }

  retryCount = 0;
  setStreamingState(true);
  showLoading();
  await sendToAgent(lastUserMessage);
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

// =============================================================================
// Streaming UI state
// =============================================================================

/**
 * Show/hide streaming state (send/cancel buttons, input, sidebar spinner)
 */
function setStreamingState(streaming) {
  const sendBtn = document.getElementById('chatSendBtn');
  const cancelBtn = document.getElementById('chatCancelBtn');
  const input = document.getElementById('chatInput');

  if (sendBtn) sendBtn.style.display = streaming ? 'none' : 'flex';
  if (cancelBtn) cancelBtn.style.display = streaming ? 'flex' : 'none';
  if (input) input.disabled = streaming;

  // Manage sidebar spinner
  if (streaming && currentConversationId) {
    setSidebarSpinner(currentConversationId, true);
  } else if (!streaming) {
    setSidebarSpinner(_sidebarSpinnerConvId, false);
  }

  // Finalize streaming block when streaming ends
  if (!streaming && streamingBlock) {
    renderMermaid(streamingBlock);
    renderOptions(streamingBlock);
    streamingBlock = null;
    streamingText = '';
  }
}

/**
 * Show or hide the spinner icon on a sidebar conversation link.
 * Stores the original icon class in data-icon so it can be restored.
 */
function setSidebarSpinner(convId, spinning) {
  if (!convId) return;
  const link = document.querySelector(`a.nav-link-conversation[href="/explorations/${convId}"]`);
  if (!link) return;
  const icon = link.querySelector('i');
  if (!icon) return;

  if (spinning) {
    // Save original icon class before replacing (skip if already a spinner)
    if (!icon.dataset.icon && !icon.classList.contains('ri-spin')) {
      icon.dataset.icon = icon.className;
    }
    icon.className = 'ri-loader-4-line ri-spin';
    _sidebarSpinnerConvId = convId;
  } else {
    // Restore original icon (fallback to chat icon for server-rendered spinners)
    icon.className = icon.dataset.icon || 'ri-chat-3-line';
    delete icon.dataset.icon;
    if (_sidebarSpinnerConvId === convId) _sidebarSpinnerConvId = null;
  }
}

/**
 * Reconcile sidebar spinners with actual server state.
 * Clears spinners for conversations that are no longer running.
 */
let _spinnerPollTimer = null;

async function reconcileSidebarSpinners() {
  try {
    const resp = await fetch('/api/conversations/running');
    if (!resp.ok) return;
    const { running } = await resp.json();
    const runningSet = new Set(running);

    // Find all sidebar links that currently show a spinner
    document.querySelectorAll('a.nav-link-conversation i.ri-loader-4-line.ri-spin').forEach(icon => {
      const link = icon.closest('a');
      if (!link) return;
      const href = link.getAttribute('href');
      const match = href && href.match(/\/explorations\/(.+)/);
      if (!match) return;
      const convId = match[1];
      if (!runningSet.has(convId)) {
        setSidebarSpinner(convId, false);
      }
    });
  } catch {
    // Silently ignore — this is best-effort
  }

  // Keep polling while any sidebar spinner is still visible
  _scheduleSpinnerPoll();
}

function _scheduleSpinnerPoll() {
  clearTimeout(_spinnerPollTimer);
  _spinnerPollTimer = null;

  const hasSpinners = document.querySelector('a.nav-link-conversation i.ri-loader-4-line.ri-spin');
  if (hasSpinners) {
    _spinnerPollTimer = setTimeout(reconcileSidebarSpinners, 5000);
  }
}

const LOADING_BASE = 'Autometa réfléchit…';

/**
 * Dernier événement utile après « Autometa réfléchit… » (même ligne ou repli legacy).
 */
function updateLoadingLastEvent(sourceType, data) {
  let techLine = '';
  if (sourceType === 'system' && data.raw && data.raw.subtype === 'api_retry') {
    const r = data.raw;
    const attempt = r.attempt != null ? r.attempt : '?';
    const max = r.max_retries != null ? r.max_retries : '?';
    const err = r.error != null ? String(r.error) : 'erreur';
    const st = r.error_status;
    if (st != null && st !== '') {
      techLine = `Appel API · tentative ${attempt}/${max} · dernier statut ${st} · ${err}`;
    } else {
      techLine = `Appel API · tentative ${attempt}/${max} · ${err}`;
    }
  } else if (sourceType === 'tool_use' && data.content && data.content.tool) {
    techLine = `Outil · ${data.content.tool}`;
  } else if (sourceType === 'assistant') {
    techLine = 'Appel modèle · génération de la réponse';
  }

  if (!techLine) {
    return;
  }

  const techEl = document.getElementById('loadingTech');
  const baseEl = document.getElementById('loadingBase');
  if (techEl && baseEl) {
    baseEl.textContent = LOADING_BASE;
    techEl.textContent = techLine;
    techEl.classList.remove('d-none');
    return;
  }

  const statusEl = document.getElementById('loadingStatus');
  if (statusEl) {
    statusEl.textContent = `${LOADING_BASE} — ${techLine}`;
    return;
  }

  const legacyDebug = document.getElementById('loadingDebug');
  if (legacyDebug) {
    legacyDebug.textContent = ` — ${techLine}`;
    legacyDebug.classList.remove('d-none');
    return;
  }

  const loading = document.getElementById('loadingIndicator');
  if (!loading) {
    return;
  }
  let fb = document.getElementById('loadingStatusFallback');
  if (!fb) {
    fb = document.createElement('div');
    fb.id = 'loadingStatusFallback';
    fb.className = 'loading-tech';
    fb.setAttribute('aria-live', 'polite');
    loading.appendChild(fb);
  }
  fb.textContent = `${LOADING_BASE} — ${techLine}`;
}

window.updateLoadingLastEvent = updateLoadingLastEvent;

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
  loading.className = 'loading-indicator flex-wrap';
  loading.id = 'loadingIndicator';
  loading.innerHTML = `
    <div class="spinner"></div>
    <div class="loading-indicator-text">
      <span id="loadingBase" class="loading-base">${LOADING_BASE}</span>
      <span id="loadingTech" class="loading-tech d-none" aria-live="polite"></span>
    </div>
  `;

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

// =============================================================================
// Conversation loading
// =============================================================================

/**
 * Load an existing conversation by ID
 */
async function loadConversation(convId, { autoStream = true } = {}) {
  if (!isValidConversationId(convId)) return;

  // Close any existing EventSource before loading new conversation
  closeEventSource();

  // Reset actions sidebar state
  resetActionsState();

  // Always clear the template loading spinner (even on error)
  const loadingIndicator = document.getElementById('loadingConversation');
  if (loadingIndicator) {
    loadingIndicator.remove();
  }

  try {
    const response = await fetch(`/api/conversations/${convId}`);
    if (!response.ok) {
      console.error('Failed to load conversation:', response.status);
      return;
    }

    const conv = await response.json();
    currentConversationId = conv.id;

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

      // Render mermaid diagrams before scrolling (they change layout height)
      const assistantBlocks = chatOutput.querySelectorAll('.event-assistant');
      for (const block of assistantBlocks) {
        await renderMermaid(block);
      }

      // Reset streaming state after DB load — these are static events, not a live stream
      streamingBlock = null;
      streamingText = '';
    }

    // Update URL without reload (preserve hash if present)
    const hash = window.location.hash;
    window.history.replaceState({}, '', `/explorations/${convId}${hash}`);

    // Scroll after layout settles (both main chat and actions sidebar)
    requestAnimationFrame(() => {
      if (hash) {
        const el = document.getElementById(hash.substring(1));
        if (el) { el.scrollIntoView({ block: 'start' }); return; }
      }
      scrollToBottom();
      scrollActionsToBottom();
    });

    // Reconcile sidebar spinners on every conversation load
    reconcileSidebarSpinners();

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

// Start polling for sidebar spinner reconciliation if any spinners are server-rendered
document.addEventListener('DOMContentLoaded', _scheduleSpinnerPoll);
