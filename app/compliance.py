"""금칙어·규제 검사. LLM이 아니라 규칙 파일 기반 결정론적 검사다."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "knowledge" / "rules.json"


def load_rules() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def strip_html(text: str) -> str:
    if "<" not in text:
        return text
    p = _TextExtractor()
    p.feed(text)
    return " ".join(p.parts)


def check(text: str, profile: str = "b2c-goods", scope: str = "section") -> dict:
    """본문을 검사해 위반 목록과 누락된 필수 항목을 돌려준다.

    scope="full_page"일 때만 상품정보제공고시 등 필수 블록 존재 여부를 본다.
    """
    rules = load_rules()
    plain = strip_html(text)
    lowered = plain.lower()

    violations = []
    for rule in rules["word_rules"]:
        for pattern in rule["patterns"]:
            for m in re.finditer(re.escape(pattern), plain, flags=re.IGNORECASE):
                violations.append(
                    {
                        "rule_id": rule["id"],
                        "severity": rule["severity"],
                        "label": rule["label"],
                        "matched": m.group(0),
                        "span": [m.start(), m.end()],
                        "context": plain[max(0, m.start() - 25) : m.end() + 25].strip(),
                        "why": rule["why"],
                        "suggest": rule["suggest"],
                    }
                )

    missing = []
    if scope == "full_page":
        blocks = list(rules["required_blocks"]["all"])
        blocks += rules["required_blocks"].get(profile, [])
        for block in blocks:
            if not any(k.lower() in lowered for k in block["any_of"]):
                missing.append({"id": block["id"], "label": block["label"]})

    blocking = [v for v in violations if v["severity"] == "block"]
    return {
        "passed": not blocking and not missing,
        "checked_chars": len(plain),
        "rules_applied": len(rules["word_rules"]),
        "violations": violations,
        "block_count": len(blocking),
        "warn_count": len(violations) - len(blocking),
        "missing_required": missing,
        "profile": profile,
        "scope": scope,
    }


def check_product_name(name: str) -> dict:
    """상품명 50자·허용 특수문자 규격 검사."""
    spec = load_rules()["listing_spec"]
    allowed = set(spec["product_name_allowed_symbols"])
    bad = sorted(
        {
            ch
            for ch in name
            if not ch.isalnum() and not ch.isspace() and ch not in allowed
        }
    )
    return {
        "length": len(name),
        "max": spec["product_name_max_chars"],
        "length_ok": len(name) <= spec["product_name_max_chars"],
        "disallowed_symbols": bad,
        "passed": len(name) <= spec["product_name_max_chars"] and not bad,
    }
