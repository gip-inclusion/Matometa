"""
Matomo API client for Matometa.

Usage:
    from scripts.matomo import MatomoAPI

    api = MatomoAPI()  # loads from .env
    summary = api.get_visits(site_id=117, period="month", date="2025-12-01")

    # For any Matomo API method, use request() with **kwargs:
    events = api.request("Events.getName", idSite=211, period="month", date="2025-12-01")
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

    def request(self, method: str, timeout: int = 180, **params) -> Any:
        """
        Make a raw API request to any Matomo method.

        Use this when high-level methods don't expose the parameters you need,
        or for API methods not wrapped by this client.

        Args:
            method: Matomo API method (e.g., "Events.getName", "VisitsSummary.get")
            timeout: Request timeout in seconds (default 180)
            **params: Any parameters to pass to the API (idSite, period, date, etc.)

        Returns:
            API response (typically list or dict)

        Example:
            api.request("Events.getName", idSite=211, period="month", date="2025-12-01",
                        secondaryDimension="eventCategory", flat=1)
        """
        return self._request(method, params, timeout)

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

    # --- Events ---

    def get_event_categories(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get event categories with counts.

        Returns list of dicts with label (category name), nb_events, nb_visits, etc.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("Events.getCategory", params)

    def get_event_actions(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get event actions with counts.

        Returns list of dicts with label (action name), nb_events, nb_visits, etc.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("Events.getAction", params)

    def get_event_names(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get event names with counts.

        Returns list of dicts with label (event name), nb_events, nb_visits, etc.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("Events.getName", params)

    # --- Entry/Exit pages ---

    def get_entry_pages(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        flat: bool = True,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get landing pages (first page of visits).

        Returns list of dicts with label (URL), entry_nb_visits, entry_bounce_count, etc.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        if flat:
            params["flat"] = 1
        return self._request("Actions.getEntryPageUrls", params)

    def get_exit_pages(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        flat: bool = True,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get exit pages (last page of visits).

        Returns list of dicts with label (URL), exit_nb_visits, exit_rate, etc.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        if flat:
            params["flat"] = 1
        return self._request("Actions.getExitPageUrls", params)

    # --- Transitions (page flow) ---

    def get_transitions(
        self,
        site_id: int,
        period: str,
        date: str,
        page_url: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> dict:
        """
        Get page flow: what pages users visited before and after a specific URL.

        Args:
            page_url: The page URL to analyze (e.g., "/gps/groups/list")

        Returns:
            Dict with:
            - previousPages: list of pages visited before
            - followingPages: list of pages visited after
            - referrers: external sources leading to this page
            - outlinks: external links clicked from this page
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "actionType": "url",
            "actionName": page_url,
            "limitBeforeGrouping": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("Transitions.getTransitionsForAction", params)

    # --- Visit time patterns ---

    def get_visits_by_hour(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
    ) -> list[dict]:
        """
        Get visit distribution by hour of day (server time).

        Returns list of 24 dicts (one per hour) with nb_visits, nb_uniq_visitors, etc.
        """
        params = {"idSite": site_id, "period": period, "date": date}
        if segment:
            params["segment"] = segment
        return self._request("VisitTime.getVisitInformationPerServerTime", params)

    def get_visits_by_day_of_week(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
    ) -> list[dict]:
        """
        Get visit distribution by day of week.

        Returns list of 7 dicts (Monday=1 to Sunday=7) with nb_visits, etc.
        """
        params = {"idSite": site_id, "period": period, "date": date}
        if segment:
            params["segment"] = segment
        return self._request("VisitTime.getByDayOfWeek", params)

    # --- Referrers ---

    def get_referrers(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get all referrer types with visit counts.

        Returns list of dicts with label (referrer type), nb_visits, nb_actions, etc.
        Types include: Direct Entry, Search Engines, Websites, Social Networks, Campaigns.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("Referrers.getReferrerType", params)

    def get_referrer_websites(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get referring websites with visit counts.

        Returns list of dicts with label (website URL), nb_visits, nb_actions, etc.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("Referrers.getWebsites", params)

    def get_referrer_search_engines(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get search engines with visit counts.

        Returns list of dicts with label (search engine name), nb_visits, etc.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("Referrers.getSearchEngines", params)

    def get_referrer_socials(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get social networks with visit counts.

        Returns list of dicts with label (social network name), nb_visits, etc.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("Referrers.getSocials", params)

    # --- Visit frequency (returning visitors) ---

    def get_visit_frequency(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
    ) -> dict:
        """
        Get metrics for returning visitors vs new visitors.

        Returns dict with metrics prefixed by visitor type:
        - nb_visits_returning, nb_actions_returning, avg_time_on_site_returning, ...
        - nb_visits_new, nb_actions_new, bounce_rate_new, ...

        Useful for comparing engagement between new and returning visitors.
        """
        params = {"idSite": site_id, "period": period, "date": date}
        if segment:
            params["segment"] = segment
        return self._request("VisitFrequency.get", params)

    # --- Cohorts (premium plugin) ---

    def get_cohorts(
        self,
        site_id: int,
        period: str,
        date: str,
        metric: Optional[str] = None,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get cohort analysis data.

        A cohort is a group of visitors whose first visit was within a specific period.
        Returns metrics for each cohort for periods after the cohort's first visit.

        Args:
            site_id: Matomo site ID
            period: day, week, month, or year
            date: Date or range (e.g., "2025-12-01" or "last30")
            metric: Specific metric to return (optional)
            segment: Optional segment filter
            limit: Max cohorts to return

        Returns:
            List of cohort data with metrics by period.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if metric:
            params["metric"] = metric
        if segment:
            params["segment"] = segment
        return self._request("Cohorts.getCohorts", params)

    def get_cohorts_over_time(
        self,
        site_id: int,
        period: str,
        display_date_range: str,
        cohorts: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> Any:
        """
        Get cohort metrics evolution over time.

        Args:
            site_id: Matomo site ID
            period: day, week, month, or year
            display_date_range: Date range to display
            cohorts: Cohort specification
            segment: Optional segment filter
            limit: Max rows to return

        Returns:
            Cohort evolution data for graphing.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "displayDateRange": display_date_range,
            "cohorts": cohorts,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("Cohorts.getCohortsOverTime", params)

    def get_cohorts_by_first_visit(
        self,
        site_id: int,
        period: str,
        cohorts: str,
        segment: Optional[str] = None,
        periods_from_start: Optional[str] = None,
    ) -> Any:
        """
        Get cohorts grouped by period of first visit.

        Args:
            site_id: Matomo site ID
            period: day, week, month, or year
            cohorts: Cohort specification
            segment: Optional segment filter
            periods_from_start: Number of periods from cohort start

        Returns:
            Cohort data grouped by first visit period.
        """
        params = {
            "idSite": site_id,
            "period": period,
            "cohorts": cohorts,
        }
        if segment:
            params["segment"] = segment
        if periods_from_start:
            params["periodsFromStart"] = periods_from_start
        return self._request("Cohorts.getByPeriodOfFirstVisit", params)


class MatomoError(Exception):
    """Error from Matomo API."""
    pass


# --- Web UI URL generation (re-exported from ui_mapping) ---

from .ui_mapping import UI_MAPPING, get_ui_url, format_data_source


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
