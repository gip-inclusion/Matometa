"""
Matomo Web UI URL generation.

Maps API methods to the correct Matomo web UI category/subcategory
and generates clickable URLs for reports.
"""

import urllib.parse
from typing import Optional


# Mapping from API methods to web UI category/subcategory
# Discovered via API.getWidgetMetadata - these are the actual Matomo IDs
UI_MAPPING = {
    # Visitors
    "VisitsSummary.get": ("General_Visitors", "General_Overview"),
    "VisitsSummary.getUniqueVisitors": ("General_Visitors", "General_Overview"),
    # Actions - Pages
    "Actions.getPageUrls": ("General_Actions", "General_Pages"),
    "Actions.getPageTitles": ("General_Actions", "Actions_SubmenuPageTitles"),
    "Actions.getEntryPageUrls": ("General_Actions", "Actions_SubmenuPagesEntry"),
    "Actions.getExitPageUrls": ("General_Actions", "Actions_SubmenuPagesExit"),
    # Custom dimensions - subcategory is "customdimension{N}" where N is dimension ID
    "CustomDimensions.getCustomDimension": ("General_Visitors", None),  # subcategory = f"customdimension{id}"
    # Events
    "Events.getCategory": ("General_Actions", "Events_Events"),
    "Events.getAction": ("General_Actions", "Events_Events"),
    "Events.getName": ("General_Actions", "Events_Events"),
    # Referrers
    "Referrers.getReferrerType": ("Referrers_Referrers", "Referrers_WidgetGetAll"),
    "Referrers.getWebsites": ("Referrers_Referrers", "Referrers_SubmenuWebsitesOnly"),
    "Referrers.getSearchEngines": ("Referrers_Referrers", "Referrers_SubmenuSearchEngines"),
    "Referrers.getSocials": ("Referrers_Referrers", "Referrers_Socials"),
    "Referrers.getAll": ("Referrers_Referrers", "Referrers_WidgetGetAll"),
    # Visit time
    "VisitTime.getVisitInformationPerServerTime": ("General_Visitors", "VisitTime_SubmenuTimes"),
    "VisitTime.getByDayOfWeek": ("General_Visitors", "VisitTime_SubmenuTimes"),
    # Transitions
    "Transitions.getTransitionsForAction": ("General_Actions", "Transitions_Transitions"),
    # Devices & Location
    "DevicesDetection.getType": ("General_Visitors", "DevicesDetection_Devices"),
    "DevicesDetection.getBrowsers": ("General_Visitors", "DevicesDetection_Software"),
    "UserCountry.getCountry": ("General_Visitors", "UserCountry_SubmenuLocations"),
    "UserCountry.getRegion": ("General_Visitors", "UserCountry_SubmenuLocations"),
    "UserCountry.getCity": ("General_Visitors", "UserCountry_SubmenuLocations"),
    # Engagement
    "VisitorInterest.getNumberOfVisitsPerVisitDuration": ("General_Actions", "VisitorInterest_Engagement"),
    "VisitorInterest.getNumberOfVisitsPerPage": ("General_Actions", "VisitorInterest_Engagement"),
    # Visit frequency (returning vs new)
    "VisitFrequency.get": ("General_Visitors", "VisitFrequency_SubmenuFrequency"),
    # Cohorts (premium plugin)
    "Cohorts.getCohorts": ("General_Visitors", "Cohorts_Cohorts"),
    "Cohorts.getCohortsOverTime": ("General_Visitors", "Cohorts_Cohorts"),
    "Cohorts.getByPeriodOfFirstVisit": ("General_Visitors", "Cohorts_Cohorts"),
}


def get_ui_url(
    base_url: str,
    method: str,
    site_id: int,
    period: str,
    date: str,
    segment: Optional[str] = None,
    dimension_id: Optional[int] = None,
) -> str:
    """
    Generate a Matomo web UI URL for a given API method.

    Args:
        base_url: Matomo instance URL (e.g., "matomo.inclusion.beta.gouv.fr")
        method: API method name (e.g., "VisitsSummary.get")
        site_id: Matomo site ID
        period: day, week, month, or year
        date: YYYY-MM-DD format
        segment: Optional segment filter
        dimension_id: Required for CustomDimensions methods

    Returns:
        Full URL to the Matomo web UI with the appropriate view.
    """
    mapping = UI_MAPPING.get(method)
    if not mapping:
        # Fallback to dashboard
        category, subcategory = "Dashboard_Dashboard", "1"
    else:
        category, subcategory = mapping
        if subcategory is None and dimension_id is not None:
            # Custom dimensions use "customdimension{N}" format
            subcategory = f"customdimension{dimension_id}"

    # Build the hash fragment with category/subcategory
    hash_params = {
        "category": category,
        "subcategory": subcategory or "1",
    }
    if segment:
        hash_params["segment"] = segment

    # Use safe='@=;' to avoid over-encoding segment operators
    hash_fragment = urllib.parse.urlencode(hash_params, safe='@=;,')

    # Build the main URL
    main_params = {
        "module": "CoreHome",
        "action": "index",
        "idSite": site_id,
        "period": period,
        "date": date,
    }
    main_query = urllib.parse.urlencode(main_params)

    return f"https://{base_url}/index.php?{main_query}#?{hash_fragment}"


def format_data_source(
    base_url: str,
    method: str,
    params: dict,
    dimension_id: Optional[int] = None,
) -> str:
    """
    Format a data source reference for reports.

    Returns a markdown string with:
    - A hyperlink to the web UI
    - The raw API call for reproducibility

    Args:
        base_url: Matomo instance URL
        method: API method name
        params: Dict with idSite, period, date, and optionally segment
        dimension_id: For custom dimension queries

    Returns:
        Markdown-formatted data source string.
    """
    site_id = params.get("idSite")
    period = params.get("period")
    date = params.get("date")
    segment = params.get("segment")

    # Generate web UI link
    ui_url = get_ui_url(
        base_url=base_url,
        method=method,
        site_id=site_id,
        period=period,
        date=date,
        segment=segment,
        dimension_id=dimension_id,
    )

    # Generate raw API call (without token)
    api_params = {"idSite": site_id, "period": period, "date": date}
    if segment:
        api_params["segment"] = segment
    if dimension_id:
        api_params["idDimension"] = dimension_id

    api_call = f"{method}?" + "&".join(f"{k}={v}" for k, v in api_params.items())

    return f"[View in Matomo]({ui_url}) | `{api_call}`"
