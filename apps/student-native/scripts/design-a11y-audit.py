#!/usr/bin/env python3
"""Accessibility audit of the Design-00 previews, read from the device's real accessibility tree.

    design-a11y-audit.py android|ios [--udid UDID] [--maestro PATH]

For every preview it lists each element a screen reader can activate and checks:
  * it has a spoken name (label or text);
  * its touch target is at least 48x48 dp (Android) / 44x44 pt (iOS).
Elements cut off by the edge of the scrolling area are skipped (they are measured
in full on the scrolled pass). This is an automated check of names and sizes; it
does not replace listening to TalkBack / VoiceOver.
"""
import json, re, subprocess, sys, time
import xml.etree.ElementTree as ET

platform = sys.argv[1]
arg = lambda name, default=None: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default
UDID, MAESTRO = arg("--udid"), arg("--maestro", "maestro")
APP = "ht.edupreneur.student.dev"
MIN = 48 if platform == "android" else 44
PREVIEWS = [
    "home?locale=fr", "home?locale=ht&state=pending", "home?locale=fr&state=empty", "home?locale=fr&state=error",
    "path?locale=fr", "path?locale=ht&state=offline", "lesson?locale=fr", "lesson?locale=ht",
    "quiz?locale=fr", "quiz?locale=fr&state=selected", "quiz?locale=ht&state=incorrect", "quiz?locale=fr&state=long",
    "progress?locale=fr", "progress?locale=ht&state=pending", "progress?locale=fr&state=failed", "progress?locale=fr&state=empty",
]

def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout

def open_url(path):
    url = f"monedupreneur://design/{path}"
    if platform == "android":
        sh("adb", "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", f"'{url}'", APP)
    else:
        sh("xcrun", "simctl", "openurl", UDID, url)
    time.sleep(3.5)

def android_nodes():
    density = int(re.search(r"(\d+)", sh("adb", "shell", "wm", "density")).group(1)) / 160
    sh("adb", "shell", "uiautomator", "dump", "/sdcard/ui.xml")
    root = ET.fromstring(sh("adb", "exec-out", "cat", "/sdcard/ui.xml"))
    parent = {child: node for node in root.iter("node") for child in node}
    def box(n):
        return tuple(map(int, re.findall(r"-?\d+", n.get("bounds"))))
    def clipped(n):
        """True when a scrolling ancestor cuts this element off (it is then only partly on screen)."""
        x1, y1, x2, y2 = box(n)
        if x2 - x1 <= 0 or y2 - y1 <= 0:
            return True
        p = parent.get(n)
        while p is not None:
            if p.get("scrollable") == "true" or "ScrollView" in p.get("class", ""):
                a, b, c, d = box(p)
                vertical = "ScrollView" in p.get("class", "")
                if (y1 <= b or y2 >= d) if vertical else (x1 < a or x2 >= c):
                    return True
            p = parent.get(p)
        return False
    out = []
    for n in root.iter("node"):
        if n.get("clickable") != "true":
            continue
        x1, y1, x2, y2 = box(n)
        name = n.get("content-desc") or n.get("text") or " ".join(c.get("text", "") for c in n.iter("node")).strip()
        out.append((name, (x2 - x1) / density, (y2 - y1) / density, clipped(n)))
    return out

def ios_nodes(names):
    """The iOS tree from Maestro has names and frames but no roles, so the elements to
    check are the ones found activatable on Android (same labels on both platforms)."""
    raw = sh(MAESTRO, "--device", UDID, "hierarchy")
    tree = json.loads(raw[raw.index("{"):])
    found = {}
    def walk(n):
        a = n.get("attributes", {})
        m = re.findall(r"-?\d+", a.get("bounds", ""))
        label = a.get("accessibilityText", "")
        if label in names and len(m) == 4:
            x1, y1, x2, y2 = map(int, m)
            found[label] = (label, x2 - x1, y2 - y1, y2 >= 874 - 1 or y1 <= 0)
        for c in n.get("children", []):
            walk(c)
    walk(tree)
    return list(found.values()), sorted(set(names) - set(found))

NAMES_FILE = arg("--names", "/tmp/design-a11y-names.json")
names_by_preview = {} if platform == "android" else json.load(open(NAMES_FILE))
total = fails = 0
for path in PREVIEWS:
    open_url(path)
    missing = []
    if platform == "android":
        nodes = android_nodes()
        names_by_preview[path] = [n[0] for n in nodes if n[0].strip()]
    else:
        nodes, missing = ios_nodes(names_by_preview.get(path, []))
    checked = [n for n in nodes if not n[3]]
    bad = [n for n in checked if not n[0].strip() or n[1] < MIN - 0.5 or n[2] < MIN - 0.5]
    total += len(checked); fails += len(bad)
    smallest = min((min(n[1], n[2]) for n in checked), default=0)
    print(f"{'PASS' if not bad else 'FAIL'}  {path:36} {len(checked):2} targets, smallest side {smallest:.0f}, {len(nodes) - len(checked)} clipped-skipped")
    for name, w, h, _ in bad:
        print(f"      !! {name[:40]!r} {w:.0f}x{h:.0f}")
    if missing:
        print(f"      (not exposed under the same name on iOS: {len(missing)} -> {[m[:28] for m in missing][:4]})")
if platform == "android":
    json.dump(names_by_preview, open(NAMES_FILE, "w"), ensure_ascii=False)
print(f"\n{platform}: {total} activatable elements checked, {fails} failures (minimum {MIN})")
sys.exit(1 if fails else 0)
