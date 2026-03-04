/**
 * Message rendering: appendEvent dispatcher, format functions, mermaid/options.
 * Depends on: utils.js (escapeHtml, isAtBottom, scrollToBottom, formatFileSize)
 *             actions.js (streamingBlock, streamingText, pendingToolUses, lastAssistantBlock,
 *                         currentTurnActions, createAndAppendAction, addFootnotesToLastAssistant,
 *                         scanHeadingsForToc)
 */

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

  // Non-assistant event ends the streaming accumulation
  if (type !== 'assistant' && streamingBlock) {
    renderMermaid(streamingBlock);
    renderOptions(streamingBlock);
    streamingBlock = null;
    streamingText = '';
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

  // Check scroll position BEFORE adding content (for smart auto-scroll)
  const wasAtBottom = isAtBottom();

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

  // Streaming: accumulate assistant chunks into one block
  if (type === 'assistant' && streamingBlock) {
    streamingText += data.content;
    streamingBlock.dataset.rawContent = streamingText;
    streamingBlock.innerHTML = formatAssistantContent(streamingText);
    lastAssistantBlock = streamingBlock;
    // Keep loading indicator below the streaming block
    const loadingEl = document.getElementById('loadingIndicator');
    if (loadingEl) {
      chatOutput.appendChild(loadingEl);
    }
    // Scroll if needed
    if (isAtBottom()) {
      chatOutput.scrollTop = chatOutput.scrollHeight;
    }
    return;
  }

  const block = document.createElement('div');
  block.className = `event-block event-${type}`;

  if (type === 'user') {
    block.innerHTML = formatUserContent(data.content);
  } else if (type === 'assistant') {
    // Start streaming accumulation
    streamingText = data.content;
    streamingBlock = block;
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

  // Keep the loading indicator at the bottom (appendChild moves existing elements)
  const loadingEl = document.getElementById('loadingIndicator');
  if (loadingEl) {
    chatOutput.appendChild(loadingEl);
  }

  // Scan assistant messages for <h2> headings to populate TOC
  if (type === 'assistant') {
    scanHeadingsForToc(block);
  }

  // Only auto-scroll if user was already at bottom (preserves scroll position if reading history)
  if (wasAtBottom) {
    scrollToBottom();
  }
}

// =============================================================================
// Format functions
// =============================================================================

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

    // Sanity check: real options blocks are short lists of choices.
    // If the block is too long, it's a malformed code fence — leave it as-is.
    if (lines.length > 6 || lines.length === 0) continue;

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
        // Mark selected in this group
        container.querySelectorAll('.btn').forEach(b => {
          b.classList.remove('btn-primary', 'active');
          b.classList.add('btn-outline-primary');
        });
        button.classList.remove('btn-outline-primary');
        button.classList.add('btn-primary', 'active');

        // Collect all selected options across all groups in this message
        const msgBlock = button.closest('.message-content, .chat-output');
        const allGroups = msgBlock ? msgBlock.querySelectorAll('.options-buttons') : [container];
        const answers = [];
        allGroups.forEach(group => {
          const selected = group.querySelector('.btn.active');
          if (selected) answers.push(selected.dataset.prompt);
        });

        const chatInput = document.getElementById('chatInput');
        if (chatInput) {
          chatInput.value = answers.join('\n');
          chatInput.focus();
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

/**
 * Show error message
 */
function showError(message) {
  appendEvent('error', { content: message });
}
