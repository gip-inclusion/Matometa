"""
Metabase API client for Matometa.

Usage:
    from skills.metabase_query.scripts.metabase import MetabaseAPI

    api = MetabaseAPI()  # loads from .env
    result = api.execute_sql("SELECT 1 as test")
    print(result.to_markdown())
"""

import json
import urllib.request
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class QueryResult:
    """Result from a Metabase query."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int

    def to_markdown(self, max_rows: int = 20) -> str:
        """Format result as a markdown table."""
        if self.row_count == 0:
            return "Aucun résultat trouvé."

        lines = [f"Résultats ({self.row_count} lignes):", ""]

        # Header
        lines.append("| " + " | ".join(self.columns) + " |")
        lines.append("| " + " | ".join("---" for _ in self.columns) + " |")

        # Rows
        rows_to_show = min(max_rows, self.row_count)
        for i in range(rows_to_show):
            cells = [str(cell) if cell is not None else "" for cell in self.rows[i]]
            lines.append("| " + " | ".join(cells) + " |")

        if self.row_count > max_rows:
            lines.append(f"\n... et {self.row_count - max_rows} lignes supplémentaires")

        return "\n".join(lines)

    def to_dicts(self) -> list[dict]:
        """Convert rows to list of dictionaries."""
        return [dict(zip(self.columns, row)) for row in self.rows]


class MetabaseError(Exception):
    """Error from Metabase API."""

    pass


class MetabaseAPI:
    """Client for querying the Metabase API."""

    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        database_id: Optional[int] = None,
    ):
        """
        Initialize the API client.

        If parameters not provided, loads from .env file in project root.
        """
        if url and api_key:
            self.url = url.rstrip("/")
            self.api_key = api_key
            self.database_id = database_id or 2
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

        self.url = env.get("METABASE_BASE_URL", "").rstrip("/")
        self.api_key = env.get("METABASE_API_KEY")
        self.database_id = int(env.get("METABASE_DATABASE_ID", 2))

        if not self.url or not self.api_key:
            raise ValueError(
                "METABASE_BASE_URL and METABASE_API_KEY must be set in .env"
            )

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        timeout: int = 60,
    ) -> Any:
        """Make an API request."""
        url = f"{self.url}{endpoint}"

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        request_data = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=request_data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else str(e)
            raise MetabaseError(f"HTTP {e.code}: {error_body}")
        except urllib.error.URLError as e:
            raise MetabaseError(f"Request failed: {e}")

    def _parse_result(self, data: dict) -> QueryResult:
        """Parse Metabase query result into QueryResult."""
        cols = data.get("data", {}).get("cols", [])
        rows = data.get("data", {}).get("rows", [])

        columns = [col.get("display_name") or col.get("name", f"col_{i}")
                   for i, col in enumerate(cols)]

        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
        )

    # --- Core methods ---

    def execute_sql(self, sql: str, timeout: int = 60) -> QueryResult:
        """
        Execute a native SQL query.

        Args:
            sql: SQL query to execute
            timeout: Request timeout in seconds

        Returns:
            QueryResult with columns and rows
        """
        data = {
            "database": self.database_id,
            "type": "native",
            "native": {"query": sql},
        }
        result = self._request("POST", "/api/dataset", data, timeout=timeout)
        return self._parse_result(result)

    def execute_card(self, card_id: int, timeout: int = 60) -> QueryResult:
        """
        Execute a saved Metabase card/question.

        Args:
            card_id: The card ID to execute
            timeout: Request timeout in seconds

        Returns:
            QueryResult with columns and rows
        """
        result = self._request(
            "POST", f"/api/card/{card_id}/query", {}, timeout=timeout
        )
        return self._parse_result(result)

    def get_card(self, card_id: int) -> dict:
        """
        Get card metadata.

        Args:
            card_id: The card ID

        Returns:
            Card metadata dict with name, description, dataset_query, etc.
        """
        return self._request("GET", f"/api/card/{card_id}")

    # --- Discovery methods ---

    def list_cards(self, collection_id: int) -> list[dict]:
        """
        List cards in a collection.

        Args:
            collection_id: The collection ID

        Returns:
            List of card metadata dicts
        """
        result = self._request("GET", f"/api/collection/{collection_id}/items")
        items = result.get("data", [])
        return [item for item in items if item.get("model") == "card"]

    def search_cards(self, query: str, limit: int = 50) -> list[dict]:
        """
        Search for cards by name/description.

        Args:
            query: Search query
            limit: Max results

        Returns:
            List of matching card metadata dicts
        """
        params = urllib.parse.urlencode({
            "q": query,
            "models": "card",
            "limit": limit,
        })
        result = self._request("GET", f"/api/search?{params}")
        return result.get("data", [])

    def get_card_sql(self, card_id: int) -> str:
        """
        Get the SQL query for a card.

        For native queries, returns the SQL directly.
        For GUI queries, executes the card to get compiled SQL.

        Args:
            card_id: The card ID

        Returns:
            SQL query string
        """
        card = self.get_card(card_id)
        dataset_query = card.get("dataset_query", {})

        # Native SQL query
        if dataset_query.get("type") == "native":
            return dataset_query.get("native", {}).get("query", "")

        # GUI query - need to execute to get compiled SQL
        try:
            result = self._request("POST", f"/api/card/{card_id}/query", {})
            native_form = result.get("data", {}).get("native_form", {})
            return native_form.get("query", "")
        except MetabaseError:
            return ""

    # --- Dashboard methods ---

    def get_dashboard(self, dashboard_id: int) -> dict:
        """
        Get dashboard metadata including cards.

        Args:
            dashboard_id: The dashboard ID

        Returns:
            Dashboard metadata dict with dashcards, tabs, etc.
        """
        return self._request("GET", f"/api/dashboard/{dashboard_id}")

    def list_dashboards(self, collection_id: int) -> list[dict]:
        """
        List dashboards in a collection.

        Args:
            collection_id: The collection ID

        Returns:
            List of dashboard metadata dicts
        """
        result = self._request("GET", f"/api/collection/{collection_id}/items")
        items = result.get("data", [])
        return [item for item in items if item.get("model") == "dashboard"]

    # --- User info ---

    def get_current_user(self) -> dict:
        """Get current authenticated user info."""
        return self._request("GET", "/api/user/current")


def load_api() -> MetabaseAPI:
    """Load API client from .env in current directory or parents."""
    # Try current directory first
    if Path(".env").exists():
        return MetabaseAPI()

    # Try parent directories
    cwd = Path.cwd()
    for parent in cwd.parents:
        env_path = parent / ".env"
        if env_path.exists():
            import os
            original_cwd = os.getcwd()
            os.chdir(parent)
            api = MetabaseAPI()
            os.chdir(original_cwd)
            return api

    raise FileNotFoundError("No .env file found in current directory or parents")


if __name__ == "__main__":
    # Quick test
    api = MetabaseAPI()
    user = api.get_current_user()
    print(f"Connected as: {user.get('email')}")

    result = api.execute_sql("SELECT 1 as test")
    print(result.to_markdown())
