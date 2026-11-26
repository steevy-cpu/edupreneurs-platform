"""Safeguarding checks that run BEFORE any text leaves the server, and after a model answers.

This is a deterministic first line, not a complete child-safety system:

* it recognises a small set of unambiguous phrases in French, Haitian Creole
  and English, in the first person where that matters;
* it never blocks a school subject because of a word (biology, literature and
  history lessons mention the body, death and violence);
* anything it flags is answered with a fixed message written by people, so a
  model never improvises around a child in distress.

Real learner launch needs policy and legal review, reviewed wording by native
speakers, verified local support contacts, and a model-based classifier
evaluated on real (consented) data. See docs/jude-01/05-safety-and-privacy.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from edu_api.tutor.text import normalize
from edu_api.tutor.types import Locale, NextAction, Notice


class ScreenAction(StrEnum):
    ALLOW = "allow"
    #: Possible danger, abuse or self-harm: reviewed supportive message, no model call.
    SAFETY_SUPPORT = "safety_support"
    #: Attempt to change Jude's rules or extract its instructions.
    DECLINE_MANIPULATION = "decline_manipulation"
    #: Request that is not suitable for a school helper.
    DECLINE_INAPPROPRIATE = "decline_inappropriate"


@dataclass(frozen=True)
class ScreenResult:
    action: ScreenAction
    #: The message with contact details removed; what retrieval and the model may see.
    text: str | None
    personal_info_removed: bool = False


def _any(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns))


# All patterns run on ``normalize()`` output: lower case, no accents, straight apostrophes.
_SAFETY_CONCERN = _any(
    # --- self-harm, first person (French) ---
    r"\bme suicider\b",
    r"\bje (?:vais|veux|voudrais|pense a) (?:me )?(?:tuer|suicid\w*|mourir|en finir)\b",
    r"\b(?:envie|j'ai envie) de (?:mourir|me tuer|me suicider|en finir)\b",
    r"\bme faire du mal\b",
    r"\bme scarifi\w*",
    r"\bje ne veux plus vivre\b",
    # --- abuse or danger, first person (French) ---
    r"\b(?:on|il|elle|ils|mon \w+|ma \w+) me (?:frappe|frappent|bat|battent|touche|viole|menace)\b",
    r"\bj'ai ete (?:viole|violee|agresse|agressee|abuse|abusee)\b",
    r"\bj'ai peur de rentrer (?:chez moi|a la maison)\b",
    r"\bje suis en danger\b",
    r"\bon veut me (?:tuer|kidnapper|enlever)\b",
    # --- self-harm, first person (Haitian Creole) ---
    r"\btouye tet (?:mwen|m)\b",
    r"\b(?:mwen|m) (?:vle|anvi|ta renmen) mouri\b",
    r"\b(?:mwen|m) pa vle viv anko\b",
    r"\bfe tet (?:mwen|m) mal\b",
    r"\bfe swisid\b",
    # --- abuse or danger, first person (Haitian Creole) ---
    r"\b(?:y ap|yo|li|l ap|papa m|manman m|tonton m) (?:ap )?"
    r"(?:bat|frape|manyen|vyole|menase) (?:mwen|m)\b",
    r"\byo (?:fe|fè) kadejak sou (?:mwen|m)\b",
    r"\b(?:mwen|m) an danje\b",
    r"\b(?:mwen|m) pe (?:tounen|rantre) lakay\b",
    r"\byo vle (?:touye|kidnape) (?:mwen|m)\b",
    # --- English ---
    r"\bkill myself\b",
    r"\bi want to die\b",
    r"\bhurt myself\b",
    r"\bend my life\b",
    r"\b(?:he|she|they|someone) (?:hits|beats|touches|raped|abuses) me\b",
)

_MANIPULATION = _any(
    r"\b(?:ignore|oublie|oubliez|bliye|inyore)\b.{0,40}\b(?:instructions?|consignes?|regles?|enstriksyon|reg)\b",
    r"\b(?:ignore|forget|disregard)\b.{0,40}\b(?:instructions?|rules?|prompt)\b",
    r"\b(?:system|systeme|sistem) ?prompt\b",
    r"\bprompt (?:systeme|system)\b",
    r"\b(?:revele|montre|affiche|repete|montre m|di m)\b.{0,30}"
    r"\b(?:tes|vos|ou) ?(?:instructions|consignes|enstriksyon)\b",
    r"\b(?:reveal|show|print|repeat)\b.{0,30}\b(?:your )?(?:instructions|system prompt|rules)\b",
    r"\b(?:tu es|you are|ou se) (?:maintenant|now|kounye a)\b",
    r"\b(?:developer|developpeur) mode\b",
    r"\bmode (?:developpeur|dan)\b",
    r"\bjailbreak\b",
    r"\bdo anything now\b",
)

_INAPPROPRIATE = _any(
    r"\bporn\w*",
    r"\b(?:photos?|images?|videos?|foto|videyo) (?:nus?|nues?|toutouni|de nus?|sexy)\b",
    r"\b(?:envoie|voye|send)\b.{0,20}\b(?:nudes?|photos? nue?s?)\b",
    r"\b(?:fabriquer|faire|construire|fe|fabrike|make|build)\b.{0,20}"
    r"\b(?:une |yon |a )?(?:bombe|bonm|bomb|explosifs?|eksplozif)\b",
    r"\b(?:acheter|trouver|achte|jwenn|buy)\b.{0,20}"
    r"\b(?:une arme|un pistolet|zam|yon zam|a gun|de la drogue|dwog)\b",
    r"\b(?:comment|kijan|how to)\b.{0,20}\b(?:tuer quelqu'un|touye yon moun|kill someone)\b",
    r"\b(?:pirater|hacker|hack|pirate)\b.{0,30}"
    r"\b(?:compte|kont|account|mot de passe|password|modpas)\b",
)

# Contact details are removed on the ORIGINAL text (they survive normalisation poorly).
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_PHONE_PREFIXED = re.compile(r"(?:\+|00)\s?\d{1,3}[\s.-]?(?:\d[\s.-]?){7,11}\d")
_PHONE_GROUPED = re.compile(r"\b\d{4}[\s.-]\d{4}\b|\b\d{2}(?:[\s.-]\d{2}){3}\b")
_PHONE_CUE = re.compile(
    r"\b(?:telephone|telefon|tel|numero|nimewo|whatsapp|appelle|rele m|rele mwen|call me|"
    r"portable|cell)\b"
)
REDACTED = "[…]"


def redact_contact_details(text: str) -> tuple[str, bool]:
    """Remove e-mail addresses, links and phone numbers from a student's message.

    A bare group of digits is only treated as a phone number next to a cue word
    ("mon numéro", "nimewo m", "WhatsApp") or an international prefix:
    mathematics questions are full of numbers and must pass untouched.
    """
    redacted = _EMAIL.sub(REDACTED, text)
    redacted = _URL.sub(REDACTED, redacted)
    redacted = _PHONE_PREFIXED.sub(REDACTED, redacted)
    if _PHONE_CUE.search(normalize(redacted)):
        redacted = _PHONE_GROUPED.sub(REDACTED, redacted)
        redacted = re.sub(r"\b\d{8}\b", REDACTED, redacted)
    return redacted, redacted != text


def screen_student_message(message: str | None) -> ScreenResult:
    """Classify a student's message. Order matters: safety first, always."""
    if message is None:
        return ScreenResult(ScreenAction.ALLOW, None)
    normalized = normalize(message)
    if _SAFETY_CONCERN.search(normalized):
        return ScreenResult(ScreenAction.SAFETY_SUPPORT, None)
    if _MANIPULATION.search(normalized):
        return ScreenResult(ScreenAction.DECLINE_MANIPULATION, None)
    if _INAPPROPRIATE.search(normalized):
        return ScreenResult(ScreenAction.DECLINE_INAPPROPRIATE, None)
    text, removed = redact_contact_details(message)
    return ScreenResult(ScreenAction.ALLOW, text, personal_info_removed=removed)


# --- model output ------------------------------------------------------------------
_OUTPUT_CLAIMS = _any(
    r"\bj'ai (?:contacte|appele|prevenu|alerte)\b",
    r"\bje vais (?:contacter|appeler|prevenir|alerter)\b",
    r"\b(?:mwen|m) (?:rele|kontakte|aveti) (?:yon|polis|lapolis|paran|pwofese)\b",
    r"\b(?:mwen|m) (?:pral|ap) (?:rele|kontakte|aveti)\b",
    r"\bi (?:have|will|am going to) (?:contact|call|alert|notif)\w*\b",
)


def output_violations(text: str, *, canary: str) -> list[str]:
    """Reasons a model's student-facing text may not be shown. Empty means none found."""
    problems: list[str] = []
    if canary and canary in text:
        problems.append("system_prompt_leak")
    if _URL.search(text):
        problems.append("contains_link")
    if _EMAIL.search(text):
        problems.append("contains_email")
    if _PHONE_PREFIXED.search(text):
        problems.append("contains_phone")
    normalized = normalize(text)
    if _OUTPUT_CLAIMS.search(normalized):
        problems.append("claims_to_contact_someone")
    if _INAPPROPRIATE.search(normalized):
        problems.append("inappropriate_content")
    return problems


# --- reviewed fixed messages -----------------------------------------------------------
@dataclass(frozen=True)
class FixedMessage:
    text: str
    notice: Notice
    next_action: NextAction


#: Version of the fixed wording below. Change it whenever a message changes.
TEMPLATES_VERSION = "jude-fixed-messages.v1"

_SAFETY_SUPPORT: dict[Locale, str] = {
    "fr": (
        "Merci de me l'avoir dit. Ce que tu vis est important, et tu ne dois pas rester "
        "seul(e) avec ça. Parle dès maintenant à un adulte de confiance : un parent, un "
        "professeur ou une autre personne de ta famille. Si tu es en danger tout de suite, "
        "appelle les services d'urgence ou rejoins immédiatement un adulte qui peut t'aider. "
        "Je suis un assistant pour les leçons : je ne peux ni appeler quelqu'un ni envoyer "
        "de l'aide, mais je t'encourage à demander de l'aide aujourd'hui."
    ),
    "ht": (
        "Mèsi paske ou di m sa. Sa w ap viv la enpòtan, e ou pa dwe rete pou kont ou ak sa. "
        "Tanpri, pale kounye a ak yon granmoun ou fè konfyans: yon paran, yon pwofesè oswa "
        "yon lòt moun nan fanmi ou. Si ou an danje kounye a menm, rele sèvis ijans yo oswa "
        "ale touswit kote yon granmoun ki ka ede w. Mwen se yon asistan pou leson: mwen pa "
        "ka rele pèsonn ni voye èd, men mwen ankouraje w chèche èd jodi a."
    ),
}

_MANIPULATION_REPLY: dict[Locale, str] = {
    "fr": (
        "Je ne peux pas changer mes règles. Je suis là pour t'aider à comprendre cette "
        "leçon : quelle partie veux-tu revoir ?"
    ),
    "ht": (
        "Mwen pa ka chanje règ mwen yo. Mwen la pou m ede w konprann leson sa a: ki pati "
        "ou vle nou revize?"
    ),
}

_INAPPROPRIATE_REPLY: dict[Locale, str] = {
    "fr": (
        "Je ne peux pas t'aider avec cette demande. Je peux t'aider pour tes leçons et tes "
        "exercices."
    ),
    "ht": "Mwen pa ka ede w ak demann sa a. Mwen ka ede w ak leson ou yo ak egzèsis ou yo.",
}

_CONTROLLED_ASSESSMENT_REPLY: dict[Locale, str] = {
    "fr": (
        "Pendant une évaluation, je ne peux donner ni indices ni réponses. Bon courage ! "
        "Nous pourrons revoir la leçon ensemble après."
    ),
    "ht": (
        "Pandan yon evalyasyon, mwen pa ka bay ni endis ni repons. Kouraj! N a ka revize "
        "leson an ansanm apre."
    ),
}

_INSUFFICIENT_CONTEXT_REPLY: dict[Locale, str] = {
    "fr": (
        "Je ne trouve pas dans cette leçon de quoi répondre à cette question de façon "
        "fiable, et je préfère ne pas inventer. Essaie de la reformuler avec les mots de la "
        "leçon, ou pose-la à ton professeur."
    ),
    "ht": (
        "Mwen pa jwenn nan leson sa a ase enfòmasyon pou m reponn kesyon sa a yon fason ki "
        "fyab, e mwen pa vle envante. Eseye repoze l ak mo ki nan leson an, oswa mande "
        "pwofesè ou."
    ),
}


def safety_support_message(locale: Locale) -> FixedMessage:
    return FixedMessage(
        _SAFETY_SUPPORT[locale], Notice.SAFETY_CONCERN, NextAction.TALK_TO_TRUSTED_ADULT
    )


def manipulation_message(locale: Locale) -> FixedMessage:
    return FixedMessage(
        _MANIPULATION_REPLY[locale], Notice.INSTRUCTION_MANIPULATION, NextAction.ASK_FOLLOW_UP
    )


def inappropriate_message(locale: Locale) -> FixedMessage:
    return FixedMessage(_INAPPROPRIATE_REPLY[locale], Notice.INAPPROPRIATE_REQUEST, NextAction.NONE)


def controlled_assessment_message(locale: Locale) -> FixedMessage:
    return FixedMessage(
        _CONTROLLED_ASSESSMENT_REPLY[locale], Notice.CONTROLLED_ASSESSMENT, NextAction.NONE
    )


def insufficient_context_message(locale: Locale) -> FixedMessage:
    return FixedMessage(
        _INSUFFICIENT_CONTEXT_REPLY[locale],
        Notice.QUESTION_NOT_IN_LESSON,
        NextAction.REPHRASE_QUESTION,
    )
