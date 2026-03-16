#!/usr/bin/env python3
"""
API endpoints pour collecter et analyser les données de tracking Matometa
À intégrer dans l'application Flask principale
"""

from flask import request, jsonify, Blueprint
import json
from datetime import datetime, timedelta
import sqlite3
from collections import defaultdict

# Blueprint pour les routes de tracking
tracking_bp = Blueprint('tracking', __name__, url_prefix='/api/tracking')

def get_tracking_db():
    """Connexion à la base de tracking"""
    return sqlite3.connect('data/matometa_tracking.db')

@tracking_bp.route('', methods=['POST'])
def collect_tracking():
    """Endpoint pour recevoir les données de tracking frontend"""
    try:
        data = request.get_json()

        if not data or 'event_type' not in data:
            return jsonify({'error': 'Missing event_type'}), 400

        # Valider les données requises
        required_fields = ['session_id', 'timestamp', 'page_url']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        # Insérer dans la base de données
        with get_tracking_db() as conn:
            conn.execute("""
                INSERT INTO user_actions (timestamp, user_session, action_type, action_target, action_data, page_path)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                data['timestamp'],
                data['session_id'],
                data['event_type'],
                data.get('page_url', ''),
                json.dumps(data),
                data.get('page_url', '')
            ))

        return jsonify({'status': 'success'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@tracking_bp.route('/analytics', methods=['GET'])
def get_analytics():
    """Endpoint pour récupérer les analytics"""
    try:
        # Paramètres de requête
        days = int(request.args.get('days', 7))
        start_date = datetime.now() - timedelta(days=days)

        analytics = {}

        with get_tracking_db() as conn:
            # 1. Utilisateurs uniques
            cursor = conn.execute("""
                SELECT COUNT(DISTINCT user_session) as unique_users
                FROM page_views
                WHERE timestamp >= ?
            """, (start_date.isoformat(),))
            analytics['unique_users'] = cursor.fetchone()[0]

            # 2. Pages les plus consultées
            cursor = conn.execute("""
                SELECT page_path, COUNT(*) as views
                FROM page_views
                WHERE timestamp >= ?
                GROUP BY page_path
                ORDER BY views DESC
                LIMIT 10
            """, (start_date.isoformat(),))
            analytics['top_pages'] = [
                {'page': row[0], 'views': row[1]}
                for row in cursor.fetchall()
            ]

            # 3. Actions les plus fréquentes
            cursor = conn.execute("""
                SELECT action_type, COUNT(*) as count
                FROM user_actions
                WHERE timestamp >= ?
                GROUP BY action_type
                ORDER BY count DESC
            """, (start_date.isoformat(),))
            analytics['top_actions'] = [
                {'action': row[0], 'count': row[1]}
                for row in cursor.fetchall()
            ]

            # 4. Performance des requêtes
            cursor = conn.execute("""
                SELECT
                    query_type,
                    query_instance,
                    AVG(execution_time_ms) as avg_time,
                    COUNT(*) as total_queries,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count
                FROM query_performance
                WHERE timestamp >= ?
                GROUP BY query_type, query_instance
            """, (start_date.isoformat(),))
            analytics['query_performance'] = [
                {
                    'type': row[0],
                    'instance': row[1],
                    'avg_time_ms': round(row[2] or 0, 2),
                    'total_queries': row[3],
                    'success_rate': round((row[4] / row[3]) * 100, 1) if row[3] > 0 else 0
                }
                for row in cursor.fetchall()
            ]

            # 5. Activité par jour
            cursor = conn.execute("""
                SELECT
                    DATE(timestamp) as date,
                    COUNT(DISTINCT user_session) as unique_users,
                    COUNT(*) as total_actions
                FROM user_actions
                WHERE timestamp >= ?
                GROUP BY DATE(timestamp)
                ORDER BY date DESC
            """, (start_date.isoformat(),))
            analytics['daily_activity'] = [
                {
                    'date': row[0],
                    'unique_users': row[1],
                    'total_actions': row[2]
                }
                for row in cursor.fetchall()
            ]

        return jsonify(analytics), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@tracking_bp.route('/mep-impact/<int:pr_number>', methods=['GET'])
def get_mep_impact(pr_number):
    """Calculer l'impact d'une MEP spécifique basé sur les données de tracking"""
    try:
        # Récupérer la date de la MEP depuis GitHub (ou base de données)
        # Pour l'exemple, on simule avec une date récente
        mep_date = datetime.now() - timedelta(days=7)

        before_start = mep_date - timedelta(days=7)
        before_end = mep_date
        after_start = mep_date
        after_end = mep_date + timedelta(days=7)

        impact_data = {}

        with get_tracking_db() as conn:
            # Comparer l'activité avant/après la MEP
            cursor = conn.execute("""
                SELECT
                    CASE
                        WHEN timestamp BETWEEN ? AND ? THEN 'before'
                        WHEN timestamp BETWEEN ? AND ? THEN 'after'
                    END as period,
                    COUNT(DISTINCT user_session) as unique_users,
                    COUNT(*) as total_actions
                FROM user_actions
                WHERE timestamp BETWEEN ? AND ?
                GROUP BY period
            """, (
                before_start.isoformat(), before_end.isoformat(),
                after_start.isoformat(), after_end.isoformat(),
                before_start.isoformat(), after_end.isoformat()
            ))

            results = {row[0]: {'users': row[1], 'actions': row[2]} for row in cursor.fetchall()}

            before = results.get('before', {'users': 0, 'actions': 0})
            after = results.get('after', {'users': 0, 'actions': 0})

            impact_data = {
                'pr_number': pr_number,
                'mep_date': mep_date.isoformat(),
                'before_mep': before,
                'after_mep': after,
                'impact': {
                    'users_change_pct': round(
                        ((after['users'] - before['users']) / before['users'] * 100)
                        if before['users'] > 0 else 0, 1
                    ),
                    'actions_change_pct': round(
                        ((after['actions'] - before['actions']) / before['actions'] * 100)
                        if before['actions'] > 0 else 0, 1
                    )
                }
            }

        return jsonify(impact_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Fonction pour intégrer dans l'app principale
def init_tracking_routes(app):
    """Intégrer les routes de tracking dans l'application Flask"""
    app.register_blueprint(tracking_bp)

    # Middleware pour tracking automatique des requêtes API
    @app.before_request
    def track_api_requests():
        if request.path.startswith('/api/') and request.method == 'POST':
            # Tracker les appels API importants
            from matometa_tracking_backend import tracker
            tracker.track_action('api_call', request.path, {
                'method': request.method,
                'content_type': request.content_type
            })

"""
INTÉGRATION DANS L'APP MATOMETA PRINCIPALE:

1. Dans app.py ou __init__.py:
from matometa_tracking_api import init_tracking_routes
from matometa_tracking_backend import init_tracking_middleware

# Initialiser le tracking
init_tracking_middleware(app)
init_tracking_routes(app)

2. Dans les templates HTML, ajouter le script:
<script src="{{ url_for('static', filename='js/matometa-tracking.js') }}"></script>

3. Pour mesurer l'impact d'une MEP:
GET /api/tracking/mep-impact/28  # Pour la PR #28

4. Pour voir les analytics:
GET /api/tracking/analytics?days=30

5. Exemples d'utilisation manuelle dans le code:
from matometa_tracking_backend import tracker

# Dans une route de téléchargement
@app.route('/export/csv')
def export_csv():
    tracker.track_action('download', 'csv_export', {
        'file_size': len(csv_content),
        'records_count': len(data)
    })
    return send_file(...)

# Dans lib.query pour tracker les requêtes
def execute_metabase_query_tracked(*args, **kwargs):
    start_time = time.time()
    try:
        result = execute_metabase_query(*args, **kwargs)
        tracker.track_query('metabase', kwargs.get('instance'),
                          (time.time() - start_time) * 1000, 'success',
                          len(result.data))
        return result
    except Exception as e:
        tracker.track_query('metabase', kwargs.get('instance'),
                          (time.time() - start_time) * 1000, 'error')
        raise
"""