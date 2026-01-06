"""
Test Matomo web UI URLs to find correct category/subcategory mappings.

Usage:
    from scripts.ui_tester import test_ui_url, discover_categories
"""

import subprocess
import urllib.parse
import re
from pathlib import Path
from typing import Optional


def _load_cookie() -> str:
    """Load cookie from .matomo_cookie file."""
    cookie_path = Path(__file__).parent.parent.parent.parent / ".matomo_cookie"
    if not cookie_path.exists():
        raise FileNotFoundError(
            f"Cookie file not found at {cookie_path}. "
            "Get a fresh cookie from browser dev tools and save it there."
        )
    return cookie_path.read_text().strip()


def _clear_cookie():
    """Clear the cookie file (call when it starts 403ing)."""
    cookie_path = Path(__file__).parent.parent.parent.parent / ".matomo_cookie"
    if cookie_path.exists():
        cookie_path.write_text("")
        print("Cookie cleared. Get a fresh one from browser.")


def build_ui_url(
    site_id: int,
    period: str,
    date: str,
    category: str,
    subcategory: str,
    segment: Optional[str] = None,
) -> str:
    """Build a Matomo web UI URL."""
    base = "https://matomo.inclusion.beta.gouv.fr/index.php"

    main_params = {
        "module": "CoreHome",
        "action": "index",
        "idSite": site_id,
        "period": period,
        "date": date,
    }

    hash_params = {
        "category": category,
        "subcategory": subcategory,
    }
    if segment:
        hash_params["segment"] = segment

    main_query = urllib.parse.urlencode(main_params)
    hash_query = urllib.parse.urlencode(hash_params)

    return f"{base}?{main_query}#?{hash_query}"


def test_ui_url(
    site_id: int,
    period: str,
    date: str,
    category: str,
    subcategory: str,
    segment: Optional[str] = None,
    verbose: bool = False,
) -> dict:
    """
    Test a Matomo web UI URL and return status.

    Returns:
        dict with:
        - url: the URL tested
        - status: 'ok', 'redirect', 'error', or 'auth_failed'
        - title: page title if found
        - actual_category: where it actually landed (if different)
        - message: error message if any
    """
    url = build_ui_url(site_id, period, date, category, subcategory, segment)
    cookie = _load_cookie()

    # Use curl to fetch the page
    cmd = [
        "curl", "-s", "-L",
        "-H", f"Cookie: {cookie}",
        "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
        "-H", "Accept: text/html",
        "-w", "\n%{http_code}",
        url
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout

        # Extract HTTP status code (last line)
        lines = output.strip().split('\n')
        status_code = lines[-1] if lines else "000"
        html = '\n'.join(lines[:-1])

        if verbose:
            print(f"Status code: {status_code}")
            print(f"HTML length: {len(html)}")

        # Check for auth failure
        if status_code == "403" or "login" in html.lower() and "password" in html.lower():
            return {
                "url": url,
                "status": "auth_failed",
                "message": "Cookie expired or invalid. Get a fresh one."
            }

        # Extract page title
        title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else None

        # Check if we landed on a different category (redirect)
        # Look for the active menu item or category in the page
        actual_cat_match = re.search(r'"category"\s*:\s*"([^"]+)"', html)
        actual_subcat_match = re.search(r'"subcategory"\s*:\s*"([^"]+)"', html)

        actual_category = actual_cat_match.group(1) if actual_cat_match else None
        actual_subcategory = actual_subcat_match.group(1) if actual_subcat_match else None

        # Determine status
        if actual_category and actual_category != category:
            status = "redirect"
        elif actual_subcategory and actual_subcategory != subcategory:
            status = "redirect"
        elif "error" in (title or "").lower() or "404" in (title or ""):
            status = "error"
        else:
            status = "ok"

        return {
            "url": url,
            "status": status,
            "title": title,
            "requested": {"category": category, "subcategory": subcategory},
            "actual": {"category": actual_category, "subcategory": actual_subcategory},
        }

    except subprocess.TimeoutExpired:
        return {"url": url, "status": "error", "message": "Request timed out"}
    except Exception as e:
        return {"url": url, "status": "error", "message": str(e)}


def discover_categories(site_id: int = 117) -> dict[str, list[tuple[str, str]]]:
    """
    Discover available categories via Matomo API.

    Returns dict: {category_id: [(subcategory_id, subcategory_name), ...]}
    """
    import os
    import json
    from pathlib import Path

    # Load API credentials
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    env = {}
    with open(env_path) as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                env[k] = v

    url = env['MATOMO_URL']
    token = env['MATOMO_API_KEY']

    api_url = f"https://{url}/?module=API&method=API.getWidgetMetadata&idSite={site_id}&format=JSON&token_auth={token}"

    cmd = ['curl', '-s', api_url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)

    # Collect category -> subcategory mappings
    mappings = {}
    for widget in data:
        if isinstance(widget, dict):
            cat = widget.get('category', {})
            cat_id = cat.get('id', '') if isinstance(cat, dict) else ''
            subcat = widget.get('subcategory', {})
            if isinstance(subcat, dict):
                subcat_id = subcat.get('id', '')
                subcat_name = subcat.get('name', '')
            else:
                subcat_id = str(subcat) if subcat else ''
                subcat_name = ''

            if cat_id and subcat_id:
                if cat_id not in mappings:
                    mappings[cat_id] = []
                entry = (subcat_id, subcat_name)
                if entry not in mappings[cat_id]:
                    mappings[cat_id].append(entry)

    return mappings


def print_categories(site_id: int = 117):
    """Print all available categories in a readable format."""
    mappings = discover_categories(site_id)
    print(f"Available categories for site {site_id}:\n")
    for cat in sorted(mappings.keys()):
        print(f"\n{cat}:")
        for subcat_id, subcat_name in sorted(mappings[cat]):
            print(f"  {subcat_id} ({subcat_name})")


def test_all_mappings(site_id: int = 117, period: str = "month", date: str = "2025-12-01"):
    """Test all current UI mappings and report which ones work."""
    # Import the current mapping
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "querying"))
    from scripts.matomo import _UI_MAPPING

    print(f"Testing {len(_UI_MAPPING)} UI mappings...\n")

    results = {"ok": [], "redirect": [], "error": [], "auth_failed": []}

    for method, (category, subcategory) in _UI_MAPPING.items():
        # Handle None subcategory (custom dimensions)
        if subcategory is None:
            subcategory = "1"

        result = test_ui_url(site_id, period, date, category, subcategory)
        result["method"] = method
        results[result["status"]].append(result)

        status_icon = {"ok": "✓", "redirect": "→", "error": "✗", "auth_failed": "🔒"}
        print(f"{status_icon.get(result['status'], '?')} {method}")
        if result["status"] == "redirect":
            print(f"   Requested: {category}/{subcategory}")
            print(f"   Actual: {result['actual']['category']}/{result['actual']['subcategory']}")

    print(f"\n=== Summary ===")
    print(f"OK: {len(results['ok'])}")
    print(f"Redirected: {len(results['redirect'])}")
    print(f"Errors: {len(results['error'])}")
    if results['auth_failed']:
        print(f"Auth failed: {len(results['auth_failed'])} - refresh cookie!")

    return results


if __name__ == "__main__":
    # Quick test
    result = test_ui_url(
        site_id=117,
        period="month",
        date="2025-12-01",
        category="General_Visitors",
        subcategory="General_Overview"
    )
    print(result)
