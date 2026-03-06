/**
 * Pure utility functions — no dependencies on other chat modules.
 */

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function autoGrow(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
}

function isAtBottom() {
  // Use .chat-main as scroll container (matches scrollToBottom)
  const container = document.querySelector('.chat-main') || document.getElementById('chatOutput');
  if (!container) return true;

  // Consider "at bottom" if within 100px of the bottom
  const threshold = 100;
  return container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
}

function scrollToBottom() {
  // Scroll container is .chat-main, not .chat-output
  const chatMain = document.querySelector('.chat-main');
  if (chatMain) {
    chatMain.scrollTop = chatMain.scrollHeight;
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' o';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' Ko';
  return (bytes / (1024 * 1024)).toFixed(1) + ' Mo';
}

function truncateFilename(name, maxLen = 25) {
  if (name.length <= maxLen) return name;
  const ext = name.includes('.') ? '.' + name.split('.').pop() : '';
  const stem = name.slice(0, name.length - ext.length);
  const truncated = stem.slice(0, maxLen - ext.length - 3) + '...';
  return truncated + ext;
}
