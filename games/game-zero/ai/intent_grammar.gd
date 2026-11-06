extends RefCounted
## Grammar-constrained intents for typed (and, later, Vosk voice) commands.
## Same closed grammar for text and voice (ADR-0006): small vocabulary, no LLM.

const VERBS := {
	"focus": ["focus", "target", "attack", "hit"],
	"regroup": ["regroup", "fall back", "retreat", "back"],
	"defensive": ["defend", "defensive", "hold", "careful"],
	"aggressive": ["aggressive", "charge", "go", "push"],
	"swap": ["swap", "switch"],
}


static func parse(text: String, enemy_kinds: Array, party: Array) -> Dictionary:
	var t := text.to_lower().strip_edges()
	for intent in VERBS:
		for w in VERBS[intent]:
			if t.begins_with(w) or (" " + w + " ") in (" " + t + " "):
				var out := {"intent": intent, "text": text}
				if intent == "focus":
					for k in enemy_kinds:
						var plain: String = k.replace("_", " ")
						if plain in t or k in t or plain.split(" ")[-1] in t:
							out["target_kind"] = k
					if not out.has("target_kind"):
						return {"intent": "unknown", "text": text}
				elif intent == "swap":
					for p in party:
						if p in t:
							out["to"] = p
				return out
	return {"intent": "unknown", "text": text}
