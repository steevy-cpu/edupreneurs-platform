"""Emit a Maestro flow for one fresh local app session. Uses synthetic seed data."""

import json
import sys
from pathlib import Path

lang, cell = sys.argv[1:]
assert lang in {"fr", "ht"}
fr = lang == "fr"
commands = [
    {"launchApp": {"clearState": True}},
    {"extendedWaitUntil": {"visible": {"id": "sign-in-email"}, "timeout": 90000}},
    {"tapOn": {"id": "sign-in-email"}},
    {"inputText": "student.a@edupreneur.test"},
    {"tapOn": {"id": "sign-in-password"}},
    {"inputText": "${PASS_A}"},
    "hideKeyboard",
    {"tapOn": {"id": "sign-in-submit"}},
    {"extendedWaitUntil": {"visible": {"id": "tab-profile"}, "timeout": 60000}},
]


def reach(selector):
    return {"scrollUntilVisible": {"element": selector, "direction": "DOWN", "timeout": 15000}}


def shot(label):
    return {"takeScreenshot": str(Path(cell) / label)}


if not fr:
    commands.extend([
        {"tapOn": {"id": "tab-profile"}},
        reach({"text": "Kreyòl"}),
        {"tapOn": "Kreyòl"},
        {"assertVisible": "Pwofil"},
    ])

practice = "Faire les exercices" if fr else "Fè egzèsis yo"
validate = "Valider" if fr else "Valide"
subject = "Mathématiques" if fr else "Matematik"
commands.extend([
    {"tapOn": {"id": "tab-home"}},
    shot("home"),
    {"tapOn": {"id": "tab-learn"}},
    reach({"text": "9AF"}), {"tapOn": "9AF"},
    reach({"text": subject}), {"tapOn": subject},
    reach({"id": "read-1"}), shot("learn"), {"tapOn": {"id": "read-1"}},
    {"extendedWaitUntil": {"visible": "En ligne · non téléchargée" if fr else "Sou entènèt · pa telechaje", "timeout": 25000}},
    shot("reader"), reach({"text": practice}), {"tapOn": practice},
    reach({"text": "x = 7"}), {"tapOn": "x = 7"},
    reach({"text": validate}), {"tapOn": validate},
    reach({"text": ".*" + ("Réponse enregistrée sur ce téléphone" if fr else "Repons lan anrejistre sou telefòn sa a") + ".*"}),
    shot("quiz"),
    "stopApp", {"launchApp": {"clearState": False}},
    {"extendedWaitUntil": {"visible": {"id": "tab-review"}, "timeout": 45000}},
    {"tapOn": {"id": "tab-review"}},
    reach({"text": ".*" + ("Résoudre une équation simple" if fr else "Rezoud yon ekwasyon senp") + ".*"}),
    shot("review"),
])
# Maestro's YAML parser accepts JSON as a document. Do not serialize credentials.
print("appId: ht.edupreneur.student.dev\n---")
print(json.dumps(commands, ensure_ascii=False))
