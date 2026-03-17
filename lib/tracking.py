#!/usr/bin/env python3
"""
Système de tracking pour Matometa - Backend Flask
À intégrer dans l'application principale Matometa
"""

from functools import wraps
from datetime import datetime
import sqlite3
import json
import os
from flask import request, g, session
import hashlib

class MatomataTracker:
    """Système de tracking pour mesurer l'usage de Matometa"""

    def __init__(self, db_path="data/matometa_tracking.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Initialiser la base de données de tracking"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS page_views (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_session TEXT NOT NULL,
                    page_path TEXT NOT NULL,
                    page_title TEXT,
                    user_agent TEXT,
                    duration_seconds INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_session TEXT NOT NULL,
                    action_type TEXT NOT NULL,  -- 'click', 'query', 'download', 'api_call'
                    action_target TEXT NOT NULL,
                    action_data TEXT,  -- JSON avec détails
                    page_path TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_session TEXT NOT NULL,
                    query_type TEXT NOT NULL,  -- 'metabase', 'matomo', 'github'
                    query_instance TEXT,
                    execution_time_ms INTEGER,
                    status TEXT,  -- 'success', 'error'
                    row_count INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def get_user_session(self):
        """Générer un identifiant de session anonyme"""
        if 'tracking_session' not in session:
            # Créer un hash anonyme basé sur IP + User-Agent
            data = f"{request.remote_addr}:{request.user_agent.string}"
            session['tracking_session'] = hashlib.md5(data.encode()).hexdigest()[:12]
        return session['tracking_session']

    def track_page_view(self, page_path, page_title=None, duration=None):
        """Enregistrer une vue de page"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO page_views (timestamp, user_session, page_path, page_title, user_agent, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                self.get_user_session(),
                page_path,
                page_title,
                str(request.user_agent),
                duration
            ))

    def track_action(self, action_type, action_target, action_data=None):
        """Enregistrer une action utilisateur"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO user_actions (timestamp, user_session, action_type, action_target, action_data, page_path)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                self.get_user_session(),
                action_type,
                action_target,
                json.dumps(action_data) if action_data else None,
                request.path
            ))

    def track_query(self, query_type, instance, execution_time_ms, status, row_count=None):
        """Enregistrer une performance de requête"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO query_performance (timestamp, user_session, query_type, query_instance, execution_time_ms, status, row_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                self.get_user_session(),
                query_type,
                instance,
                execution_time_ms,
                status,
                row_count
            ))

# Instance globale du tracker
tracker = MatomataTracker()

def track_page(page_title=None):
    """Décorateur pour tracker automatiquement les vues de page"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Tracker la vue de page
            tracker.track_page_view(request.path, page_title)

            # Exécuter la fonction originale
            return f(*args, **kwargs)

        return decorated_function
    return decorator

def track_action_decorator(action_type, action_target):
    """Décorateur pour tracker les actions"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            result = f(*args, **kwargs)

            # Tracker l'action après succès
            tracker.track_action(action_type, action_target, {
                'args': str(args)[:100],
                'kwargs': str(kwargs)[:100]
            })

            return result
        return decorated_function
    return decorator

# Middleware pour tracking automatique
def init_tracking_middleware(app):
    """Initialiser le middleware de tracking dans Flask"""

    @app.before_request
    def before_request():
        g.start_time = datetime.now()

    @app.after_request
    def after_request(response):
        # Calculer le temps de réponse
        if hasattr(g, 'start_time'):
            duration_ms = (datetime.now() - g.start_time).total_seconds() * 1000

            # Tracker les pages vues automatiquement
            if response.status_code == 200 and request.method == 'GET':
                if not request.path.startswith('/static'):
                    tracker.track_page_view(request.path, duration=duration_ms)

        return response

# Exemples d'usage dans l'app Matometa
"""
# 1. Dans app.py (Flask principal)
from tracking import init_tracking_middleware, tracker, track_page

init_tracking_middleware(app)

# 2. Dans les routes importantes
@app.route('/')
@track_page("Dashboard Principal")
def dashboard():
    return render_template('dashboard.html')

@app.route('/export/csv')
@track_action_decorator('download', 'export_csv')
def export_csv():
    # Générer CSV...
    tracker.track_action('download', 'export_csv', {'format': 'csv'})
    return send_file(csv_file)

# 3. Dans lib.query (requêtes API)
def execute_query_with_tracking(source, instance, caller, **kwargs):
    start_time = datetime.now()

    try:
        result = execute_query(source, instance, caller, **kwargs)

        # Tracker le succès
        execution_time = (datetime.now() - start_time).total_seconds() * 1000
        tracker.track_query(source, instance, execution_time, 'success', len(result.data))

        return result

    except Exception as e:
        # Tracker l'erreur
        execution_time = (datetime.now() - start_time).total_seconds() * 1000
        tracker.track_query(source, instance, execution_time, 'error')
        raise
"""