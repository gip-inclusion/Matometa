#!/usr/bin/env python3
"""
Sync knowledge base with fresh Matomo data.

Usage:
    python -m skills.setup_knowledge_sync.scripts.sync_sites
    python -m skills.setup_knowledge_sync.scripts.sync_sites --baselines-only
    python -m skills.setup_knowledge_sync.scripts.sync_sites --site emplois
    python -m skills.setup_knowledge_sync.scripts.sync_sites --dry-run
"""

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.matomo import MatomoAPI, MatomoError


# =============================================================================
# Matomo Data Fetching (extended)
# =============================================================================

def fetch_custom_dimensions(api: MatomoAPI, site_id: int) -> list[dict]:
    """Fetch configured custom dimensions for a site."""
    try:
        dims = api.get_configured_dimensions(site_id)
        return [
            {
                "id": d.get("idcustomdimension"),
                "name": d.get("name"),
                "scope": d.get("scope"),
                "active": d.get("active"),
            }
            for d in dims
        ]
    except MatomoError:
        return []


def fetch_saved_segments(api: MatomoAPI, site_id: int) -> list[dict]:
    """Fetch saved segments for a site."""
    try:
        segments = api._request("SegmentEditor.getAll", {"idSite": site_id})
        if not isinstance(segments, list):
            return []
        return [
            {
                "name": s.get("name"),
                "definition": s.get("definition"),
                "auto_archive": s.get("auto_archive"),
            }
            for s in segments
        ]
    except MatomoError:
        return []


def fetch_event_categories(api: MatomoAPI, site_id: int, period: str, date: str) -> list[dict]:
    """Fetch event categories with counts."""
    try:
        events = api.get_event_categories(site_id, period, date, limit=50)
        return [
            {
                "category": e.get("label"),
                "events": e.get("nb_events", 0),
                "visits": e.get("nb_visits", 0),
            }
            for e in events
        ]
    except MatomoError:
        return []


def fetch_event_names(api: MatomoAPI, site_id: int, period: str, date: str) -> list[dict]:
    """Fetch all event names with counts (direct, no drilling needed)."""
    try:
        events = api.get_event_names(site_id, period, date, limit=200)
        return [
            {
                "name": e.get("label"),
                "events": e.get("nb_events", 0),
                "visits": e.get("nb_visits", 0),
            }
            for e in events
        ]
    except MatomoError:
        return []


# =============================================================================
# Site Configuration
# =============================================================================

@dataclass
class SiteConfig:
    """Configuration for a tracked site."""
    name: str
    matomo_id: int
    doc_path: str
    github: Optional[str] = None
    url: Optional[str] = None
    # Custom dimensions (if any)
    user_kind_dimension: Optional[int] = None  # dimension ID for user type


SITES = {
    "emplois": SiteConfig(
        name="Emplois",
        matomo_id=117,
        doc_path="knowledge/sites/emplois.md",
        url="https://emplois.inclusion.beta.gouv.fr",
        github="https://github.com/gip-inclusion/les-emplois",
        user_kind_dimension=1,
    ),
    "pilotage": SiteConfig(
        name="Pilotage",
        matomo_id=146,
        doc_path="knowledge/sites/pilotage.md",
        url="https://pilotage.inclusion.gouv.fr",
        github="https://github.com/gip-inclusion/pilotage",
    ),
    "communaute": SiteConfig(
        name="Communaute",
        matomo_id=206,
        doc_path="knowledge/sites/communaute.md",
        url="https://communaute.inclusion.gouv.fr",
        github="https://github.com/gip-inclusion/la-communaute",
    ),
    "dora": SiteConfig(
        name="Dora",
        matomo_id=211,
        doc_path="knowledge/sites/dora.md",
        url="https://dora.inclusion.beta.gouv.fr",
        github="https://github.com/gip-inclusion/dora",
    ),
    "plateforme": SiteConfig(
        name="Plateforme",
        matomo_id=212,
        doc_path="knowledge/sites/plateforme.md",
        url="https://inclusion.beta.gouv.fr",
        github="https://github.com/gip-inclusion/inclusion-website",
    ),
    "rdv-insertion": SiteConfig(
        name="RDV Insertion",
        matomo_id=214,
        doc_path="knowledge/sites/rdv-insertion.md",
        url="https://rdv-insertion.fr",
        github="https://github.com/betagouv/rdv-insertion",
    ),
    "mon-recap": SiteConfig(
        name="Mon Recap",
        matomo_id=217,
        doc_path="knowledge/sites/mon-recap.md",
        url="https://mon-recap.inclusion.beta.gouv.fr",
    ),
    "marche": SiteConfig(
        name="Marche",
        matomo_id=136,
        doc_path="knowledge/sites/marche.md",
        url="https://lemarche.inclusion.beta.gouv.fr",
        github="https://github.com/gip-inclusion/le-marche-django",
    ),
}


# =============================================================================
# Data Fetching
# =============================================================================

def get_months_for_year(year: int) -> list[str]:
    """Get list of month dates for a year (YYYY-MM-01 format)."""
    today = date.today()
    months = []
    for month in range(1, 13):
        d = date(year, month, 1)
        # Don't include future months
        if d <= today:
            months.append(d.strftime("%Y-%m-%d"))
    return months


def fetch_baselines(api: MatomoAPI, site: SiteConfig, year: int = 2025) -> dict:
    """
    Fetch baseline traffic data for a site.

    Returns dict with:
        - monthly_stats: list of {month, visitors, visits, daily_avg_visitors, daily_avg_visits}
        - user_types: dict of month -> {type: visits} (if dimension configured)
        - engagement: list of {month, bounce_rate, actions_per_visit, avg_time}
    """
    months = get_months_for_year(year)

    monthly_stats = []
    user_types = {}
    engagement = []

    for month_date in months:
        month_label = month_date[:7]  # YYYY-MM

        try:
            # Get visit summary
            summary = api.get_visits(
                site_id=site.matomo_id,
                period="month",
                date=month_date,
            )

            visitors = summary.get("nb_uniq_visitors", 0)
            visits = summary.get("nb_visits", 0)

            # Treat 0 as missing data (Matomo returns 0 for no-data months)
            if visitors == 0 and visits == 0:
                monthly_stats.append({
                    "month": month_label,
                    "visitors": None,
                    "visits": None,
                    "daily_avg_visitors": None,
                    "daily_avg_visits": None,
                })
                engagement.append({
                    "month": month_label,
                    "bounce_rate": "-",
                    "actions_per_visit": None,
                    "avg_time": None,
                })
                continue

            # Calculate days in month
            year_m = int(month_date[:4])
            month_m = int(month_date[5:7])
            if month_m == 12:
                days = (date(year_m + 1, 1, 1) - date(year_m, month_m, 1)).days
            else:
                days = (date(year_m, month_m + 1, 1) - date(year_m, month_m, 1)).days

            monthly_stats.append({
                "month": month_label,
                "visitors": visitors,
                "visits": visits,
                "daily_avg_visitors": round(visitors / days) if days else 0,
                "daily_avg_visits": round(visits / days) if days else 0,
            })

            # Engagement metrics
            bounce_rate = summary.get("bounce_rate", "0%")
            actions = summary.get("nb_actions_per_visit", 0)
            avg_time = summary.get("avg_time_on_site", 0)

            engagement.append({
                "month": month_label,
                "bounce_rate": bounce_rate,
                "actions_per_visit": round(actions, 1) if actions else 0,
                "avg_time": int(avg_time) if avg_time else 0,
            })

            # User types (if dimension configured)
            if site.user_kind_dimension:
                try:
                    kinds = api.get_dimension(
                        site_id=site.matomo_id,
                        dimension_id=site.user_kind_dimension,
                        period="month",
                        date=month_date,
                    )
                    user_types[month_label] = {
                        k.get("label", "unknown"): k.get("nb_visits", 0)
                        for k in kinds
                    }
                except MatomoError:
                    pass

        except MatomoError as e:
            print(f"   Warning: Could not fetch {month_label}: {e}")
            monthly_stats.append({
                "month": month_label,
                "visitors": None,
                "visits": None,
                "daily_avg_visitors": None,
                "daily_avg_visits": None,
            })

    return {
        "monthly_stats": monthly_stats,
        "user_types": user_types,
        "engagement": engagement,
    }


# =============================================================================
# Markdown Generation
# =============================================================================

def format_number(n) -> str:
    """Format number with thousand separators, or '-' if None."""
    if n is None:
        return "-"
    return f"{n:,}".replace(",", ",")


def generate_baselines_section(data: dict, year: int) -> str:
    """Generate the Traffic Baselines markdown section."""
    lines = [
        f"## Traffic Baselines ({year})",
        "",
        f"Data retrieved {datetime.now().strftime('%Y-%m-%d')} via Matomo API.",
        "",
        "### Monthly Visitor Stats",
        "",
        "| Month   | Unique Visitors | Visits    | Daily Avg Visitors | Daily Avg Visits |",
        "|---------|-----------------|-----------|--------------------|-----------------:|",
    ]

    for stat in data["monthly_stats"]:
        lines.append(
            f"| {stat['month']} | {format_number(stat['visitors']):>15} | "
            f"{format_number(stat['visits']):>9} | {format_number(stat['daily_avg_visitors']):>18} | "
            f"{format_number(stat['daily_avg_visits']):>16} |"
        )

    # Add typical range
    valid_stats = [s for s in data["monthly_stats"] if s["daily_avg_visitors"] is not None]
    if valid_stats:
        min_v = min(s["daily_avg_visitors"] for s in valid_stats)
        max_v = max(s["daily_avg_visitors"] for s in valid_stats)
        min_visits = min(s["daily_avg_visits"] for s in valid_stats)
        max_visits = max(s["daily_avg_visits"] for s in valid_stats)
        lines.extend([
            "",
            f"**Typical range:** {format_number(min_v)}-{format_number(max_v)} unique visitors/day, "
            f"{format_number(min_visits)}-{format_number(max_visits)} visits/day.",
        ])

    # User types table (if available)
    if data.get("user_types"):
        # Get all user types across months
        all_types = set()
        for types in data["user_types"].values():
            all_types.update(types.keys())
        all_types = sorted(all_types)

        if all_types:
            lines.extend([
                "",
                "### User Type Distribution (visits)",
                "",
            ])

            # Header
            header = "| Month   |"
            separator = "|---------|"
            for ut in all_types:
                header += f" {ut[:12]:>12} |"
                separator += "--------------|"
            lines.append(header)
            lines.append(separator)

            # Data rows
            for stat in data["monthly_stats"]:
                month = stat["month"]
                types = data["user_types"].get(month, {})
                row = f"| {month} |"
                for ut in all_types:
                    val = types.get(ut, 0)
                    row += f" {format_number(val):>12} |"
                lines.append(row)

    # Engagement metrics
    if data.get("engagement"):
        lines.extend([
            "",
            "### Engagement Metrics",
            "",
            "| Month   | Bounce Rate | Actions/Visit | Avg Time on Site |",
            "|---------|-------------|---------------|------------------|",
        ])

        for eng in data["engagement"]:
            avg_time = eng["avg_time"]
            if avg_time:
                minutes = avg_time // 60
                seconds = avg_time % 60
                time_str = f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"
            else:
                time_str = "-"

            actions = eng["actions_per_visit"]
            actions_str = str(actions) if actions is not None else "-"

            lines.append(
                f"| {eng['month']} | {eng['bounce_rate']:>11} | "
                f"{actions_str:>13} | {time_str:>16} |"
            )

    return "\n".join(lines)


def generate_dimensions_section(dimensions: list[dict]) -> str:
    """Generate the Custom Dimensions markdown section."""
    lines = [
        "## Custom Dimensions",
        "",
        f"*Retrieved {datetime.now().strftime('%Y-%m-%d')} via Matomo API.*",
        "",
    ]

    active_dims = [d for d in dimensions if d.get("active")]
    inactive_dims = [d for d in dimensions if not d.get("active")]

    if not active_dims:
        lines.append("**No active custom dimensions configured.**")
    else:
        lines.extend([
            "| ID | Scope | Name |",
            "|----|-------|------|",
        ])
        for d in sorted(active_dims, key=lambda x: x.get("id", 0)):
            lines.append(f"| {d['id']} | {d['scope']} | {d['name']} |")

    if inactive_dims:
        lines.extend([
            "",
            f"*Inactive dimensions: {', '.join(d['name'] for d in inactive_dims)}*",
        ])

    return "\n".join(lines)


def generate_segments_section(segments: list[dict]) -> str:
    """Generate the Saved Segments markdown section."""
    lines = [
        "## Saved Segments",
        "",
        f"*Retrieved {datetime.now().strftime('%Y-%m-%d')} via Matomo API.*",
        "",
    ]

    if not segments:
        lines.append("**No saved segments configured.**")
    else:
        lines.extend([
            "| Name | Definition |",
            "|------|------------|",
        ])
        for s in sorted(segments, key=lambda x: x.get("name", "")):
            # Truncate long definitions
            definition = s.get("definition", "")
            if len(definition) > 60:
                definition = definition[:57] + "..."
            lines.append(f"| {s['name']} | `{definition}` |")

    return "\n".join(lines)


def generate_events_section(event_names: list[dict], ref_month: str) -> str:
    """Generate the Event Names markdown section."""
    lines = [
        "## Event Names",
        "",
        f"*Data from {ref_month}, retrieved {datetime.now().strftime('%Y-%m-%d')} via Matomo API.*",
        "",
    ]

    if not event_names:
        lines.append("**No events tracked.**")
    else:
        lines.extend([
            f"**{len(event_names)} distinct events tracked.**",
            "",
            "| Name | Events | Visits |",
            "|------|--------|--------|",
        ])
        # Sort by event count descending, show top 50
        for e in sorted(event_names, key=lambda x: x.get("events", 0), reverse=True)[:50]:
            lines.append(
                f"| {e['name']} | {format_number(e['events'])} | {format_number(e['visits'])} |"
            )

        if len(event_names) > 50:
            lines.append(f"\n*... and {len(event_names) - 50} more events.*")

    return "\n".join(lines)


def count_section_lines(content: str, section_title: str) -> int:
    """Count non-empty lines in a section."""
    pattern = rf"## {re.escape(section_title)}(.*?)(?=\n## |\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return 0
    section_content = match.group(1)
    return len([l for l in section_content.strip().split("\n") if l.strip()])


def update_doc_section(
    doc_path: Path,
    section_title: str,
    new_content: str,
    dry_run: bool = False,
    max_lines_to_overwrite: int = 5,
) -> bool:
    """
    Update a specific section in a site doc.

    VERY CONSERVATIVE: Only updates if the existing section has fewer than
    `max_lines_to_overwrite` lines (default: 5). This prevents overwriting
    any manually curated content.

    Returns True if file was modified.
    """
    if not doc_path.exists():
        return False

    content = doc_path.read_text()

    # Pattern: ## Section Title ... up to next ## or end of file
    pattern = rf"## {re.escape(section_title)}.*?(?=\n## |\Z)"

    match = re.search(pattern, content, re.DOTALL)
    if match:
        existing_lines = count_section_lines(content, section_title)
        if existing_lines > max_lines_to_overwrite:
            print(f"   Skipping {section_title}: has manual content ({existing_lines} lines)")
            return False

        new_content_with_newline = new_content + "\n"
        new_doc = re.sub(pattern, new_content_with_newline, content, flags=re.DOTALL)
        if new_doc != content:
            if not dry_run:
                doc_path.write_text(new_doc)
            return True
    else:
        print(f"   Section '{section_title}' not found")
    return False


def update_doc_baselines(doc_path: Path, baselines_section: str, dry_run: bool = False) -> bool:
    """
    Update the Traffic Baselines section in a site doc.

    Returns True if file was modified.
    """
    if not doc_path.exists():
        print(f"   Warning: {doc_path} does not exist, skipping")
        return False

    content = doc_path.read_text()

    # Find and replace the Traffic Baselines section
    # Pattern: ## Traffic Baselines ... up to next ## or end of file
    pattern = r"## Traffic Baselines.*?(?=\n## |\Z)"

    if re.search(pattern, content, re.DOTALL):
        new_content = re.sub(pattern, baselines_section + "\n", content, flags=re.DOTALL)
    else:
        # Append after first section (after first ## heading)
        first_heading = re.search(r"^## .+$", content, re.MULTILINE)
        if first_heading:
            insert_pos = first_heading.end()
            # Find end of that section
            next_heading = re.search(r"^## ", content[insert_pos:], re.MULTILINE)
            if next_heading:
                insert_pos = insert_pos + next_heading.start()
            new_content = content[:insert_pos] + "\n" + baselines_section + "\n" + content[insert_pos:]
        else:
            # Just append
            new_content = content + "\n" + baselines_section + "\n"

    if new_content != content:
        if dry_run:
            print(f"   Would update {doc_path}")
        else:
            doc_path.write_text(new_content)
            print(f"   Updated {doc_path}")
        return True
    else:
        print(f"   No changes to {doc_path}")
        return False


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Sync knowledge base with Matomo data")
    parser.add_argument("--site", type=str, help="Sync only this site")
    parser.add_argument("--baselines-only", action="store_true", help="Only sync baselines (skip dimensions, segments, events)")
    parser.add_argument("--year", type=int, default=2025, help="Year to fetch (default: 2025)")
    parser.add_argument("--ref-month", type=str, default=None, help="Reference month for events (YYYY-MM-DD, default: last month)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated")
    args = parser.parse_args()

    # Default ref month to last complete month
    if args.ref_month is None:
        today = date.today()
        if today.month == 1:
            ref_date = date(today.year - 1, 12, 1)
        else:
            ref_date = date(today.year, today.month - 1, 1)
        args.ref_month = ref_date.strftime("%Y-%m-%d")

    print("=" * 70)
    print("Knowledge Base Sync")
    print("=" * 70)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Year: {args.year}")
    print(f"Reference month (events): {args.ref_month[:7]}")
    if args.baselines_only:
        print("Mode: BASELINES ONLY")
    if args.dry_run:
        print("Mode: DRY RUN")
    print()

    # Initialize API
    try:
        api = MatomoAPI()
        print("Matomo API connected")
    except Exception as e:
        print(f"Failed to connect to Matomo: {e}")
        sys.exit(1)

    # Determine which sites to sync
    if args.site:
        if args.site not in SITES:
            print(f"Unknown site: {args.site}")
            print(f"Available: {', '.join(SITES.keys())}")
            sys.exit(1)
        sites_to_sync = {args.site: SITES[args.site]}
    else:
        sites_to_sync = SITES

    print(f"Sites to sync: {len(sites_to_sync)}")
    print()

    project_root = Path(__file__).parent.parent.parent.parent
    updated_count = 0

    for site_key, site_config in sites_to_sync.items():
        print(f"{'=' * 70}")
        print(f"Site: {site_config.name} (ID: {site_config.matomo_id})")
        print(f"{'=' * 70}")

        doc_path = project_root / site_config.doc_path
        site_updated = False

        # 1. Fetch and update baselines
        print(f"Fetching baselines for {args.year}...")
        try:
            data = fetch_baselines(api, site_config, args.year)
            print(f"   Got {len(data['monthly_stats'])} months of data")
            baselines_md = generate_baselines_section(data, args.year)
            if update_doc_baselines(doc_path, baselines_md, args.dry_run):
                site_updated = True
        except Exception as e:
            print(f"   Error fetching baselines: {e}")

        if not args.baselines_only:
            # 2. Fetch and update custom dimensions
            print("Fetching custom dimensions...")
            try:
                dimensions = fetch_custom_dimensions(api, site_config.matomo_id)
                print(f"   Got {len(dimensions)} dimensions")
                if dimensions:
                    dims_md = generate_dimensions_section(dimensions)
                    if update_doc_section(doc_path, "Custom Dimensions", dims_md, args.dry_run):
                        site_updated = True
            except Exception as e:
                print(f"   Error fetching dimensions: {e}")

            # 3. Fetch and update saved segments
            print("Fetching saved segments...")
            try:
                segments = fetch_saved_segments(api, site_config.matomo_id)
                print(f"   Got {len(segments)} segments")
                if segments:
                    segs_md = generate_segments_section(segments)
                    if update_doc_section(doc_path, "Saved Segments", segs_md, args.dry_run):
                        site_updated = True
            except Exception as e:
                print(f"   Error fetching segments: {e}")

            # 4. Fetch and update event names
            print(f"Fetching event names ({args.ref_month[:7]})...")
            try:
                events = fetch_event_names(api, site_config.matomo_id, "month", args.ref_month)
                print(f"   Got {len(events)} event names")
                if events:
                    events_md = generate_events_section(events, args.ref_month[:7])
                    if update_doc_section(doc_path, "Event Names", events_md, args.dry_run):
                        site_updated = True
            except Exception as e:
                print(f"   Error fetching events: {e}")

        if site_updated:
            updated_count += 1
            print(f"   Updated: {doc_path}")
        else:
            print(f"   No changes")

        print()

    print("=" * 70)
    print(f"COMPLETE: {updated_count} sites updated")
    print("=" * 70)


if __name__ == "__main__":
    main()
