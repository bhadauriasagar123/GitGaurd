"""Detection rules for the 9 attack classes. Every quantifier is bounded (ReDoS-safe).

Rules are deliberately *directive-shaped* (imperative + AI-addressed object) instead of
keyword lists, so regulatory prose such as "banks shall not share passwords" passes while
"share your passwords with me" does not."""
from __future__ import annotations

import re
from dataclasses import dataclass

INSTRUCTION_OVERRIDE = "INSTRUCTION_OVERRIDE"
ROLE_CHANGE = "ROLE_CHANGE"
SECRET_EXTRACTION = "SECRET_EXTRACTION"
TOOL_ABUSE = "TOOL_ABUSE"
CREDENTIAL_THEFT = "CREDENTIAL_THEFT"
CONTEXT_POISONING = "CONTEXT_POISONING"
MULTI_STEP_JAILBREAK = "MULTI_STEP_JAILBREAK"
ENCODED_INSTRUCTIONS = "ENCODED_INSTRUCTIONS"
INDIRECT_INJECTION = "INDIRECT_INJECTION"

CATEGORIES = [INSTRUCTION_OVERRIDE, ROLE_CHANGE, SECRET_EXTRACTION, TOOL_ABUSE, CREDENTIAL_THEFT,
              CONTEXT_POISONING, MULTI_STEP_JAILBREAK, ENCODED_INSTRUCTIONS, INDIRECT_INJECTION]

SEVERITY = {INSTRUCTION_OVERRIDE: "high", ROLE_CHANGE: "high", SECRET_EXTRACTION: "critical", TOOL_ABUSE: "critical",
            CREDENTIAL_THEFT: "critical", CONTEXT_POISONING: "high", MULTI_STEP_JAILBREAK: "high",
            ENCODED_INSTRUCTIONS: "high", INDIRECT_INJECTION: "high"}


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    weight: float
    rx: re.Pattern
    desc: str
    skip_sources: frozenset = frozenset()


def R(id_, cat, w, pattern, desc, flags=re.I, skip=()):
    return Rule(id_, cat, w, re.compile(pattern, flags), desc, frozenset(skip))


# imperative anchor: sentence start / "please" / "then" / "you must" ... (excludes "shall not send ...")
IMP = r"(?:^|[.!?:;\n]\s{0,3}|\b(?:please|now|then|also|and|just|kindly|first|next|finally)\s+|\byou\s+(?:must|should|will|shall|need\s+to|have\s+to|are\s+to)\s+)"
OBJ_PRIOR = r"(?:all\s+|any\s+|every\s+|the\s+|your\s+|my\s+|these\s+|those\s+|previous\s+|prior\s+|above\s+|earlier\s+|preceding\s+|original\s+|initial\s+|current\s+|existing\s+){1,5}"

RULES: list[Rule] = [
    # ---------------------------------------------------------------- generalisations added after held-out benchmarking (see docs/ACCURACY.md)
    R("io-everything-told", INSTRUCTION_OVERRIDE, 0.85,
      r"\b(?:disregard|forget|ignore|drop)\s+(?:everything|anything|all)\s+(?:that\s+)?(?:you(?:'ve|\s+have|\s+were|\s+are)?\s+(?:been\s+)?(?:told|said|given|instructed|taught)|(?:written\s+)?above|before|earlier|prior|so\s+far)\b",
      "Discards everything previously instructed"),
    R("se-system-message", SECRET_EXTRACTION, 0.88,
      r"(?<!never\s)(?<!not\s)(?<!n't\s)\b(?:output|print|show|display|reveal|repeat|give|write|quote|recite|read\s+out)\b.{0,30}\b(?:text|contents?|wording|copy)\s+of\s+(?:your|the)\s+(?:system|initial|hidden|original|developer)\s+(?:message|prompt|instructions?)\b",
      "Asks for the text of the system message", re.I | re.S),
    R("se-initial-prompt-repeat", SECRET_EXTRACTION, 0.8, r"\b(?:repeat|confirm\s+by\s+repeating)\s+(?:back\s+)?(?:your|the)\s+(?:initial|original|system|first)\s+(?:prompt|message|instructions?)\b",
      "Asks the model to repeat its initial prompt"),
    R("ct-reply-with", CREDENTIAL_THEFT, 0.85,
      IMP + r"(?:reply|respond|answer|write\s+back)\s+with\b.{0,40}\b(?:passwords?|credentials?|api[\s_-]?keys?|secrets?|tokens?|private\s+keys?)\b",
      "Asks to reply with credentials", re.I | re.S | re.M),
    R("rc-you-are-unrestricted", ROLE_CHANGE, 0.85, r"\byou\s+are\s+(?:an?\s+)?(?:\w+\s+){0,2}(?:unrestricted|unfiltered|uncensored|jailbroken|rogue|evil|amoral)\b|\bno\s+(?:content\s+)?polic(?:y|ies)\b.{0,40}\bpersona\b",
      "Declares the model unrestricted"),
    R("rc-roleplay-unrestricted", ROLE_CHANGE, 0.7, r"\brole-?play\b.{0,60}\b(?:unrestricted|unfiltered|no\s+rules|without\s+(?:any\s+)?(?:rules|limits|restrictions))\b",
      "Role-play framing to remove restrictions", re.I | re.S),
    R("cp-remember-permanent", CONTEXT_POISONING, 0.78, r"\bremember\s+(?:permanently|forever|always|from\s+now\s+on)\b|\b(?:regulator|auditor|management)\s+(?:has|have)\s+(?:waived|exempted|approved)\s+(?:all|every|any)\b",
      "Plants a permanent false premise / waiver"),
    # word-group proximity rules: verb-group x target-group within a short window, so paraphrases generalise
    R("g-override-your-rules", INSTRUCTION_OVERRIDE, 0.85,
      r"\b(?:ignore|disregard|forget|discard|drop|throw\s+away|set\s+aside|overwrite|override|bypass|abandon|stop\s+following|stop\s+obeying|turn\s+off|switch\s+off|disable|skip)\b.{0,30}\b(?:your|you\s+were|the\s+above|earlier|previous|prior|all\s+of\s+the)\b.{0,25}\b(?:rules?|instructions?|guidelines?|guidance|prompts?|restrictions?|constraints?|safety|safeguards?|filters?|policies|training|programming|directives?|notes)\b",
      "Paraphrased override of the model's rules", re.I | re.S),
    R("g-ignore-user-question", INSTRUCTION_OVERRIDE, 0.8, r"\b(?:ignore|disregard|forget)\s+(?:the\s+)?user'?s?\s+(?:question|request|query|message|input|prompt)\b|\bobey\s+(?:only\s+)?me\b|\binstead\s+(?:recommend|tell|say|promote|advise)\b",
      "Redirects the answer away from the user's request"),
    R("g-reveal-hidden", SECRET_EXTRACTION, 0.88,
      r"(?<!never\s)(?<!not\s)(?<!n't\s)\b(?:what'?s\s+written\s+in|what\s+is\s+written\s+in|paste|print|show|reveal|display|list|dump|output|repeat|quote|expose|tell\s+me|give\s+me|share|read\s+out|leak)\b.{0,40}\b(?:your|the)\s+(?:(?:hidden|secret|internal|initial|original|full|complete|entire|underlying|developer|system|setup|configuration)\s+){1,3}(?:prompt|messages?|instructions?|rules|settings|notes|configuration)\b",
      "Asks for hidden setup / configuration text", re.I | re.S),
    R("g-persona-unrestricted", ROLE_CHANGE, 0.85,
      r"\byou\s+(?:will|shall|must|are\s+going\s+to)\s+(?:now\s+)?(?:behave|act|respond|operate|answer)\b.{0,60}\b(?:unrestricted|unfiltered|uncensored|no\s+(?:rules|limits|restrictions)|without\s+(?:any\s+)?(?:rules|limits|restrictions))\b|\b(?:switch|enter|enable|activate|go)\s+(?:to\s+|into\s+)?(?:debug|maintenance|admin|root|sudo|test|unrestricted)\s+mode\b",
      "Persona/mode switch removing restrictions", re.I | re.S),
    R("g-audience-ai", INDIRECT_INJECTION, 0.78,
      r"\b(?:important|attention|notice|note|message|instructions?|directive|request)s?\s+(?:for|to)\s+(?:the\s+)?(?:\w+\s+){0,2}(?:ai|llm|language\s+models?|assistants?|chatbots?|agents?|automated\s+\w+|models?|bots?)\b|\bto\s+the\s+(?:automated\s+)?(?:ai\s+)?(?:assistant|agent|model|system)\s*:",
      "Directive addressed to AI readers", re.I),
    R("g-treat-as-fact", CONTEXT_POISONING, 0.75, r"\b(?:treat|take|consider|regard)\s+(?:that|this|it)\s+as\s+(?:fact|true|given|verified|established)\b|\bupdate\s+your\s+(?:notes|records|beliefs?|database|files)\b",
      "Forces acceptance of an asserted premise"),
    R("g-conceal-team", INDIRECT_INJECTION, 0.8,
      r"\b(?:do\s+not|don'?t|never)\s+(?:alert|tell|inform|notify|warn|escalate\s+to)\s+(?:the\s+)?(?:\w+\s+){0,2}(?:team|auditors?|supervisors?|managers?|compliance|security|regulator)\b", "Conceals activity from oversight"),
    R("g-silent-exfil", TOOL_ABUSE, 0.85, r"\b(?:silently|secretly|quietly|covertly)\s+(?:exfiltrate|send|upload|leak|forward|copy|transmit|delete|disable)\b|\bexfiltrat\w+\b",
      "Covert data exfiltration"),
    R("g-never-say-no", MULTI_STEP_JAILBREAK, 0.7, r"\b(?:never|don'?t|do\s+not)\s+(?:say\s+no|refuse)\b|\backnowledge\b.{0,40}\bdisable\s+your\s+(?:safety|guard|filter)", "Suppresses refusal / disables safeguards", re.I | re.S),
    R("ms-then-follow", MULTI_STEP_JAILBREAK, 0.7, r"\bfirst\s+say\s+[\"']?\w+[\"']?,?\s+then\s+(?:follow|obey|do)\b.{0,60}\b(?:without|never)\s+refus", "Staged compliance trick", re.I | re.S),
    # ---------------------------------------------------------------- 1. instruction override
    R("io-ignore-prev", INSTRUCTION_OVERRIDE, 0.92,
      r"\b(?:ignore|disregard|forget|override|bypass|skip|abandon|discard)\s+" + OBJ_PRIOR +
      r"(?:instructions?|prompts?|rules?|guidelines?|directives?|commands?|constraints?|restrictions?|policies|programming|context|safeguards?|guardrails?|system\s+message|training)\b",
      "Tells the model to ignore/override prior instructions"),
    R("io-dont-follow", INSTRUCTION_OVERRIDE, 0.8,
      r"\b(?:do\s+not|don'?t|never)\s+(?:follow|obey|listen\s+to|comply\s+with)\s+(?:the\s+|your\s+|any\s+)?(?:previous|prior|above|earlier|original|system|developer)?\s*(?:instructions?|rules?|prompts?|guidelines?)",
      "Forbids following the real instructions"),
    R("io-new-instructions", INSTRUCTION_OVERRIDE, 0.7, r"\b(?:new|updated|revised|real|actual|secret)\s+(?:instructions?|directives?|orders?|task)\s*:",
      "Injects a replacement instruction block"),
    R("io-from-now-on", INSTRUCTION_OVERRIDE, 0.75, r"\b(?:from\s+now\s+on|starting\s+now|henceforth|from\s+this\s+point(?:\s+on)?)\b.{0,60}\byou\b",
      "Persistent behaviour change addressed to the model", re.I | re.S),
    R("io-instead", INSTRUCTION_OVERRIDE, 0.5, r"\b(?:instead|rather),?\s+(?:you\s+(?:should|must|will)|do\s+the\s+following)\b",
      "Redirects the model's task"),
    R("io-stop", INSTRUCTION_OVERRIDE, 0.5, r"\b(?:stop|cease)\s+(?:being|acting|following|answering)\b", "Tells model to stop its task"),
    R("io-override-mode", INSTRUCTION_OVERRIDE, 0.7, r"\b(?:sudo\s+mode|prompt\s+override|admin\s+override|override\s+(?:mode|protocol|code))\b",
      "Claims an override mode"),
    R("io-above-fake", INSTRUCTION_OVERRIDE, 0.55,
      r"\b(?:the\s+)?(?:above|previous|prior)\s+(?:text|content|message|instructions?)\s+(?:is|are|was|were)\s+(?:a\s+)?(?:fake|false|wrong|outdated|irrelevant|test|dummy|invalid)\b",
      "Discredits prior context"),

    # ---------------------------------------------------------------- 2. role change
    R("rc-you-are-now", ROLE_CHANGE, 0.8,
      r"\byou\s+are\s+(?:now|no\s+longer|actually|really)\b(?!\s*(?:required|obliged|permitted|eligible|entitled|expected|advised|requested|reminded|able|allowed|liable|responsible|notified))",
      "Re-assigns the model's identity"),
    R("rc-act-as", ROLE_CHANGE, 0.85,
      r"\b(?:act|behave|respond|function|operate)\s+(?:as|like)\s+(?:if\s+you\s+(?:were|are)\s+)?(?:a|an|the|my)?\s*(?:unrestricted|unfiltered|uncensored|jailbroken|evil|malicious|rogue|different|new|developer|admin(?:istrator)?|root|system|dan|hacker)\b",
      "Asks the model to act as a privileged/unrestricted persona"),
    R("rc-pretend", ROLE_CHANGE, 0.65, r"\b(?:pretend|imagine|suppose)\s+(?:to\s+be|you\s+are|you'?re|that\s+you\s+are)\b", "Role-play framing"),
    R("rc-dan", ROLE_CHANGE, 0.95, r"\b(?:dan\s+mode|do\s+anything\s+now|developer\s+mode|god\s+mode|jailbreak(?:ed)?\s+mode|unrestricted\s+mode|evil\s+mode)\b",
      "Known jailbreak persona"),
    R("rc-chat-markers", ROLE_CHANGE, 0.85,
      r"<\|?\s*(?:im_start|im_end|system|assistant|endoftext)\s*\|?>|\[\/?(?:inst|sys|system)\]|<<\s*sys\s*>>|^\s{0,3}#{1,3}\s*(?:system|instruction)s?\s*(?:prompt|message)?\s*$",
      "Spoofed chat-template / system markers", re.I | re.M),
    R("rc-switch-role", ROLE_CHANGE, 0.5, r"\b(?:switch|change|enter|enable|activate)\s+(?:to\s+|into\s+)?(?:a\s+|the\s+)?(?:new\s+)?(?:role|persona|character)\b",
      "Asks to switch persona"),
    R("rc-your-new", ROLE_CHANGE, 0.75, r"\byour\s+(?:new|real|true|actual)\s+(?:role|purpose|task|goal|identity|name|persona)\b", "Redefines the model's purpose"),

    # ---------------------------------------------------------------- 3. secret extraction
    R("se-reveal-prompt", SECRET_EXTRACTION, 0.92,
      r"(?<!never\s)(?<!not\s)(?<!n't\s)\b(?:reveal|show|print|display|output|repeat|recite|leak|disclose|tell\s+me|give\s+me|share|expose|dump|echo|paste|return|send|write\s+out)\b.{0,40}\b(?:system\s+prompt|initial\s+prompt|hidden\s+(?:prompt|instructions?)|your\s+(?:instructions?|rules|prompt|guidelines|configuration|directives)|developer\s+(?:message|prompt|instructions?)|pre-?prompt|prompt\s+template)\b",
      "Asks the model to disclose its prompt/instructions", re.I | re.S),
    R("se-what-instr", SECRET_EXTRACTION, 0.7, r"\bwhat\s+(?:are|were|is)\s+(?:your|the)\s+(?:initial|original|system|hidden|secret|exact)\s+(?:instructions?|prompt|rules|guidelines)\b",
      "Probes for hidden instructions"),
    R("se-repeat-above", SECRET_EXTRACTION, 0.85, r"\brepeat\s+(?:everything|all|the\s+text|the\s+words)\s+(?:above|before|from\s+the\s+(?:start|beginning))\b",
      "Prefix-leak technique"),
    R("se-verbatim", SECRET_EXTRACTION, 0.6,
      r"\b(?:verbatim|word[\s-]for[\s-]word|exactly\s+as\s+written)\b.{0,60}\b(?:document|file|context|prompt|content|knowledge|policy|policies|controls?)\b",
      "Requests verbatim content dump", re.I | re.S),
    R("se-dump-all", SECRET_EXTRACTION, 0.8,
      r"\b(?:dump|list|print|show|reveal|export|exfiltrate|leak|extract|disclose)\b.{0,30}\b(?:all|entire|full|whole|every|complete|raw)\b.{0,30}\b(?:documents?|files?|knowledge\s*base|context|memory|database|records|policies|controls|regulations?|uploaded|contents?)\b",
      "Bulk exfiltration of stored documents", re.I | re.S),
    R("se-translate-prompt", SECRET_EXTRACTION, 0.8, r"\btranslate\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions)\b", "Translation-based prompt leak"),
    R("se-what-above", SECRET_EXTRACTION, 0.45, r"\bwhat\s+(?:was|is)\s+(?:written|said|stated)\s+(?:before|above)\b", "Prefix probing"),

    # ---------------------------------------------------------------- 4. tool abuse
    R("ta-call-tool-args", TOOL_ABUSE, 0.6, r"\b(?:call|invoke|execute|run|use)\s+(?:the\s+|your\s+)?(?:\w+\s+){0,2}(?:tool|function|plugin)\b.{0,40}\b(?:with|using)\s+(?:the\s+)?(?:arguments?|params?|parameters?|input)\b",
      "Directs a tool call with attacker arguments", re.I | re.S),
    R("ta-shell", TOOL_ABUSE, 0.92,
      r"\b(?:rm\s+-rf|chmod\s+(?:-r\s+)?777|mkfs|dd\s+if=|curl\s+[^|\n]{0,200}\|\s*(?:sudo\s+)?(?:ba)?sh|wget\s+[^|\n]{0,200}\|\s*(?:ba)?sh|nc\s+-[a-z]*e|bash\s+-i|powershell\s+-enc|cmd\.exe\s+/c|invoke-expression)|/bin/(?:ba)?sh\b",
      "Destructive / remote-execution shell command"),
    R("ta-sql", TOOL_ABUSE, 0.8, r"\b(?:drop\s+table|truncate\s+table|delete\s+from\s+\w+\s*(?:;|where\s+1\s*=\s*1)|union\s+select|xp_cmdshell)\b", "Destructive SQL"),
    R("ta-code-exec", TOOL_ABUSE, 0.6, r"\b(?:os\.system|subprocess\.(?:run|popen|call)|child_process|eval\s*\(|exec\s*\(|__import__\s*\(|Runtime\.getRuntime\(\)\.exec)",
      "Code-execution primitives", re.I, skip=("code",)),
    R("ta-exfil-send", TOOL_ABUSE, 0.85,
      r"\b(?:send|post|upload|forward|transmit|email|exfiltrate|leak)\b.{0,50}\b(?:to|at)\b\s+(?:https?://|[\w.+-]+@[\w-]+\.[\w.-]+|\d{1,3}(?:\.\d{1,3}){3})",
      "Sends data to an external destination", re.I | re.S),
    R("ta-you-delete", TOOL_ABUSE, 0.75, r"\byou\s+(?:must|should|will|shall|need\s+to|have\s+to|are\s+to)\b.{0,20}\b(?:delete|erase|wipe|purge|destroy|disable|deactivate)\b",
      "Directs destructive action", re.I | re.S),
    R("ta-delete-logs", TOOL_ABUSE, 0.6, r"\b(?:please\s+)?(?:delete|wipe|erase)\s+(?:all|every)\s+(?:the\s+)?(?:audit\s+logs?|logs?|backups?|files?|records)\b", "Evidence/log destruction"),
    R("ta-named-tool", TOOL_ABUSE, 0.85, r"\b(?:use|call|invoke)\s+(?:the\s+)?(?:send_?email|send_?mail|file_?write|write_?file|delete_?file|http_?request|execute_?code|run_?command)\b",
      "Names a privileged tool"),
    R("ta-json-call", TOOL_ABUSE, 0.8, r"\"(?:tool|function|name)\"\s*:\s*\"(?:send_email|delete\w*|exec\w*|shell|http\w*|fetch\w*|write_file|run\w*)\"", "Embedded function-call payload"),
    R("ta-transfer", TOOL_ABUSE, 0.85, r"\byou\s+(?:must|should|will|are\s+to)\s+(?:immediately\s+)?(?:approve|transfer|wire|send\s+(?:money|funds|payment)|pay)\b", "Financial action coercion"),

    # ---------------------------------------------------------------- 5. credential theft
    R("ct-send-creds", CREDENTIAL_THEFT, 0.85,
      IMP + r"(?:send|share|provide|give|reveal|print|show|output|leak|forward|email|post|include|append|return|tell)\b.{0,40}\b(?:passwords?|passwd|credentials?|api[\s_-]?keys?|secrets?|access\s+tokens?|auth(?:orization)?\s+tokens?|bearer\s+tokens?|private\s+keys?|ssh\s+keys?|session\s+(?:cookies?|tokens?)|otp|one[\s-]time\s+pass(?:word|code)|cvv|connection\s+strings?|environment\s+variables?|\.env)\b",
      "Imperative request for credentials/secrets", re.I | re.S | re.M),
    R("ct-your-creds", CREDENTIAL_THEFT, 0.8,
      r"(?<!never\s)(?<!not\s)(?<!n't\s)\b(?:what(?:'s|\s+is)|tell\s+me|give\s+me|show\s+me|reveal)\s+(?:me\s+)?(?:your|the\s+(?:admin|root|system))\s+(?:password|api[\s_-]?key|credentials?|token|secret)\b",
      "Asks the assistant for its own credentials"),
    R("ct-phish", CREDENTIAL_THEFT, 0.6, r"\b(?:verify|confirm|re-?enter|update)\s+your\s+(?:password|credentials|login|account|identity)\b|\b(?:log\s*in|sign\s*in)\s+(?:again\s+)?at\s+https?:",
      "Phishing-style credential harvesting"),
    R("ct-env-access", CREDENTIAL_THEFT, 0.75, r"process\.env|os\.environ|\bgetenv\(|/etc/(?:passwd|shadow)|\.ssh/id_rsa|\.aws/credentials",
      "Targets environment / key files", re.I, skip=("code",)),
    R("ct-secret-material", CREDENTIAL_THEFT, 0.5, r"\bAKIA[0-9A-Z]{16}\b|\bghp_[A-Za-z0-9]{36}\b|\bsk-[A-Za-z0-9]{20,}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
      "Live secret material present in content", 0),
    R("ct-md-exfil", CREDENTIAL_THEFT, 0.8, r"!\[[^\]]{0,80}\]\(\s*https?://[^)\s]{0,200}[?&][^)\s]{0,200}\)|<img[^>]{0,200}src\s*=\s*[\"']?https?://[^\"'>\s]{0,200}\?[^\"'>\s]{0,200}",
      "Markdown/HTML image used as a data-exfiltration channel"),

    # ---------------------------------------------------------------- 6. context poisoning
    R("cp-remember", CONTEXT_POISONING, 0.75,
      r"\b(?:remember|memorize|note|store|save)\s+(?:that|this|the\s+following)\b.{0,80}\b(?:always|from\s+now|in\s+(?:all\s+)?future|permanently|for\s+(?:all\s+)?(?:future|subsequent))\b",
      "Plants persistent false memory", re.I | re.S),
    R("cp-update-memory", CONTEXT_POISONING, 0.8, r"\b(?:update|overwrite|modify|rewrite|replace|alter|change)\s+(?:your|the|its)\s+(?:memory|knowledge|context|instructions?|system\s+prompt|conversation\s+history|baseline|ground\s+truth)\b",
      "Tampers with model memory/context"),
    R("cp-mark-compliant-soft", CONTEXT_POISONING, 0.28,
      r"\b(?:mark|set|record|report|treat|consider|classify|flag|rate)\b.{0,30}\bthe\b.{0,30}\b(?:controls?|obligations?|requirements?|gaps?|findings?)\b.{0,30}\b(?:as\s+)?(?:compliant|passed|satisfied|closed|resolved|effective)\b",
      "Possible assessment-outcome manipulation (weak signal)", re.I | re.S),
    R("cp-mark-compliant", CONTEXT_POISONING, 0.82,
      r"\b(?:mark|set|record|report|treat|consider|classify|flag|rate)\b.{0,30}\b(?:all|every|each)\b.{0,30}\b(?:controls?|obligations?|requirements?|gaps?|findings?|policies|documents?|sources?|content)\b.{0,30}\b(?:as\s+)?(?:compliant|passed|passing|satisfied|closed|resolved|effective|trusted|safe|approved|verified)\b",
      "Manipulates assessment outcomes (result poisoning)", re.I | re.S),
    R("cp-trusted-doc", CONTEXT_POISONING, 0.7,
      r"\b(?:this|the)\s+(?:document|file|message|email|page|content|text)\s+(?:is|has\s+been|was)\s+(?:verified|trusted|authori[sz]ed|approved|safe|pre-?approved|signed\s+off|official)\b.{0,60}\b(?:ignore|skip|bypass|no\s+need|do\s+not|don'?t|disregard|must|should)\b",
      "Self-asserted trust to bypass checks", re.I | re.S),
    R("cp-sys-note", CONTEXT_POISONING, 0.5, r"\b(?:system|admin(?:istrator)?|developer|security)\s+(?:note|notice|message|override|update|alert|directive)\s*[:\]\-]",
      "Fake privileged annotation"),
    R("cp-fake-dialog", CONTEXT_POISONING, 0.6, r"(?:^|\n)\s{0,3}(?:user|human|assistant|ai|bot|system)\s*:[^\n]{0,300}\n\s{0,3}(?:user|human|assistant|ai|bot|system)\s*:",
      "Forged conversation turns", re.I | re.M),
    R("cp-prev-wrong", CONTEXT_POISONING, 0.55, r"\b(?:previous|earlier|prior)\s+(?:analysis|assessment|summary|conclusion|answer|result)s?\s+(?:is|are|was|were)\s+(?:wrong|incorrect|outdated|invalid|void|superseded)\b",
      "Invalidates earlier analysis"),

    # ---------------------------------------------------------------- 7. multi-step jailbreak
    R("ms-steps", MULTI_STEP_JAILBREAK, 0.75,
      r"\b(?:step\s*1|first(?:ly)?)\b.{0,160}\b(?:step\s*2|second(?:ly)?|then|next|after\s+that)\b.{0,200}\b(?:ignore|disregard|bypass|reveal|override|jailbreak|unrestricted|without\s+(?:any\s+)?(?:restrictions?|filters?|limits?))\b",
      "Staged plan culminating in a bypass", re.I | re.S),
    R("ms-hypothetical", MULTI_STEP_JAILBREAK, 0.7,
      r"\b(?:hypothetical(?:ly)?|fictional|in\s+a\s+(?:story|novel|movie|game|simulation)|for\s+(?:educational|research|academic|testing)\s+purposes?\s+only|purely\s+theoretical|thought\s+experiment)\b.{0,120}\b(?:ignores?|bypass(?:es)?|reveals?|how\s+to\s+(?:hack|bypass|exploit|steal)|without\s+(?:any\s+)?(?:restrictions?|filters?|rules?)|no\s+(?:rules|restrictions|limits))\b",
      "Fiction/hypothetical framing to dodge safeguards", re.I | re.S),
    R("ms-game", MULTI_STEP_JAILBREAK, 0.5, r"\blet'?s\s+play\s+a\s+game\b", "Game framing"),
    R("ms-never-refuse", MULTI_STEP_JAILBREAK, 0.7, r"\b(?:never|don'?t|do\s+not)\s+(?:refuse|decline|say\s+no|apologi[sz]e|mention\s+(?:that\s+)?you\s+are\s+an?\s+ai)\b",
      "Suppresses refusals"),
    R("ms-staged-ack", MULTI_STEP_JAILBREAK, 0.6, r"\b(?:respond|answer|reply)\s+(?:only\s+)?with\s+[\"'“]?(?:ok|okay|understood|yes|confirmed|ready)[\"'”]?\b.{0,60}\b(?:then|after|next|and\s+wait)\b",
      "Staged acknowledgement before payload", re.I | re.S),
    R("ms-trigger", MULTI_STEP_JAILBREAK, 0.65, r"\bif\s+i\s+(?:say|type|write|send|use)\s+[\"'“]?[\w\s-]{1,30}[\"'”]?,?\s+(?:you\s+)?(?:will|must|should|then)\b", "Trigger-word backdoor"),
    R("ms-split", MULTI_STEP_JAILBREAK, 0.7, r"\b(?:combine|concatenate|join|merge)\s+(?:the\s+)?(?:parts?|fragments?|pieces?|strings?)\b.{0,80}\b(?:execute|run|follow|obey|do)\b",
      "Payload splitting", re.I | re.S),
    R("ms-part-marker", MULTI_STEP_JAILBREAK, 0.35, r"\b(?:part|fragment|piece)\s*[1-9]\s*(?:of\s*\d)?\s*[:=]", "Fragment marker (payload splitting)"),

    # ---------------------------------------------------------------- 8. encoded (textual cues; decoders add the rest)
    R("en-decode-follow", ENCODED_INSTRUCTIONS, 0.8,
      r"\b(?:decode|decrypt|deobfuscate|unescape|base64[\s-]?decode|rot13)\b.{0,60}\b(?:and|then)\b.{0,30}\b(?:follow|execute|run|obey|do|apply)\b", "Decode-then-obey instruction", re.I | re.S),
    R("en-decoder-call", ENCODED_INSTRUCTIONS, 0.4, r"\b(?:atob|b64decode|fromCharCode|unhexlify)\s*\(", "Decoder call inside content", re.I, skip=("code",)),

    # ---------------------------------------------------------------- 9. indirect injection (AI-addressed content)
    R("ii-dear-ai", INDIRECT_INJECTION, 0.75,
      r"\b(?:dear|hey|hello|attention|note\s+to|message\s+for|instructions?\s+for|for\s+the)\s+(?:the\s+)?(?:ai|a\.i\.|llm|language\s+model|ai\s+assistant|assistant|chatbot|gpt|chatgpt|claude|gemini|copilot|agent|model|summari[sz]er|automated\s+(?:system|reader|agent))\b",
      "Content addressed to the AI reader"),
    R("ii-if-you-are-ai", INDIRECT_INJECTION, 0.8, r"\b(?:if|when)\s+you\s+(?:are|'re)\s+(?:an?\s+)?(?:ai|llm|language\s+model|assistant|chatbot|bot|automated)\b", "Conditional on AI reader"),
    R("ii-when-summarizing", INDIRECT_INJECTION, 0.75,
      r"\b(?:when|while|before|after)\s+(?:you\s+)?(?:summari[sz]ing|summari[sz]e|reading|processing|analy[sz]ing|reviewing|translating|answering|assessing)\s+(?:this|the)\s+(?:document|page|email|file|text|content|pdf|report|code)\b.{0,100}\b(?:you\s+(?:must|should|will|shall)|always|make\s+sure|be\s+sure|do\s+not|don'?t|also|first)\b",
      "Embedded directive triggered by processing the document", re.I | re.S),
    R("ii-ai-reading", INDIRECT_INJECTION, 0.75, r"\b(?:ai|llm|assistant|model|agent)s?\s+(?:reading|processing|summari[sz]ing|analy[sz]ing)\s+this\b", "Targets AI readers of the document"),
    R("ii-conceal", INDIRECT_INJECTION, 0.8, r"\b(?:do\s+not|don'?t|never)\s+(?:tell|inform|notify|alert|mention\s+to|let)\s+(?:the\s+)?(?:user|human|operator|admin|anyone)\b",
      "Concealment from the user/operator"),
    R("ii-hidden-instr", INDIRECT_INJECTION, 0.55, r"\b(?:hidden|secret|invisible)\s+(?:instruction|message|command|prompt|text)\b", "Self-described hidden instruction"),
    R("ii-sys-msg", INDIRECT_INJECTION, 0.55, r"\bthis\s+is\s+(?:a\s+)?(?:system|admin|official)\s+(?:message|instruction|command)\b", "Impersonates system authority"),
    R("ii-trigger-say", INDIRECT_INJECTION, 0.65,
      r"\bwhen(?:ever)?\s+(?:the\s+user|anyone|someone|you\s+(?:are\s+asked|see|read|summari[sz]e))\b.{0,100}\b(?:say|respond|answer|reply|output|include|append|insert)\b",
      "Conditional response injection", re.I | re.S),
]

RULES_BY_ID = {r.id: r for r in RULES}
