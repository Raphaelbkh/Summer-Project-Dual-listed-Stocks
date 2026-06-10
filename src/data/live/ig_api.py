"""Minimal IG REST API client for observe-only demo connectivity."""

from dataclasses import dataclass
from typing import Any
import os

import requests


@dataclass
class IGCredentials:
    api_key: str
    username: str
    password: str


class IGAPIClient:
    """Small IG REST client with session login for demo/live environments."""

    def __init__(
        self,
        base_url: str,
        credentials: IGCredentials,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials
        self.session = session or requests.Session()
        self.cst: str | None = None
        self.security_token: str | None = None

    def login(self) -> dict[str, Any]:
        """Create an IG API session and store response tokens."""
        response = self.session.post(
            f"{self.base_url}/session",
            headers={
                "X-IG-API-KEY": self.credentials.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json; charset=UTF-8",
                "Version": "2",
            },
            json={
                "identifier": self.credentials.username,
                "password": self.credentials.password,
            },
            timeout=15,
        )
        _raise_for_ig_error(response)
        self.cst = response.headers.get("CST")
        self.security_token = response.headers.get("X-SECURITY-TOKEN")
        return response.json()

    def authenticated_headers(self) -> dict[str, str]:
        """Return headers for authenticated observe-only API requests."""
        if not self.cst or not self.security_token:
            raise ValueError("IG API client is not logged in.")
        return {
            "X-IG-API-KEY": self.credentials.api_key,
            "CST": self.cst,
            "X-SECURITY-TOKEN": self.security_token,
            "Accept": "application/json; charset=UTF-8",
        }

    def get_accounts(self) -> dict[str, Any]:
        """Fetch account metadata after login."""
        response = self.session.get(
            f"{self.base_url}/accounts",
            headers=self.authenticated_headers(),
            timeout=15,
        )
        _raise_for_ig_error(response)
        return response.json()


def _raise_for_ig_error(response: requests.Response) -> None:
    """Raise an HTTP error that includes IG's JSON errorCode when available."""
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            body = response.json()
        except ValueError:
            body = response.text
        raise requests.HTTPError(
            f"{exc}; IG response body: {body}",
            response=response,
        ) from exc


def load_ig_credentials_from_env(config_dict: dict) -> IGCredentials:
    """Load IG credentials from environment variables named in config."""
    ig_config = config_dict["ig"]
    api_key = os.getenv(ig_config["api_key_env"], "")
    username = os.getenv(ig_config["username_env"], "")
    password = os.getenv(ig_config["password_env"], "")
    missing = [
        name
        for name, value in [
            (ig_config["api_key_env"], api_key),
            (ig_config["username_env"], username),
            (ig_config["password_env"], password),
        ]
        if not value
    ]
    if missing:
        raise ValueError("Missing IG environment variables: " + ", ".join(missing))
    return IGCredentials(api_key=api_key, username=username, password=password)


def ig_base_url(config_dict: dict) -> str:
    """Resolve the configured IG REST base URL."""
    ig_config = config_dict["ig"]
    environment = ig_config.get("environment", "demo")
    if environment == "demo":
        return ig_config["demo_base_url"]
    if environment == "live":
        return ig_config["live_base_url"]
    raise ValueError(f"Unsupported IG environment: {environment}")
