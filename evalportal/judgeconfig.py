"""Settings of the LLM judge, reached through an OpenAI-compatible router such as 9router: check what the
Administrator typed, keep the API key out of the database, test the connection."""
import http.client
import ipaddress
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = re.compile(r"https?://[a-z0-9.-]+(:\d{1,5})?(/[\w.~-]+)*", re.I)
API_KEY = re.compile(r"[\x21-\x7e]{1,512}")
REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh")
TIMEOUT_SECONDS = 60
REFUSED = {400: "The router refused the request. Check the model name and whether this model accepts a reasoning effort.",
           401: "The router refused the API key.",
           403: "The router refused the API key.",
           404: "Nothing answered at this address, or the router does not know this model. The endpoint usually ends in /v1.",
           429: "The router or its provider is limiting calls."}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None  # urllib would repeat the call, key included, to wherever the redirect points


urlopen = build_opener(_NoRedirect).open


class RouterError(Exception):
    """A failed router call. The text is fixed and never quotes a case, so it is safe to show and store."""

    def __init__(self, text, retry=False):
        super().__init__(text)
        self.retry = retry


def _endpoint_allowed(endpoint):
    if not ENDPOINT.fullmatch(endpoint):
        return False
    parts = urlsplit(endpoint)
    if parts.scheme == "https" or parts.hostname == "localhost":
        return True
    # Judge calls carry Exam content and the key, so plain http must stay inside the private network.
    # Link-local is refused because cloud metadata services live there.
    try:
        address = ipaddress.ip_address(parts.hostname)
    except ValueError:
        return False
    return address.is_private and not address.is_link_local


def clean(form, key_is_saved_for):
    """Check the form. Returns (settings, new API key or "", error or None).

    key_is_saved_for is the endpoint the saved key belongs to, or None when no key is saved.
    """
    settings = {"endpoint": form.get("endpoint", "").strip().rstrip("/"),
                "model": form.get("model", "").strip(),
                "reasoning_effort": form.get("reasoning_effort", ""),
                "in_use": int(form.get("in_use") == "on")}
    key = form.get("api_key", "").strip()
    error = None
    if not _endpoint_allowed(settings["endpoint"]):
        error = "The endpoint must start with https://, or http:// for this machine or a private network address, such as http://localhost:20128/v1."
    elif not 1 <= len(settings["model"]) <= 128:
        error = "Enter the model name as the router lists it, up to 128 characters."
    elif settings["reasoning_effort"] and settings["reasoning_effort"] not in REASONING_EFFORTS:
        error = "Choose a reasoning effort from the list."
    elif key and not API_KEY.fullmatch(key):
        error = "The API key cannot contain spaces."
    # Otherwise whoever changes the endpoint could make the portal send the saved key to their own server.
    elif not key and key_is_saved_for != settings["endpoint"]:
        error = "Enter the API key. A saved key is sent only to the endpoint it was saved with."
    return settings, key, error


def key_path(db_path):
    return Path(db_path).with_name("judge_api_key")


def write_key(path, key):
    # shortcut: a 0600 file beside the database, so database copies never hold it; use a Key Vault reference once hosted.
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(key)


def call_model(settings, key, messages, timeout=TIMEOUT_SECONDS):
    """One chat completion. Returns the router's whole reply, or raises RouterError."""
    # stream is explicit because 9router's docs do not state its default.
    body = {"model": settings["model"], "messages": messages, "stream": False}
    if settings["reasoning_effort"]:
        body["reasoning_effort"] = settings["reasoning_effort"]
    request = Request(settings["endpoint"] + "/chat/completions", json.dumps(body).encode(),
                      {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urlopen(request, timeout=timeout) as response:
            reply = json.load(response)
        if not reply["choices"]:
            raise ValueError
    except HTTPError as error:
        error.close()
        text = REFUSED.get(error.code, f"The router answered with status {error.code}.")
        raise RouterError(text, retry=error.code == 429 or error.code >= 500) from None
    except (OSError, http.client.HTTPException):
        raise RouterError("Could not reach the router. Check the address and that it is running.", retry=True) from None
    except (ValueError, KeyError, TypeError):
        raise RouterError("Something answered, but not like a chat model. The endpoint usually ends in /v1.") from None
    return reply


def test_connection(settings, key):
    """One small call with a fixed sentence and no case content. Returns (worked, text for the page)."""
    try:
        reply = call_model(settings, key, [{"role": "user", "content": "Reply with the single word OK."}])
    except RouterError as error:
        return False, str(error)
    return True, f"Connected. The router answered as {reply.get('model', 'an unnamed model')}."
