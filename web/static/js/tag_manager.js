// --- State ---
let currentSiteData = null;
const siteCache = {};
const layoutEl = document.querySelector('.tm-layout');
const selectedSiteId = JSON.parse(layoutEl.dataset.selectedSite);
const selectedTriggerId = JSON.parse(layoutEl.dataset.selectedTrigger);
const matomoUrl = layoutEl.dataset.matomoUrl;

// --- DOM helpers ---
function clone(id) {
  return document.getElementById(id).content.firstElementChild.cloneNode(true);
}

function badge(className, text) {
  const el = document.createElement('span');
  el.className = 'badge ' + className;
  el.textContent = text;
  return el;
}

function matomoLink(href) {
  const el = clone('tpl-matomo-link');
  el.href = href;
  return el;
}

function labelValue(label, value, tag) {
  const div = document.createElement('div');
  const span = document.createElement('span');
  span.className = 'text-muted small';
  span.textContent = label;
  const val = document.createElement(tag || 'code');
  val.textContent = value;
  div.append(span, ' ', val);
  return div;
}

// Row with a label and multiple children (elements or strings), comma-separated
function labelRow(label, children, className) {
  const div = document.createElement('div');
  div.className = className || 'mt-2';
  const span = document.createElement('span');
  span.className = 'text-muted small';
  span.textContent = label;
  div.append(span, ' ');
  children.forEach((child, i) => {
    if (i > 0) div.append(', ');
    div.append(child);
  });
  return div;
}

function replaceChildren(el, ...children) {
  el.textContent = '';
  el.append(...children);
}

// --- URLs ---
function matomoTriggerUrl(siteId, containerId, triggerId) {
  return matomoUrl + '/index.php?module=TagManager&action=manageTriggers&idSite=' + siteId + '&idContainer=' + containerId + '#?idTrigger=' + triggerId;
}

function matomoTagUrl(siteId, containerId, tagId) {
  return matomoUrl + '/index.php?module=TagManager&action=manageTags&idSite=' + siteId + '&idContainer=' + containerId + '#?idTag=' + tagId;
}

// --- Tag type helpers ---
function tagTypeCss(type) {
  switch (type) {
    case 'Matomo': return 'tm-type-matomo';
    case 'CustomHtml': return 'tm-type-customhtml';
    case 'LinkedinInsight': return 'tm-type-linkedininsight';
    default: return 'tm-type-default';
  }
}

function tagTypeLabel(type) {
  switch (type) {
    case 'CustomHtml': return 'CustomHTML';
    case 'LinkedinInsight': return 'LinkedIn';
    default: return type;
  }
}

// --- Mobile navigation ---
function mobileShowPane(pane) {
  layoutEl.classList.remove('tm-show-triggers', 'tm-show-details');
  if (pane === 'triggers') layoutEl.classList.add('tm-show-triggers');
  else if (pane === 'details') layoutEl.classList.add('tm-show-details');
}

function mobileBack(target) {
  mobileShowPane(target === 'sites' ? 'sites' : 'triggers');
}

// --- URL management ---
function pushUrl(matomoId, triggerId) {
  let path = '/tag-manager';
  if (matomoId) {
    path += '/' + matomoId;
    if (triggerId) path += '/' + triggerId;
  }
  history.pushState({ matomoId, triggerId }, '', path);
}

// --- Preload all site counts + auto-select from URL ---
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.tm-sites-pane .tm-list-item').forEach(btn => {
    const matomoId = btn.dataset.matomoId;
    fetch('/api/tag-manager/site/' + matomoId)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => {
        siteCache[matomoId] = data;
        updateSiteCounts(matomoId, data);
      })
      .catch(() => {
        const el = document.getElementById('count-' + matomoId);
        if (el) {
          const pill = document.createElement('span');
          pill.className = 'tm-count-pill';
          pill.style.color = '#dc3545';
          pill.textContent = 'erreur';
          replaceChildren(el, pill);
        }
      });
  });

  if (selectedSiteId) {
    const siteBtn = document.querySelector('.tm-sites-pane .tm-list-item[data-matomo-id="' + selectedSiteId + '"]');
    if (siteBtn) selectSite(siteBtn, true, selectedTriggerId);
  }
});

// --- Handle browser back/forward ---
function resetPanes() {
  document.querySelectorAll('.tm-list-item').forEach(b => b.classList.remove('active'));
  replaceChildren(document.getElementById('tmTriggersList'), clone('tpl-empty-site'));
  replaceChildren(document.getElementById('tmDetailsContent'), clone('tpl-empty-trigger'));
  document.getElementById('tmTriggersHeader').textContent = 'Triggers';
  document.getElementById('tmDetailsHeader').textContent = 'Tags';
  document.getElementById('tmFooter').textContent = '';
  currentSiteData = null;
  mobileShowPane('sites');
}

window.addEventListener('popstate', function(e) {
  const state = e.state;
  if (!state) { resetPanes(); return; }
  if (state.matomoId) {
    const siteBtn = document.querySelector('.tm-sites-pane .tm-list-item[data-matomo-id="' + state.matomoId + '"]');
    if (siteBtn) selectSite(siteBtn, true, state.triggerId);
  }
});

// --- Site selection ---
async function selectSite(btn, skipPush, autoTriggerId) {
  document.querySelectorAll('.tm-sites-pane .tm-list-item').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  const matomoId = btn.dataset.matomoId;
  if (!skipPush) pushUrl(matomoId);

  const triggersList = document.getElementById('tmTriggersList');
  replaceChildren(triggersList, clone('tpl-loading'));
  replaceChildren(document.getElementById('tmDetailsContent'), clone('tpl-empty-trigger'));
  document.getElementById('tmDetailsHeader').textContent = 'Tags';

  try {
    let data = siteCache[matomoId];
    if (!data) {
      const resp = await fetch('/api/tag-manager/site/' + matomoId);
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.error || 'Erreur API');
      }
      data = await resp.json();
      siteCache[matomoId] = data;
      updateSiteCounts(matomoId, data);
    }
    currentSiteData = data;

    renderTriggers(data);
    updateFooter(data);
    mobileShowPane('triggers');

    if (autoTriggerId) {
      const triggerBtn = document.querySelector('.tm-triggers-pane .tm-list-item[data-trigger-id="' + autoTriggerId + '"]');
      if (triggerBtn) selectTrigger(autoTriggerId, triggerBtn, true);
    }
  } catch (err) {
    const errEl = clone('tpl-error');
    errEl.querySelector('.tm-error-msg').textContent = err.message;
    replaceChildren(triggersList, errEl);
  }
}

// --- Render triggers ---
function renderTriggers(data) {
  const triggers = data.triggers || [];
  const tags = data.tags || [];
  const container = document.getElementById('tmTriggersList');

  if (triggers.length === 0) {
    replaceChildren(container, clone('tpl-empty-no-triggers'));
    document.getElementById('tmTriggersHeader').textContent = 'Triggers';
    return;
  }

  // Build trigger-to-tags index
  const triggerTags = {};
  for (const tag of tags) {
    for (const tid of (tag.fire_trigger_ids || [])) {
      if (!triggerTags[tid]) triggerTags[tid] = [];
      triggerTags[tid].push(tag);
    }
  }

  // Sort: no conditions first, then with tags before orphans, then by name
  const sorted = [...triggers].sort((a, b) => {
    const aCond = (a.conditions || []).length === 0 ? 0 : 1;
    const bCond = (b.conditions || []).length === 0 ? 0 : 1;
    if (aCond !== bCond) return aCond - bCond;
    const aCount = (triggerTags[a.idtrigger] || []).length;
    const bCount = (triggerTags[b.idtrigger] || []).length;
    if (aCount > 0 && bCount === 0) return -1;
    if (aCount === 0 && bCount > 0) return 1;
    return (a.name || '').localeCompare(b.name || '');
  });

  document.getElementById('tmTriggersHeader').textContent = 'Triggers (' + triggers.length + ')';

  const frag = document.createDocumentFragment();
  for (const trigger of sorted) {
    const tTags = triggerTags[trigger.idtrigger] || [];
    const conditions = trigger.conditions || [];
    const orphan = tTags.length === 0;

    const btn = clone('tpl-trigger-item');
    if (orphan) btn.classList.add('tm-orphan');
    btn.dataset.triggerId = trigger.idtrigger;
    btn.addEventListener('click', function() { selectTrigger(trigger.idtrigger, this); });

    btn.querySelector('.tm-item-name').textContent = trigger.name;
    btn.querySelector('.tm-trigger-type').textContent = trigger.type;

    const condPreview = conditions.length > 0
      ? conditions.map(c => c.actual + ' ' + c.comparison + ' "' + (c.expected || '') + '"').join(', ')
      : 'toutes les pages';
    btn.querySelector('.tm-trigger-cond').textContent = condPreview;

    const pillsEl = btn.querySelector('.tm-trigger-pills');
    if (tTags.length > 0) {
      const counts = {};
      for (const t of tTags) counts[t.type] = (counts[t.type] || 0) + 1;
      for (const [type, count] of Object.entries(counts)) {
        pillsEl.append(badge(tagTypeCss(type), count + ' ' + tagTypeLabel(type)));
      }
    } else {
      pillsEl.append(badge('bg-secondary', 'orphelin'));
    }

    frag.append(btn);
  }

  replaceChildren(container, frag);
}

// --- Trigger selection ---
function selectTrigger(triggerId, btn, skipPush) {
  document.querySelectorAll('.tm-triggers-pane .tm-list-item').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  if (!currentSiteData) return;

  const matomoId = document.querySelector('.tm-sites-pane .tm-list-item.active')?.dataset.matomoId;
  if (!skipPush && matomoId) pushUrl(matomoId, triggerId);

  const tags = (currentSiteData.tags || []).filter(
    t => (t.fire_trigger_ids || []).includes(triggerId)
  );
  const trigger = (currentSiteData.triggers || []).find(t => t.idtrigger === triggerId);

  renderTagDetails(trigger, tags);
  mobileShowPane('details');
}

// --- Render tag details ---
function renderTriggerCard(trigger) {
  const { site } = currentSiteData;
  const card = clone('tpl-trigger-card');
  card.querySelector('.tm-name').textContent = trigger.name;
  card.querySelector('.tm-type').textContent = trigger.type;

  if (trigger.draft_id) {
    card.querySelector('.tm-card-header').append(
      matomoLink(matomoTriggerUrl(site.matomo_id, site.container_id, trigger.draft_id))
    );
  }

  const body = card.querySelector('.tm-body');
  const conditions = trigger.conditions || [];
  if (conditions.length > 0) {
    const condDiv = document.createElement('div');
    condDiv.className = 'tm-conditions mt-2';
    for (const c of conditions) {
      const row = clone('tpl-condition');
      row.querySelector('.tm-actual').textContent = c.actual;
      row.querySelector('.tm-comparison').textContent = c.comparison;
      row.querySelector('.tm-expected').textContent = '"' + (c.expected || '') + '"';
      condDiv.append(row);
    }
    body.append(condDiv);
  } else {
    body.append(clone('tpl-no-conditions'));
  }

  return card;
}

function renderTagDetails(trigger, tags) {
  const container = document.getElementById('tmDetailsContent');

  if (tags.length === 0) {
    replaceChildren(container, clone('tpl-empty-no-tags'));
    document.getElementById('tmDetailsHeader').textContent = 'Tags';
    return;
  }

  document.getElementById('tmDetailsHeader').textContent = 'Tags (' + tags.length + ')';

  const frag = document.createDocumentFragment();

  if (trigger) frag.append(renderTriggerCard(trigger), clone('tpl-arrow'));

  for (let i = 0; i < tags.length; i++) {
    if (i > 0) {
      const arrow = clone('tpl-arrow');
      arrow.style.opacity = '0.4';
      frag.append(arrow);
    }
    frag.append(renderTagCard(tags[i]));
  }

  replaceChildren(container, frag);
}

// --- Tag type renderers (dispatched by type) ---
const tagRenderers = {
  CustomHtml(content, params) {
    if (params.htmlPosition) content.append(labelValue('Position:', params.htmlPosition));
    const codeBlock = document.createElement('div');
    codeBlock.className = 'tm-code-block mt-2';
    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.textContent = params.customHtml || '';
    pre.append(code);
    codeBlock.append(pre);
    content.append(codeBlock);
  },

  Matomo(content, params) {
    const trackingType = params.trackingType || 'pageview';
    content.append(labelValue('Tracking:', trackingType, 'strong'));
    if (trackingType === 'event') {
      for (const key of ['eventCategory', 'eventAction', 'eventName', 'eventValue']) {
        if (params[key]) content.append(labelValue(key.replace('event', '') + ':', params[key]));
      }
    }
    if (params.customDimensions?.length > 0) {
      const codes = params.customDimensions.map(d => {
        const c = document.createElement('code');
        c.textContent = 'dim' + (d.index || '') + '=' + (d.value || '');
        return c;
      });
      content.append(labelRow('Dimensions:', codes, 'mt-1'));
    }
  },

  LinkedinInsight(content) {
    const p = document.createElement('div');
    p.className = 'mt-2 text-muted small';
    p.textContent = 'LinkedIn Insight pixel';
    content.append(p);
  },
};

function renderTagCard(tag) {
  const card = clone('tpl-tag-card');
  if (tag.status === 'paused') card.classList.add('tm-paused');
  card.querySelector('.tm-name').textContent = tag.name;

  const { site } = currentSiteData;
  const actions = card.querySelector('.tm-actions');
  actions.append(badge(tagTypeCss(tag.type), tagTypeLabel(tag.type)));
  if (tag.status === 'paused') actions.append(badge('bg-secondary', 'pause'));
  if (tag.draft_id) actions.append(matomoLink(matomoTagUrl(site.matomo_id, site.container_id, tag.draft_id)));

  const badges = card.querySelector('.tm-tag-badges');
  badges.append(badge('bg-light text-dark', tag.fire_limit || 'unlimited'));
  if (tag.priority !== 999) badges.append(badge('bg-light text-dark', 'prio ' + tag.priority));

  const content = card.querySelector('.tm-tag-content');
  const renderer = tagRenderers[tag.type];
  if (renderer) renderer(content, tag.parameters || {});

  if (tag.block_trigger_ids?.length > 0) {
    const codes = tag.block_trigger_ids.map(id => {
      const t = (currentSiteData.triggers || []).find(tr => tr.idtrigger === id);
      const code = document.createElement('code');
      code.textContent = t ? t.name : '#' + id;
      return code;
    });
    content.append(labelRow('Bloque par:', codes));
  }

  if (tag.start_date || tag.end_date) {
    content.append(labelRow('Periode:', [(tag.start_date || '...') + ' \u2014 ' + (tag.end_date || '...')]));
  }

  return card;
}

// --- Helpers ---
function updateSiteCounts(matomoId, data) {
  const el = document.getElementById('count-' + matomoId);
  if (!el) return;
  const triggers = (data.triggers || []).length;
  const tags = (data.tags || []).length;
  const p1 = document.createElement('span');
  p1.className = 'tm-count-pill';
  p1.textContent = triggers + ' trigger' + (triggers !== 1 ? 's' : '');
  const p2 = document.createElement('span');
  p2.className = 'tm-count-pill';
  p2.textContent = tags + ' tag' + (tags !== 1 ? 's' : '');
  replaceChildren(el, p1, p2);
}

function updateFooter(data) {
  const footer = document.getElementById('tmFooter');
  if (!data.version) {
    footer.textContent = 'Pas de version publiee';
    return;
  }
  const rel = data.version;
  const triggers = (data.triggers || []).length;
  const tags = (data.tags || []).length;
  const variables = (data.variables || []).length;
  footer.textContent = triggers + ' triggers \u00b7 ' + tags + ' tags \u00b7 ' + variables + ' variables \u00b7 '
    + 'v' + rel.idcontainerversion + ' publiee le ' + (rel.release_date || '').slice(0, 10)
    + ' par ' + (rel.release_login || '?')
    + ' \u00b7 ' + data.query_time_ms + ' ms';
}
