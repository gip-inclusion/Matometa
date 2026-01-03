"""
Matomo API client for cyberputois.

Usage:
    from scripts.matomo import MatomoAPI

    api = MatomoAPI()  # loads from .env
    summary = api.get_visits(site_id=117, period="month", date="2025-12-01")
"""

import os
import json
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any, Optional


class MatomoAPI:
    """Client for querying the Matomo API."""

    def __init__(self, url: Optional[str] = None, token: Optional[str] = None):
        """
        Initialize the API client.

        If url/token not provided, loads from .env file in project root.
        """
        if url and token:
            self.url = url
            self.token = token
        else:
            self._load_env()

    def _load_env(self):
        """Load credentials from .env file."""
        env_path = Path(__file__).parent.parent.parent.parent / ".env"
        if not env_path.exists():
            raise FileNotFoundError(f".env file not found at {env_path}")

        env = {}
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip()

        self.url = env.get("MATOMO_URL")
        self.token = env.get("MATOMO_API_KEY")

        if not self.url or not self.token:
            raise ValueError("MATOMO_URL and MATOMO_API_KEY must be set in .env")

    def _request(self, method: str, params: dict, timeout: int = 180) -> Any:
        """Make an API request."""
        base_params = {
            "module": "API",
            "method": method,
            "format": "JSON",
            "token_auth": self.token,
        }
        base_params.update(params)

        query = urllib.parse.urlencode(base_params)
        url = f"https://{self.url}/?{query}"

        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                data = json.loads(response.read().decode())

                # Check for API errors
                if isinstance(data, dict) and data.get("result") == "error":
                    raise MatomoError(data.get("message", "Unknown error"))

                return data
        except urllib.error.URLError as e:
            raise MatomoError(f"Request failed: {e}")

    def get_api_url(self, method: str, params: dict) -> str:
        """
        Get the full API URL for a request (for documentation purposes).
        Token is redacted.
        """
        base_params = {
            "module": "API",
            "method": method,
            "format": "JSON",
            "token_auth": "[REDACTED]",
        }
        base_params.update(params)
        query = urllib.parse.urlencode(base_params)
        return f"https://{self.url}/?{query}"

    # --- High-level methods ---

    def get_sites(self) -> list[dict]:
        """Get all sites the API key has access to."""
        return self._request("SitesManager.getSitesWithAtLeastViewAccess", {})

    def get_visits(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
    ) -> dict:
        """
        Get visit summary for a site.

        Args:
            site_id: Matomo site ID
            period: day, week, month, or year
            date: today, yesterday, YYYY-MM-DD, or lastN
            segment: Optional segment filter (e.g., "pageUrl=@/gps/")

        Returns:
            Dict with nb_uniq_visitors, nb_visits, nb_actions, etc.
        """
        params = {"idSite": site_id, "period": period, "date": date}
        if segment:
            params["segment"] = segment
        return self._request("VisitsSummary.get", params)

    def get_unique_visitors(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
    ) -> int:
        """Get unique visitor count."""
        params = {"idSite": site_id, "period": period, "date": date}
        if segment:
            params["segment"] = segment
        result = self._request("VisitsSummary.getUniqueVisitors", params)
        return result.get("value", 0)

    def get_pages(
        self,
        site_id: int,
        period: str,
        date: str,
        pattern: Optional[str] = None,
        segment: Optional[str] = None,
        flat: bool = True,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get page URL statistics.

        Args:
            site_id: Matomo site ID
            period: day, week, month, or year
            date: today, yesterday, YYYY-MM-DD, or lastN
            pattern: Filter URLs containing this pattern
            segment: Optional segment filter
            flat: Flatten hierarchical results
            limit: Max rows to return

        Returns:
            List of dicts with label (URL), nb_visits, nb_hits, etc.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if pattern:
            params["filter_pattern"] = pattern
        if segment:
            params["segment"] = segment
        if flat:
            params["flat"] = 1
        return self._request("Actions.getPageUrls", params)

    def get_configured_dimensions(self, site_id: int) -> list[dict]:
        """
        Get custom dimensions configured for a site.

        Returns list of dicts with:
            - idcustomdimension: internal ID
            - index: dimension index (use this for queries)
            - scope: "visit" or "action"
            - name: human-readable name
            - active: bool
        """
        return self._request(
            "CustomDimensions.getConfiguredCustomDimensions",
            {"idSite": site_id}
        )

    def get_dimension(
        self,
        site_id: int,
        dimension_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get breakdown by custom dimension.

        Args:
            site_id: Matomo site ID
            dimension_id: The dimension index (or idcustomdimension for action-scoped)
            period: day, week, month, or year
            date: today, yesterday, YYYY-MM-DD, or lastN
            segment: Optional segment filter
            limit: Max rows to return

        Returns:
            List of dicts with label, nb_visits, nb_actions, etc.
        """
        params = {
            "idSite": site_id,
            "idDimension": dimension_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("CustomDimensions.getCustomDimension", params)

    def get_dimension_by_week(
        self,
        site_id: int,
        dimension_id: int,
        year: int,
        month: int,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, list[dict]]:
        """
        Get dimension breakdown for each week in a month.

        Useful for avoiding timeouts on large queries.

        Returns:
            Dict keyed by week start date, values are dimension breakdowns.
        """
        from datetime import date, timedelta

        # Get first day of month
        start = date(year, month, 1)

        # Get last day of month
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)

        results = {}
        current = start

        while current <= end:
            week_str = current.isoformat()
            try:
                data = self.get_dimension(
                    site_id=site_id,
                    dimension_id=dimension_id,
                    period="week",
                    date=week_str,
                    segment=segment,
                    limit=limit,
                )
                results[week_str] = data
            except MatomoError as e:
                results[week_str] = {"error": str(e)}

            current += timedelta(days=7)

        return results


class MatomoError(Exception):
    """Error from Matomo API."""
    pass


# --- Convenience functions for CLI usage ---

def load_api() -> MatomoAPI:
    """Load API client from .env in current directory or parents."""
    # Try current directory first
    if Path(".env").exists():
        return MatomoAPI()

    # Try parent directories
    cwd = Path.cwd()
    for parent in cwd.parents:
        env_path = parent / ".env"
        if env_path.exists():
            os.chdir(parent)
            api = MatomoAPI()
            os.chdir(cwd)
            return api

    raise FileNotFoundError("No .env file found in current directory or parents")


if __name__ == "__main__":
    # Quick test
    api = MatomoAPI()
    sites = api.get_sites()
    print(f"Found {len(sites)} sites:")
    for site in sites:
        print(f"  {site['idsite']}: {site['name']}")
