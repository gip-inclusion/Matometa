/**
 * Matometa Chat Interface
 * Handles conversation creation, SSE streaming, and UI updates
 */

let currentConversationId = null;
let eventSource = null;
let progressIndicator = null;
let progressDots = '';
let retryCount = 0;
let lastUserMessage = null;
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

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
    initChat();
    initKnowledge();

    // Scroll to top on new navigation, unless it's a back/forward
    if (!isPopState) {
      window.scrollTo(0, 0);
    }
    isPopState = false;

    // Check if we're on a conversation page
    const path = window.location.pathname;
    const convMatch = path.match(/^\/explorations\/([a-f0-9-]+)$/);
    if (convMatch && convMatch[1] !== currentConversationId) {
      currentConversationId = convMatch[1];
      loadConversation(convMatch[1]);
    } else if (path === '/explorations' || path === '/explorations/new') {
      currentConversationId = null;
      // Focus input on new conversation page
      if (path === '/explorations/new') {
        const input = document.getElementById('chatInput');
        if (input) input.focus();
      }
    }
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
  const input = document.getElementById('chatInput');
  const sendBtn = document.getElementById('chatSendBtn');
  const cancelBtn = document.getElementById('chatCancelBtn');
  const viewModeControl = document.getElementById('viewModeControl');
  const chatOutput = document.getElementById('chatOutput');

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

  // View mode segmented control
  if (viewModeControl && chatOutput) {
    const viewModeLabel = document.getElementById('viewModeLabel');

    viewModeControl.addEventListener('click', (e) => {
      const btn = e.target.closest('.segmented-btn');
      if (!btn) return;

      const mode = btn.dataset.mode;
      const label = btn.dataset.label;

      // Update active button
      viewModeControl.querySelectorAll('.segmented-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      // Update chat output class
      chatOutput.classList.remove('view-minimal', 'view-normal', 'view-verbose');
      chatOutput.classList.add(`view-${mode}`);

      // Ensure final answers are marked for minimal mode
      if (mode === 'minimal') {
        markFinalAnswersInConversation();
      }

      // Update label
      if (viewModeLabel) {
        viewModeLabel.textContent = label;
      }
    });
  }

  // Title editing
  initTitleEditing();
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
    titleInput.focus();
    titleInput.select();
  });

  // Cancel editing
  cancelBtn.addEventListener('click', () => {
    titleEdit.classList.add('d-none');
    titleDisplay.classList.remove('d-none');
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

  if (!message) {
    input.focus();
    return;
  }

  // Create conversation if needed
  if (!currentConversationId) {
    try {
      const response = await fetch('/api/conversations', { method: 'POST' });
      const data = await response.json();
      currentConversationId = data.id;

      // Redirect to conversation view if we're on the list view
      const chatOutput = document.getElementById('chatOutput');
      if (!chatOutput) {
        // We're on list view, redirect to conversation with pending message
        window.location.href = `/explorations/${currentConversationId}?message=${encodeURIComponent(message)}`;
        return;
      }

      // Update URL to new conversation (we're in the chat view)
      history.replaceState({}, '', `/explorations/${currentConversationId}`);
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

  // Show user message
  appendEvent('user', { content: message });

  // Save message for potential retry
  lastUserMessage = message;
  retryCount = 0;

  // Send message to API
  await sendToAgent(message);
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
 * Start SSE streaming for the current conversation
 */
function startStream() {
  if (!currentConversationId) return;

  setStreamingState(true);

  // Show loading indicator
  showLoading();

  // Connect to SSE endpoint
  eventSource = new EventSource(`/api/conversations/${currentConversationId}/stream`);

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
 * Append an event to the chat output
 */
function appendEvent(type, data) {
  const chatOutput = document.getElementById('chatOutput');
  if (!chatOutput) return;

  // System events are never shown
  if (type === 'system') {
    return;
  }

  // Tool events: update progress indicator if tools are hidden
  if (type === 'tool_use' || type === 'tool_result') {
    updateProgressIndicator();
  }

  // When assistant speaks, remove progress indicator
  if (type === 'assistant') {
    removeProgressIndicator();
  }

  const block = document.createElement('div');
  block.className = `event-block event-${type}`;

  if (type === 'user') {
    block.innerHTML = escapeHtml(data.content);
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
    // Render mermaid diagrams and options after adding to DOM
    setTimeout(() => {
      renderMermaid(block);
      renderOptions(block);
    }, 0);
  } else if (type === 'tool_use') {
    block.innerHTML = formatToolUse(data.content);
  } else if (type === 'tool_result') {
    block.innerHTML = formatToolResult(data.content);
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
 * Update or create progress indicator for hidden tool activity
 */
function updateProgressIndicator() {
  const chatOutput = document.getElementById('chatOutput');

  // Only show progress indicator if tools are hidden (not in verbose mode)
  if (!chatOutput || chatOutput.classList.contains('view-verbose')) {
    return;
  }

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
      // First button is primary, rest are outline
      button.className = index === 0 ? 'btn btn-primary btn-sm' : 'btn btn-outline-primary btn-sm';
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
      // Mark final answers for minimal view mode
      markFinalAnswersInConversation();
    }

    // Update URL without reload
    window.history.replaceState({}, '', `/explorations/${convId}`);

    // If conversation is running, resume the stream
    if (conv.is_running) {
      console.log('Conversation is running, resuming stream...');
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
  currentConversationId = null;
  lastUserMessage = null;
  retryCount = 0;

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
  const viewUrl = `/rapports?id=${reportId}`;

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
