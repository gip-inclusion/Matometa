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

# Tag Manager validation constants
VALID_TRIGGER_TYPES = {
    "AllElementsClick",
    "AllLinksClick",
    "PageView",
    "FormSubmit",
    "HistoryChange",
    "WindowLoaded",
    "ElementVisibility",
    "CustomEvent",
}

VALID_TAG_TYPES = {
    "CustomHtml",
    "Matomo",
    "LinkedinInsight",
}

VALID_FIRE_LIMITS = {
    "unlimited",
    "once_page",
    "once_24hours",
    "once_lifetime",
}

VALID_HTML_POSITIONS = {
    "headStart",
    "headEnd",
    "bodyStart",
    "bodyEnd",
}

VALID_ENVIRONMENTS = {
    "live",
    "staging",
    "dev",
    "production",
    "pentest",
    "preview",
}

VALID_COMPARISONS = {
    "equals",
    "equals_exactly",
    "contains",
    "starts_with",
    "ends_with",
    "matches_regex",
    "is_not_equal",
    "does_not_contain",
    "not_contains",
    "match_css_selector",
}


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

    def _request(self, method: str, params: dict, timeout: int = 180, http_method: str = "GET") -> Any:
        """Make an API request."""
        base_params = {
            "module": "API",
            "method": method,
            "format": "JSON",
            "token_auth": self.token,
        }
        url = f"https://{self.url}/"

        try:
            # Choose HTTP method and prepare parameters
            if http_method == "POST":
                # POST: flatten nested params and use data= (form-encoded)
                flattened = self._flatten_params(params)
                base_params.update(flattened)
                resp = self._session.post(url, data=base_params, timeout=(10, timeout))
            else:
                # GET: use params= (query string)
                base_params.update(params)
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

    def post(self, method: str, timeout: int = 30, **params) -> Any:
        """
        Generic POST for any Tag Manager write operation.

        Args:
            method: Matomo API method (e.g., "TagManager.addContainerTrigger")
            timeout: Request timeout in seconds (default 30, lower than GET)
            **params: Parameters to pass (nested dicts/lists auto-flattened)

        Returns:
            API response (typically {"value": id} for creates)

        Example:
            >>> api.post("TagManager.addContainerTrigger",
            ...     idSite=210,
            ...     idContainer="xg8aydM9",
            ...     idContainerVersion=420,
            ...     type="AllElementsClick",
            ...     name="My Trigger",
            ...     conditions=[
            ...         {"comparison": "contains", "actual": "ClickClasses", "expected": "btn"}
            ...     ]
            ... )
            {'value': 13994}
        """
        return self._request(method, params, timeout, http_method="POST")

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

    def _flatten_params(self, params: dict, prefix: str = "") -> dict:
        """
        Flatten nested dicts/lists to PHP array notation.

        PHP array notation is required for POST requests to Matomo API.
        Converts Python data structures to the format Matomo expects.

        Args:
            params: Parameters to flatten (can contain nested dicts/lists)
            prefix: Internal - used for recursion to build key paths

        Returns:
            Flattened dict with PHP array notation keys

        Examples:
            >>> api._flatten_params({"customHtml": "<script></script>"})
            {'customHtml': '<script></script>'}

            >>> api._flatten_params({"parameters": {"customHtml": "..."}})
            {'parameters[customHtml]': '...'}

            >>> api._flatten_params({"conditions": [{"comparison": "equals"}]})
            {'conditions[0][comparison]': 'equals'}
        """
        result = {}
        for key, value in params.items():
            new_key = f"{prefix}[{key}]" if prefix else key

            if isinstance(value, dict):
                # Recursively flatten nested dicts
                result.update(self._flatten_params(value, new_key))
            elif isinstance(value, list):
                # Flatten lists: indexed for dicts, direct for simple values
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        result.update(self._flatten_params(item, f"{new_key}[{i}]"))
                    else:
                        result[f"{new_key}[{i}]"] = item
            else:
                # Leaf value - add to result
                result[new_key] = value

        return result

    # --- Tag Manager: Container operations ---

    def get_container(self, site_id: int, container_id: str) -> dict:
        """
        Get container details including draft version and releases.

        Args:
            site_id: Matomo site ID
            container_id: Container ID (e.g., "xg8aydM9")

        Returns:
            Container dict with draft and releases information

        Example:
            >>> container = api.get_container(site_id=210, container_id="xg8aydM9")
            >>> draft_id = container["draft"]["idcontainerversion"]
            >>> for rel in container["releases"]:
            ...     print(f"{rel['environment']} → v{rel['idcontainerversion']}")
        """
        return self._request("TagManager.getContainer", {"idSite": site_id, "idContainer": container_id})

    def get_draft_version(self, site_id: int, container_id: str) -> int:
        """
        Get current draft version ID (convenience method).

        Args:
            site_id: Matomo site ID
            container_id: Container ID

        Returns:
            Draft version ID (int)

        Example:
            >>> draft_id = api.get_draft_version(site_id=210, container_id="xg8aydM9")
            >>> print(f"Draft version: {draft_id}")
        """
        container = self.get_container(site_id, container_id)
        return container["draft"]["idcontainerversion"]

    # --- Tag Manager: Trigger operations ---

    def add_trigger(
        self,
        site_id: int,
        container_id: str,
        version_id: int,
        trigger_type: str,
        name: str,
        conditions: list[dict],
        description: str = "",
        **kwargs,
    ) -> int:
        """
        Add trigger to container version.

        Args:
            site_id: Matomo site ID
            container_id: Container ID
            version_id: Version ID (typically draft)
            trigger_type: Type of trigger (validated against VALID_TRIGGER_TYPES)
            name: Trigger name
            conditions: List of condition dicts with comparison/actual/expected
            description: Optional description
            **kwargs: Additional parameters passed to API

        Returns:
            Trigger ID (int)

        Raises:
            ValueError: If trigger_type is invalid

        Example:
            >>> trigger_id = api.add_trigger(
            ...     site_id=210,
            ...     container_id="xg8aydM9",
            ...     version_id=420,
            ...     trigger_type="PageView",
            ...     name="Service Page View",
            ...     conditions=[
            ...         {"comparison": "starts_with", "actual": "PageUrl",
            ...          "expected": "/services/"}
            ...     ]
            ... )
        """
        if trigger_type not in VALID_TRIGGER_TYPES:
            raise ValueError(
                f"Invalid trigger_type '{trigger_type}'. Must be one of: {', '.join(sorted(VALID_TRIGGER_TYPES))}"
            )

        params = {
            "idSite": site_id,
            "idContainer": container_id,
            "idContainerVersion": version_id,
            "type": trigger_type,
            "name": name,
            "conditions": conditions,
        }
        if description:
            params["description"] = description
        params.update(kwargs)

        result = self.post("TagManager.addContainerTrigger", **params)
        return result["value"]

    def update_trigger(
        self,
        site_id: int,
        container_id: str,
        version_id: int,
        trigger_id: int,
        **kwargs,
    ):
        """
        Update existing trigger.

        Args:
            site_id: Matomo site ID
            container_id: Container ID
            version_id: Version ID
            trigger_id: Trigger ID to update
            **kwargs: Fields to update (name, conditions, etc.)

        Example:
            >>> api.update_trigger(
            ...     site_id=210,
            ...     container_id="xg8aydM9",
            ...     version_id=420,
            ...     trigger_id=13994,
            ...     name="Updated Trigger Name"
            ... )
        """
        params = {
            "idSite": site_id,
            "idContainer": container_id,
            "idContainerVersion": version_id,
            "idTrigger": trigger_id,
        }
        params.update(kwargs)
        return self.post("TagManager.updateContainerTrigger", **params)

    def delete_trigger(
        self,
        site_id: int,
        container_id: str,
        version_id: int,
        trigger_id: int,
    ):
        """
        Delete trigger from container version.

        Args:
            site_id: Matomo site ID
            container_id: Container ID
            version_id: Version ID
            trigger_id: Trigger ID to delete

        Note:
            Deleting from draft doesn't remove from published versions.
            Delete from both if needed.

        Example:
            >>> api.delete_trigger(
            ...     site_id=210,
            ...     container_id="xg8aydM9",
            ...     version_id=420,
            ...     trigger_id=13994
            ... )
        """
        return self.post(
            "TagManager.deleteContainerTrigger",
            idSite=site_id,
            idContainer=container_id,
            idContainerVersion=version_id,
            idTrigger=trigger_id,
        )

    # --- Tag Manager: Tag operations ---

    def add_tag(
        self,
        site_id: int,
        container_id: str,
        version_id: int,
        tag_type: str,
        name: str,
        parameters: dict,
        fire_trigger_ids: list[int],
        fire_limit: str = "unlimited",
        status: str = "active",
        priority: int = 999,
        description: str = "",
        **kwargs,
    ) -> int:
        """
        Add tag to container version.

        Args:
            site_id: Matomo site ID
            container_id: Container ID
            version_id: Version ID (typically draft)
            tag_type: Type of tag (validated against VALID_TAG_TYPES)
            name: Tag name
            parameters: Tag-specific parameters (e.g., customHtml, htmlPosition)
            fire_trigger_ids: List of trigger IDs that fire this tag
            fire_limit: How often tag fires (validated against VALID_FIRE_LIMITS)
            status: Tag status (active or paused)
            priority: Execution priority (999 = standard)
            description: Optional description
            **kwargs: Additional parameters (block_trigger_ids, etc.)

        Returns:
            Tag ID (int)

        Raises:
            ValueError: If tag_type, fire_limit, or htmlPosition (for CustomHtml) is invalid

        Example:
            >>> tag_id = api.add_tag(
            ...     site_id=210,
            ...     container_id="xg8aydM9",
            ...     version_id=420,
            ...     tag_type="CustomHtml",
            ...     name="Tally Popup",
            ...     parameters={"customHtml": "<script>...</script>", "htmlPosition": "bodyEnd"},
            ...     fire_trigger_ids=[13994],
            ...     fire_limit="once_24hours"
            ... )
        """
        if tag_type not in VALID_TAG_TYPES:
            raise ValueError(f"Invalid tag_type '{tag_type}'. Must be one of: {', '.join(sorted(VALID_TAG_TYPES))}")

        if fire_limit not in VALID_FIRE_LIMITS:
            raise ValueError(
                f"Invalid fire_limit '{fire_limit}'. Must be one of: {', '.join(sorted(VALID_FIRE_LIMITS))}"
            )

        # Validate htmlPosition for CustomHtml tags
        if tag_type == "CustomHtml" and "htmlPosition" in parameters:
            html_position = parameters["htmlPosition"]
            if html_position not in VALID_HTML_POSITIONS:
                raise ValueError(
                    f"Invalid htmlPosition '{html_position}'. Must be one of: {', '.join(sorted(VALID_HTML_POSITIONS))}"
                )

        params = {
            "idSite": site_id,
            "idContainer": container_id,
            "idContainerVersion": version_id,
            "type": tag_type,
            "name": name,
            "parameters": parameters,
            "fireTriggerIds": fire_trigger_ids,
            "fireLimit": fire_limit,
            "status": status,
            "priority": priority,
        }
        if description:
            params["description"] = description
        params.update(kwargs)

        result = self.post("TagManager.addContainerTag", **params)
        return result["value"]

    def update_tag(
        self,
        site_id: int,
        container_id: str,
        version_id: int,
        tag_id: int,
        **kwargs,
    ):
        """
        Update existing tag.

        Args:
            site_id: Matomo site ID
            container_id: Container ID
            version_id: Version ID
            tag_id: Tag ID to update
            **kwargs: Fields to update (name, parameters, fire_trigger_ids, etc.)

        Example:
            >>> api.update_tag(
            ...     site_id=210,
            ...     container_id="xg8aydM9",
            ...     version_id=420,
            ...     tag_id=11149,
            ...     name="Updated Tag Name",
            ...     fire_limit="once_page"
            ... )
        """
        params = {
            "idSite": site_id,
            "idContainer": container_id,
            "idContainerVersion": version_id,
            "idTag": tag_id,
        }
        params.update(kwargs)
        return self.post("TagManager.updateContainerTag", **params)

    def delete_tag(
        self,
        site_id: int,
        container_id: str,
        version_id: int,
        tag_id: int,
    ):
        """
        Delete tag from container version.

        Args:
            site_id: Matomo site ID
            container_id: Container ID
            version_id: Version ID
            tag_id: Tag ID to delete

        Note:
            Deleting from draft doesn't remove from published versions.

        Example:
            >>> api.delete_tag(210, "xg8aydM9", 420, 11149)
        """
        return self.post(
            "TagManager.deleteContainerTag",
            idSite=site_id,
            idContainer=container_id,
            idContainerVersion=version_id,
            idTag=tag_id,
        )

    def pause_tag(
        self,
        site_id: int,
        container_id: str,
        version_id: int,
        tag_id: int,
    ):
        """
        Pause tag (set status=paused).

        Args:
            site_id: Matomo site ID
            container_id: Container ID
            version_id: Version ID
            tag_id: Tag ID to pause

        Example:
            >>> api.pause_tag(210, "xg8aydM9", 420, 11149)
        """
        return self.post(
            "TagManager.pauseContainerTag",
            idSite=site_id,
            idContainer=container_id,
            idContainerVersion=version_id,
            idTag=tag_id,
        )

    def resume_tag(
        self,
        site_id: int,
        container_id: str,
        version_id: int,
        tag_id: int,
    ):
        """
        Resume tag (set status=active).

        Args:
            site_id: Matomo site ID
            container_id: Container ID
            version_id: Version ID
            tag_id: Tag ID to resume

        Example:
            >>> api.resume_tag(210, "xg8aydM9", 420, 11149)
        """
        return self.post(
            "TagManager.resumeContainerTag",
            idSite=site_id,
            idContainer=container_id,
            idContainerVersion=version_id,
            idTag=tag_id,
        )

    # --- Tag Manager: Workflow operations ---

    def publish_version(
        self,
        site_id: int,
        container_id: str,
        version_id: int,
        environment: str,
    ):
        """
        Publish container version to environment.

        Creates a new numbered version from the draft and deploys it.
        Note: IDs of triggers/tags change in the published version.

        Args:
            site_id: Matomo site ID
            container_id: Container ID
            version_id: Version ID to publish (typically draft)
            environment: Target environment (validated against VALID_ENVIRONMENTS)

        Raises:
            ValueError: If environment is invalid

        Example:
            >>> api.publish_version(
            ...     site_id=210,
            ...     container_id="xg8aydM9",
            ...     version_id=420,
            ...     environment="live"
            ... )
        """
        if environment not in VALID_ENVIRONMENTS:
            raise ValueError(
                f"Invalid environment '{environment}'. Must be one of: {', '.join(sorted(VALID_ENVIRONMENTS))}"
            )

        return self.post(
            "TagManager.publishContainerVersion",
            idSite=site_id,
            idContainer=container_id,
            idContainerVersion=version_id,
            environment=environment,
        )

    def enable_preview(
        self,
        site_id: int,
        container_id: str,
        version_id: Optional[int] = None,
    ):
        """
        Enable preview mode for testing draft without publishing.

        Sets a cookie in the browser to load draft version.

        Args:
            site_id: Matomo site ID
            container_id: Container ID
            version_id: Optional version to preview (defaults to current draft)

        Example:
            >>> api.enable_preview(site_id=210, container_id="xg8aydM9")
            >>> # Now visit the site in your browser to test
        """
        params = {"idSite": site_id, "idContainer": container_id}
        if version_id is not None:
            params["idContainerVersion"] = version_id
        return self.post("TagManager.enablePreviewMode", **params)

    def disable_preview(self, site_id: int, container_id: str):
        """
        Disable preview mode.

        Args:
            site_id: Matomo site ID
            container_id: Container ID

        Example:
            >>> api.disable_preview(site_id=210, container_id="xg8aydM9")
        """
        return self.post(
            "TagManager.disablePreviewMode",
            idSite=site_id,
            idContainer=container_id,
        )

    def export_version(
        self,
        site_id: int,
        container_id: str,
        version_id: int,
    ) -> dict:
        """
        Export container version (for debugging/analysis).

        Returns full container data including all triggers, tags, variables.

        Args:
            site_id: Matomo site ID
            container_id: Container ID
            version_id: Version ID to export

        Returns:
            Dict with triggers, tags, variables lists

        Example:
            >>> data = api.export_version(210, "xg8aydM9", 972)
            >>> print(f"Found {len(data['triggers'])} triggers")
        """
        return self._request(
            "TagManager.exportContainerVersion",
            {"idSite": site_id, "idContainer": container_id, "idContainerVersion": version_id},
        )
