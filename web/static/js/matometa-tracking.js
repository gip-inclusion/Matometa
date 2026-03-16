/**
 * Système de tracking frontend pour Matometa
 * À intégrer dans les templates HTML de l'application
 */

class MatomataFrontendTracker {
    constructor() {
        this.sessionId = this.getOrCreateSession();
        this.pageStartTime = Date.now();
        this.interactions = [];
        this.setupEventListeners();
        this.trackPageView();
    }

    getOrCreateSession() {
        let session = localStorage.getItem('matometa_session');
        if (!session) {
            session = 'sess_' + Math.random().toString(36).substr(2, 12);
            localStorage.setItem('matometa_session', session);
        }
        return session;
    }

    // Envoyer les données de tracking au serveur
    async sendTracking(eventType, data) {
        try {
            await fetch('/api/tracking', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    event_type: eventType,
                    session_id: this.sessionId,
                    timestamp: new Date().toISOString(),
                    page_url: window.location.pathname,
                    ...data
                })
            });
        } catch (error) {
            console.warn('Tracking failed:', error);
        }
    }

    // Tracker une vue de page
    trackPageView() {
        this.sendTracking('page_view', {
            page_title: document.title,
            referrer: document.referrer
        });
    }

    // Tracker les clics sur des éléments spécifiques
    setupEventListeners() {
        // Clics sur les liens Metabase
        document.addEventListener('click', (event) => {
            const target = event.target.closest('a, button');
            if (!target) return;

            const href = target.href || target.dataset.href;
            const text = target.textContent.trim();

            if (href && href.includes('metabase')) {
                this.sendTracking('click_metabase_link', {
                    link_url: href,
                    link_text: text,
                    element_id: target.id,
                    element_class: target.className
                });
            }

            if (href && href.includes('github')) {
                this.sendTracking('click_github_link', {
                    link_url: href,
                    link_text: text
                });
            }

            if (target.dataset.trackAction) {
                this.sendTracking('user_action', {
                    action: target.dataset.trackAction,
                    target_text: text,
                    target_id: target.id
                });
            }
        });

        // Tracker le temps passé sur la page
        let scrollDepth = 0;
        window.addEventListener('scroll', () => {
            const currentDepth = (window.scrollY + window.innerHeight) / document.body.scrollHeight;
            if (currentDepth > scrollDepth) {
                scrollDepth = Math.round(currentDepth * 100);
            }
        });

        // Envoyer les métriques avant de quitter la page
        window.addEventListener('beforeunload', () => {
            const timeSpent = Math.round((Date.now() - this.pageStartTime) / 1000);

            this.sendTracking('page_exit', {
                time_spent_seconds: timeSpent,
                scroll_depth_percent: scrollDepth,
                interactions_count: this.interactions.length
            });
        });

        // Tracker les soumissions de formulaires
        document.addEventListener('submit', (event) => {
            const form = event.target;
            const formData = new FormData(form);
            const formId = form.id || form.className;

            this.sendTracking('form_submit', {
                form_id: formId,
                form_action: form.action,
                field_count: formData.size
            });
        });
    }

    // Méthodes publiques pour tracking manuel
    trackQuery(queryType, instance, status, executionTime) {
        this.sendTracking('query_execution', {
            query_type: queryType,
            instance: instance,
            status: status,
            execution_time_ms: executionTime
        });
    }

    trackDownload(fileName, fileType) {
        this.sendTracking('file_download', {
            file_name: fileName,
            file_type: fileType
        });
    }

    trackFeatureUsage(featureName, featureData = {}) {
        this.sendTracking('feature_usage', {
            feature_name: featureName,
            feature_data: featureData
        });
    }
}

// Initialiser le tracker quand la page est chargée
window.addEventListener('DOMContentLoaded', () => {
    window.matomataTracker = new MatomataFrontendTracker();
});

// Fonctions utilitaires pour usage manuel
function trackClick(elementName) {
    if (window.matomataTracker) {
        window.matomataTracker.sendTracking('manual_click', {
            element_name: elementName
        });
    }
}

function trackCustomEvent(eventName, eventData = {}) {
    if (window.matomataTracker) {
        window.matomataTracker.sendTracking('custom_event', {
            event_name: eventName,
            event_data: eventData
        });
    }
}

/*
EXEMPLES D'USAGE DANS LES TEMPLATES MATOMETA:

1. Dans le <head> des templates:
<script src="/static/js/matometa-tracking.js"></script>

2. Pour tracker des clics spécifiques:
<a href="/dashboard" data-track-action="view_dashboard">Dashboard</a>
<button onclick="trackClick('export_button')">Exporter</button>

3. Pour tracker des actions spécifiques:
<script>
function onMetabaseQuery() {
    trackCustomEvent('metabase_query', {
        instance: 'stats',
        query_type: 'sql'
    });
}
</script>

4. Dans les pages avec requêtes longues:
<script>
async function executeQuery() {
    const startTime = Date.now();

    try {
        const result = await fetch('/api/query', {...});
        const executionTime = Date.now() - startTime;

        matomataTracker.trackQuery('metabase', 'stats', 'success', executionTime);

    } catch (error) {
        const executionTime = Date.now() - startTime;
        matomataTracker.trackQuery('metabase', 'stats', 'error', executionTime);
    }
}
</script>
*/