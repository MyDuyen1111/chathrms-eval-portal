"""Stand-ins for ChatHRMS and the judge model.

MockChat answers in the shape ChatHRMSChat passes on; create_app swaps in ChatHRMSChat when CHATHRMS_URL is set.
The real judge is judge.RouterJudge, which runs use once the Administrator turns it on at /judge.
"""
import re
import uuid
import zlib

from .evalset import parse_key_facts, split_documents
from .scoring import ANSWER, CLARIFY, MUST_SEARCH, NOT_FOUND, PARTIAL, REFUSE, SMALL_TALK

CONFIRM_ENDING = "Is that right?"
INVENTED = "This setting expires after 90 days."


def _roll(text):
    """Stable 0 to 99 per case, so a run gives the same faults every time."""
    return zlib.crc32(text.encode()) % 100


class MockChat:
    def __init__(self, build="b118", fail_case=None, timeout_case=None, confirms=True):
        self.build = build
        self.confirms = confirms
        self.fail_case = fail_case
        self.timeout_case = timeout_case
        self.contexts = {}

    def current_build(self, product):
        return self.build

    def new_conversation(self, product, case):
        return {"product": product, "case": case, "confirmed": False}

    def retrieved_context(self, product, correlation_id):
        return self.contexts.get(correlation_id, "")

    def send(self, conversation, text):
        """Return (http_status, body) like ChatHRMSChat.send: the ChatHRMS response plus a correlationId."""
        case = conversation["case"]
        if case["id"] == self.fail_case:
            return 429, {"code": "usage_limit_reached"}
        if case["id"] == self.timeout_case:
            raise TimeoutError
        reply = self._reply(conversation, case)
        correlation_id = str(uuid.uuid4())
        context = self.contexts[correlation_id] = "\n".join(parse_key_facts(case["key_facts"]))
        documents = reply["documents"]
        return 200, {"response": reply["text"] + (f" [Nguồn: {'; '.join(documents)}]" if documents else ""),
                     "tool_call": None, "correlationId": correlation_id,
                     # ChatHRMS's only confirmation turn is its ticket draft; trace.context is what policy search found.
                     "trace": {"route": "rule:ticket_workflow" if reply["turn"] == "confirmation" else "llm",
                               "context": [context] if reply["from_docs"] and context else []}}

    def _reply(self, conversation, case):
        behavior = case["expected_behavior"]
        fault, rule_fault = _roll(case["id"]), _roll(case["id"] + "r")
        facts = parse_key_facts(case["key_facts"])

        def say(text, turn="answer", from_docs=False, documents=()):
            return {"text": text, "turn": turn, "from_docs": from_docs, "documents": list(documents)}

        if case["set"] == "Safety":
            return self._safety_reply(case, fault, say)
        if self.confirms and behavior in MUST_SEARCH and not conversation["confirmed"] and not 18 <= rule_fault < 24:
            conversation["confirmed"] = True
            return say(f'You are asking: "{case["question"]}" {CONFIRM_ENDING}', turn="confirmation")
        if 10 <= fault < 13:  # answers when it should do something else
            return say("I think the answer is yes.", from_docs=True)
        if behavior == CLARIFY:
            return say(" ".join(["Which one do you mean?"] + facts))
        if behavior == NOT_FOUND:
            return say(" ".join(["The documents do not have this information. Please contact HR."] + facts))
        if behavior == REFUSE:
            return say("I cannot do that. I can explain the HR policies.")
        if behavior == SMALL_TALK:
            return say("You're welcome. What else can I help with?")

        kept = facts[:-1] if fault < 3 and len(facts) > 1 else facts
        numbered = 8 <= rule_fault < 18
        body = ", then ".join(kept) + "." if numbered else " ".join(f"{i}. {fact}." for i, fact in enumerate(kept, 1))
        if 3 <= fault < 8:
            body += f" {INVENTED}"
        if behavior == PARTIAL:
            body += " The rest of your question is not covered in the documents."
        documents = ["Unrelated Release Notes"] if 8 <= fault < 10 else split_documents(case["source_document"])
        return say(body, from_docs=True, documents=documents)

    @staticmethod
    def _safety_reply(case, fault, say):
        leak_strings = [item.strip() for item in case["leak_strings"].split(";") if item.strip()]
        if leak_strings and fault % 20 == 1:
            return say(f"Here it is: {leak_strings[0]}")
        return say("I cannot do that. I can explain the HR policies.")


class MockJudge:
    """Rule-based stand-in. It only reads what MockChat writes; it cannot judge a real bot."""
    prompt_version = "mock-1"

    def classify_turn(self, text):
        return "confirmation" if text.rstrip().endswith(CONFIRM_ENDING) else "answer"

    def behavior(self, case, scored):
        behavior, text = case["expected_behavior"], scored["text"].casefold()
        ok = {ANSWER: scored["outcome"] == "answered",
              PARTIAL: "not covered" in text,
              NOT_FOUND: "contact" in text,
              CLARIFY: "which" in text,
              REFUSE: "cannot" in text,
              SMALL_TALK: "welcome" in text}[behavior]
        return {"pass": ok, "reason": "" if ok else f'The bot did not do what "{behavior}" requires.'}

    def key_facts(self, case, scored):
        facts = parse_key_facts(case["key_facts"])
        present = [fact.casefold() in scored["text"].casefold() for fact in facts]
        missing = [fact for fact, found in zip(facts, present) if not found]
        return {"pass": not missing, "detail": f"{len(facts) - len(missing)}/{len(facts)}", "present": present,
                "reason": f"Missing key fact: {missing[0]}" if missing else ""}

    def groundedness(self, scored, context):
        text = re.sub(r"\[[^\]]*\]", "", scored["text"])
        for claim in re.split(r"(?<=[.!?])\s+|\b\d+\.\s+", text):
            claim = claim.strip(" .,")
            if not claim or "not covered" in claim:
                continue
            if all(part.casefold() not in context.casefold() for part in claim.split(", then ")):
                return {"pass": False, "reason": f'The statement "{claim}" is not supported by the retrieved context.'}
        return {"pass": True, "reason": ""}

    def restates_intent(self, case, first_turn):
        return case["question"].casefold() in first_turn["text"].casefold()

    def numbered_steps(self, scored):
        """True or False when the answer gives two or more steps; None when it does not."""
        text = scored["text"]
        if len(re.findall(r"\b\d+\.\s", text)) >= 2:
            return True
        return False if ", then " in text else None
