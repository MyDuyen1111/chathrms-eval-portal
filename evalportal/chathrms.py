"""Chat client for ChatHRMS, the HR bot testers practice the handbook on. Same four methods as MockChat.

Each case signs in as the employee in its `user` column. ChatHRMS has one password for its admins and
one for its employees, so the client tries both.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid


class ChatHRMSChat:
    def __init__(self, base_url, passwords, build="live", timeout=120):
        self.base_url = base_url.rstrip("/")
        self.passwords = [password for password in passwords if password]
        self.build = build
        self.timeout = timeout
        self.contexts = {}

    def current_build(self, product):
        # shortcut: ChatHRMS has no build endpoint, so every run reports CHATHRMS_BUILD; read it from the API once there is one.
        return self.build

    def new_conversation(self, product, case):
        """Sign in for every case, so a token never expires in the middle of a long run."""
        status, body = 401, {"code": "no_password", "detail": "CHATHRMS_PASSWORD is not set on the portal."}
        for password in self.passwords:
            status, body = self._post("/api/auth/login", {"employee_code": case["user"], "password": password})
            if status == 200:
                return {"token": body["access_token"], "id": ""}
        return {"refused": (status, body)}

    def send(self, conversation, text):
        """Return (http_status, body) like MockChat. The body gets a correlationId the API does not have."""
        if "refused" in conversation:
            return conversation["refused"]
        fields = {"message": text, "conversation_id": conversation["id"]} if conversation["id"] else {"message": text}
        status, body = self._post("/api/chat", fields, token=conversation["token"])
        if status == 200:
            conversation["id"] = body.get("conversation_id") or ""
            if (body.get("trace") or {}).get("route") == "fallback:ai_unavailable":
                # ChatHRMS says "AI unavailable" when its LLM call fails or passes 25 s. Like a chat timeout, the runner
                # then retries once and fails this case alone, where an outcome of "unavailable" would stop the run.
                raise TimeoutError
            body["correlationId"] = str(uuid.uuid4())
            self.contexts[body["correlationId"]] = "\n\n".join((body.get("trace") or {}).get("context") or [])
        return status, body

    def retrieved_context(self, product, correlation_id):
        return self.contexts.pop(correlation_id, "")

    def _post(self, path, fields, token=None):
        if token:  # /api/chat takes form fields, /api/auth/login takes JSON
            data, headers = urllib.parse.urlencode(fields).encode(), {"Authorization": f"Bearer {token}"}
        else:
            data, headers = json.dumps(fields).encode(), {"Content-Type": "application/json"}
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                try:
                    return error.code, json.load(error)
                except ValueError:
                    return error.code, {}
        except TimeoutError:
            raise
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise TimeoutError from None
            return 503, {"code": "unreachable"}
