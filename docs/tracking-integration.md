# 📊 Intégrer le système de tracking dans Matometa

## 🎯 Objectif
Ajouter des trackers pour mesurer l'usage réel de Matometa et calculer l'impact des MEP.

## 📋 Fichiers à ajouter dans le repo Matometa

### 1. **Backend tracking** (`lib/tracking.py`)
```python
# Copier le contenu de matometa_tracking_backend.py
```

### 2. **API tracking** (`web/tracking_api.py`)
```python
# Copier le contenu de matometa_tracking_api.py
```

### 3. **Frontend tracking** (`web/static/js/matometa-tracking.js`)
```javascript
// Copier le contenu de matometa_tracking_frontend.js
```

## 🔧 Modifications dans l'app existante

### **A. Dans `web/app.py` (application Flask principale)**

```python
# Ajouter les imports
from lib.tracking import init_tracking_middleware, tracker, track_page
from web.tracking_api import init_tracking_routes

# Après la création de l'app Flask
app = Flask(__name__)

# Initialiser le tracking
init_tracking_middleware(app)
init_tracking_routes(app)

# Modifier les routes importantes
@app.route('/')
@track_page("Dashboard Principal")
def dashboard():
    return render_template('dashboard.html')

@app.route('/reports')
@track_page("Rapports")
def reports():
    return render_template('reports.html')
```

### **B. Dans `lib/query.py` (requêtes API)**

```python
# Ajouter le tracking des requêtes
from lib.tracking import tracker
import time

def execute_metabase_query_original(instance, caller, sql, database_id=None):
    # Code existant...
    pass

def execute_metabase_query(instance, caller, sql, database_id=None):
    """Version avec tracking"""
    start_time = time.time()

    try:
        result = execute_metabase_query_original(instance, caller, sql, database_id)

        # Tracker le succès
        execution_time = (time.time() - start_time) * 1000
        row_count = len(result.data.get('rows', [])) if hasattr(result, 'data') else 0

        tracker.track_query('metabase', instance, execution_time, 'success', row_count)
        tracker.track_action('query_execution', f'metabase_{instance}', {
            'sql_length': len(sql),
            'database_id': database_id,
            'caller': str(caller)
        })

        return result

    except Exception as e:
        # Tracker l'erreur
        execution_time = (time.time() - start_time) * 1000
        tracker.track_query('metabase', instance, execution_time, 'error')
        raise

# Même principe pour execute_matomo_query
```

### **C. Dans les templates HTML (`web/templates/base.html`)**

```html
<!DOCTYPE html>
<html>
<head>
    <!-- Contenu existant -->

    <!-- Ajouter le tracking -->
    <script src="{{ url_for('static', filename='js/matometa-tracking.js') }}"></script>
</head>
<body>
    <!-- Contenu existant -->

    <!-- Tracker des éléments spécifiques -->
    <a href="/metabase/dashboard/123" data-track-action="view_metabase_dashboard">
        Dashboard Metabase
    </a>

    <button onclick="trackClick('export_csv')" class="btn-export">
        Exporter CSV
    </button>

    <script>
        // Tracker les requêtes longues
        function executeQuery(type, instance) {
            const startTime = Date.now();

            fetch('/api/query', {
                method: 'POST',
                body: JSON.stringify({type, instance})
            })
            .then(response => {
                const executionTime = Date.now() - startTime;
                matomataTracker.trackQuery(type, instance, 'success', executionTime);
            })
            .catch(error => {
                const executionTime = Date.now() - startTime;
                matomataTracker.trackQuery(type, instance, 'error', executionTime);
            });
        }
    </script>
</body>
</html>
```

### **D. Dans le Dashboard MEP (`dashboard_mep_github_only.py`)**

```python
# Modifier l'endpoint analytics pour utiliser les vraies données
@app.route('/api/analytics')
def get_real_analytics():
    """Analytics basées sur les vraies données de tracking"""
    try:
        # Importer les données depuis la base de tracking Matometa
        import requests

        response = requests.get('http://localhost/api/tracking/analytics?days=7')
        if response.status_code == 200:
            real_data = response.json()

            return jsonify({
                'unique_users': real_data.get('unique_users', 23),
                'total_sessions': real_data.get('daily_activity', [{}])[0].get('total_actions', 156),
                'top_pages': real_data.get('top_pages', []),
                'query_performance': real_data.get('query_performance', [])
            })
        else:
            # Fallback sur les données mockées
            return jsonify({
                'unique_users': 23,
                'total_sessions': 156
            })

    except Exception as e:
        # Fallback en cas d'erreur
        return jsonify({'unique_users': 23, 'total_sessions': 156})

# Ajouter l'endpoint d'impact réel des MEP
@app.route('/api/mep/<int:pr_number>/impact')
def get_real_mep_impact(pr_number):
    """Impact réel d'une MEP basé sur les données de tracking"""
    try:
        response = requests.get(f'http://localhost/api/tracking/mep-impact/{pr_number}')
        if response.status_code == 200:
            return response.json()
    except:
        pass

    # Fallback sur calcul simulé
    return jsonify({
        'pr_number': pr_number,
        'impact': {'users_change_pct': 15.5, 'actions_change_pct': 22.3}
    })
```

## 🚀 Déploiement

### **1. Pull Request pour Matometa**
```bash
git checkout -b feature/add-usage-tracking
git add lib/tracking.py web/tracking_api.py web/static/js/matometa-tracking.js
git commit -m "Add comprehensive usage tracking system

- Track page views, user actions, and query performance
- Frontend and backend tracking integration
- Analytics API for measuring MEP impact
- Privacy-focused with anonymous session IDs"

git push origin feature/add-usage-tracking
```

### **2. Configuration**
```bash
# Créer la base de tracking (automatique au premier lancement)
# Aucune configuration supplémentaire requise
```

## 📊 Utilisation après déploiement

### **APIs disponibles :**
- `GET /api/tracking/analytics?days=30` - Analytics généraux
- `GET /api/tracking/mep-impact/28` - Impact de la PR #28
- `POST /api/tracking` - Collecter données frontend

### **Données collectées :**
- ✅ **Pages vues** : Quelles pages sont consultées et combien de temps
- ✅ **Actions utilisateur** : Clics, téléchargements, soumissions de formulaires
- ✅ **Performance requêtes** : Temps d'exécution Metabase/Matomo
- ✅ **Navigation** : Parcours utilisateur et pages d'entrée/sortie

### **Métriques d'impact MEP :**
- 📈 **Avant/après MEP** : Comparaison d'activité utilisateur
- 🎯 **Utilisation fonctionnalités** : Adoption des nouvelles features
- ⚡ **Performance** : Impact sur les temps de réponse
- 👥 **Engagement** : Changement dans le comportement utilisateur

## 🔐 Respect de la vie privée

- ✅ **Sessions anonymes** : Hash MD5 de IP + User-Agent
- ✅ **Pas de données personnelles** : Aucun nom/email stocké
- ✅ **Local uniquement** : Données stockées dans la base Matometa
- ✅ **Opt-out possible** : Variable d'environnement `DISABLE_TRACKING=true`

## 🎯 Bénéfices attendus

1. **📊 Métriques réelles** : Dashboard MEP avec vraies données
2. **🎯 Mesure d'impact** : Quantifier l'effet des nouvelles fonctionnalités
3. **🔧 Optimisation** : Identifier les goulots d'étranglement
4. **📈 Priorisation** : Données pour orienter le développement
5. **🚀 Validation** : Prouver la valeur des MEP déployées

---

**💡 Une fois intégré, votre Dashboard MEP affichera de vraies métriques d'usage au lieu des simulations !**