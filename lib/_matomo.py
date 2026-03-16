"""
Matomo API client with automatic audit logging.

Usage:
    from lib.query import MatomoAPI

    api = MatomoAPI(url="matomo.example.com", token="...")
    summary = api.get_visits(site_id=117, period="month", date="2025-12-01")
"""

import logging
import urllib.parse
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ._matomo_ui import get_ui_url
from .api_signals import emit_api_signal

logger = logging.getLogger(__name__)


class MatomoError(Exception):
    """Error from Matomo API."""

    pass


class MatomoAPI:
    """
    Client for querying the Matomo API.

    Uses requests.Session for connection pooling (reuses TCP+TLS across calls).
    Retries up to 2 times on 429/5xx errors with exponential backoff via
    urllib3.util.retry.Retry. All queries are logged to the audit database.

    Worst-case for a fully-failing request: ~9 min (3 attempts x ~180s read
    timeout + backoff). Pass a lower timeout if tighter bounds are needed.
    """

    def __init__(
        self,
        url: str,
        token: str,
        instance: str = "inclusion",
        caller: str = "agent",
    ):
        self.url = url
        self.token = token
        self.instance = instance
        self.caller = caller

        self._session = requests.Session()
        retry = Retry(
            total=2,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            respect_retry_after_header=True,
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._session.mount("http://", HTTPAdapter(max_retries=retry))

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _request(self, method: str, params: dict, timeout: int = 180) -> Any:
        """Make an API request."""
        base_params = {
            "module": "API",
            "method": method,
            "format": "JSON",
            "token_auth": self.token,
        }
        base_params.update(params)

        url = f"https://{self.url}/"

        try:
            resp = self._session.get(url, params=base_params, timeout=(10, timeout))
            resp.raise_for_status()

            # Matomo returns HTML instead of JSON on server-side timeouts.
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" in content_type or resp.text.lstrip().startswith("<!DOCTYPE"):
                raise MatomoError(
                    f"Matomo returned HTML instead of JSON (likely server-side timeout). "
                    f"Response starts with: {resp.text[:200]}"
                )

            data = resp.json()

            if isinstance(data, dict) and data.get("result") == "error":
                raise MatomoError(data.get("message", "Unknown error"))

            # Emit signal for observability sidebar
            ui_url = None
            if get_ui_url and all(k in params for k in ("idSite", "period", "date")):
                ui_url = get_ui_url(
                    base_url=self.url,
                    method=method,
                    site_id=params["idSite"],
                    period=params["period"],
                    date=params["date"],
                    segment=params.get("segment"),
                    dimension_id=params.get("idDimension"),
                )
            emit_api_signal(
                source="matomo",
                instance=self.instance,
                method=method,
                url=ui_url or self.get_api_url(method, params),
            )

            return data

        except MatomoError:
            raise

        except requests.RequestException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            body = getattr(getattr(e, "response", None), "text", str(e))
            error_msg = f"HTTP {status}: {body}" if status else str(e)
            raise MatomoError(f"Request failed: {error_msg}")

    def request(self, method: str, timeout: int = 180, **params) -> Any:
        """
        Make a raw API request to any Matomo method.

        Args:
            method: Matomo API method (e.g., "Events.getName", "VisitsSummary.get")
            timeout: Request timeout in seconds (default 180)
            **params: Any parameters to pass to the API (idSite, period, date, etc.)

        Returns:
            API response (typically list or dict)
        """
        return self._request(method, params, timeout)

    def get_api_url(self, method: str, params: dict) -> str:
        """Get the full API URL for a request (token redacted)."""
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
            segment: Optional segment filter

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
        """Get page URL statistics."""
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
        """Get custom dimensions configured for a site."""
        return self._request("CustomDimensions.getConfiguredCustomDimensions", {"idSite": site_id})

    def get_dimension(
        self,
        site_id: int,
        dimension_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get breakdown by custom dimension."""
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

    def get_event_categories(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get event categories with counts."""
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
        """Get event actions with counts."""
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
        """Get event names with counts."""
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("Events.getName", params)

    def get_entry_pages(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        flat: bool = True,
        limit: int = 100,
    ) -> list[dict]:
        """Get landing pages (first page of visits)."""
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
        """Get exit pages (last page of visits)."""
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

    def get_transitions(
        self,
        site_id: int,
        period: str,
        date: str,
        page_url: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> dict:
        """Get page flow: what pages users visited before and after a URL."""
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

    def get_visits_by_hour(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
    ) -> list[dict]:
        """Get visit distribution by hour of day."""
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
        """Get visit distribution by day of week."""
        params = {"idSite": site_id, "period": period, "date": date}
        if segment:
            params["segment"] = segment
        return self._request("VisitTime.getByDayOfWeek", params)

    def get_referrers(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get all referrer types with visit counts."""
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
        """Get referring websites with visit counts."""
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
        """Get search engines with visit counts."""
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
        """Get social networks with visit counts."""
        params = {
            "idSite": site_id,
            "period": period,
            "date": date,
            "filter_limit": limit,
        }
        if segment:
            params["segment"] = segment
        return self._request("Referrers.getSocials", params)

    def get_visit_frequency(
        self,
        site_id: int,
        period: str,
        date: str,
        segment: Optional[str] = None,
    ) -> dict:
        """Get metrics for returning visitors vs new visitors."""
        params = {"idSite": site_id, "period": period, "date": date}
        if segment:
            params["segment"] = segment
        return self._request("VisitFrequency.get", params)
