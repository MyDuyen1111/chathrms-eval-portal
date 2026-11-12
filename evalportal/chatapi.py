"""Turn a ChatHRMS response (POST /api/chat) into the shape the runner scores.

ChatHRMS has no outcome codes or citation list: they come from its trace and its source tags.
"""
import re

# ChatHRMS answers in the prompt's "[Nguồn: document]" tags; a tag may hold several names.
CITED = re.compile(r"\[Nguồn:\s*([^\]]+)\]")
# ChatHRMS could not reach its LLM at all, so every case after this one would fail too. A single failed LLM call
# (fallback:ai_unavailable) is a timeout of that case instead, see ChatHRMSChat.send.
DOWN = ("fallback:offline_policy_search",)


def normalize(body):
    trace = body.get("trace") or {}
    route, text = trace.get("route") or "", body.get("response") or ""
    # Answered from documents only when policy search ran; other answers are judged against an empty context.
    outcome = "unavailable" if route in DOWN else "answered" if trace.get("context") else "non_knowledge"
    names = [name.strip() for tag in CITED.findall(text) for name in re.split(r"[;,]", tag)]
    return {
        "outcome": outcome,
        "text": text,
        # Its only confirmation turn is the ticket draft; the runner confirms it, like the handbook's intent check.
        "turn_type": "confirmation" if route == "rule:ticket_workflow" else "answer",
        "correlation_id": body.get("correlationId"),
        "citations": [{"document": name, "sections": [], "pages": []} for name in dict.fromkeys(filter(None, names))],
    }
