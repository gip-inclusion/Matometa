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

      // Update label
      if (viewModeLabel) {
        viewModeLabel.textContent = label;
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
  eventSource.addEventListener('done', () => {
    eventSource.close();
    eventSource = null;
    setStreamingState(false);
    hideLoading();
    removeProgressIndicator();
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
    // Check if this is a report (has YAML front-matter)
    const reportInfo = detectReport(data.content);
    if (reportInfo) {
      block.classList.add('event-report');
      block.innerHTML = formatReport(data.content, reportInfo);
    } else {
      block.innerHTML = formatAssistantContent(data.content);
    }
    // Render mermaid diagrams after adding to DOM
    setTimeout(() => renderMermaid(block), 0);
  } else if (type === 'tool_use') {
    block.innerHTML = formatToolUse(data.content);
  } else if (type === 'tool_result') {
    block.innerHTML = formatToolResult(data.content);
  } else if (type === 'error') {
    block.innerHTML = escapeHtml(data.content || '');
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
 * Format tool use event
 */
function formatToolUse(content) {
  if (!content) return '';

  const tool = content.tool || 'Unknown';
  const input = content.input || {};

  let html = `<div class="tool-name">${escapeHtml(tool)}</div>`;

  if (typeof input === 'object') {
    const inputStr = JSON.stringify(input, null, 2);
    html += `<div class="tool-content">${escapeHtml(inputStr)}</div>`;
  } else {
    html += `<div class="tool-content">${escapeHtml(String(input))}</div>`;
  }

  return html;
}

/**
 * Format tool result event - no truncation
 */
function formatToolResult(content) {
  if (!content) return '';

  const tool = content.tool || '';
  const output = content.output || '';

  let html = '';
  if (tool) {
    html += `<div class="tool-name">${escapeHtml(tool)}</div>`;
  }

  // Full output, no truncation
  let outputStr = typeof output === 'object' ? JSON.stringify(output, null, 2) : String(output);

  html += `<div class="tool-content">${escapeHtml(outputStr)}</div>`;

  return html;
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
