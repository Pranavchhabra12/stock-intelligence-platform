"""Find which of our companies a headline or description is about.

Rules, strongest first:
- the company's name or legal name in the headline           -> 1.0
- another alias or its NSE symbol in the headline            -> 0.85
- any of the above only in the description                   -> 0.6
Abbreviations and symbols must match case-sensitively as whole words ("TCS",
"RIL"), so ordinary words don't trigger them. Phrases naming other companies
that share a word with ours ("Reliance Power", "HDFC Life") are removed first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

HEADLINE_NAME, HEADLINE_ALIAS, SNIPPET_ONLY = 1.0, 0.85, 0.6


@dataclass(frozen=True)
class Match:
    company_id: UUID
    score: float
    mention_type: str   # 'headline' or 'snippet'


@dataclass
class _CompanyPatterns:
    company_id: UUID
    names: re.Pattern | None      # case-insensitive full names
    aliases: re.Pattern | None    # other aliases; case-sensitive when they are abbreviations
    exclude: re.Pattern | None


def _alternation(terms: list[str], flags: int = 0) -> re.Pattern | None:
    terms = sorted({t for t in terms if t}, key=len, reverse=True)
    if not terms:
        return None
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(t) for t in terms) + r")(?![A-Za-z0-9])", flags)


class CompanyMatcher:
    def __init__(self, companies: list[dict]) -> None:
        """companies: dicts with company_id, names, abbreviations, other_aliases, exclude."""
        self._patterns = []
        for c in companies:
            alias_parts = [p for p in (
                _alternation(c.get("abbreviations", [])),                         # case-sensitive
                _alternation(c.get("other_aliases", []), re.IGNORECASE),
            ) if p]
            combined = re.compile("|".join(p.pattern if not p.flags & re.IGNORECASE else f"(?i:{p.pattern})"
                                           for p in alias_parts)) if alias_parts else None
            self._patterns.append(_CompanyPatterns(
                company_id=c["company_id"],
                names=_alternation(c.get("names", []), re.IGNORECASE),
                aliases=combined,
                exclude=_alternation(c.get("exclude", []), re.IGNORECASE),
            ))

    @classmethod
    def from_database(cls, conn: Connection) -> CompanyMatcher:
        rows = conn.execute(text(
            """
            select c.company_id, c.news_exclude_phrases,
                   array_agg(a.alias) filter (where a.alias_type in ('name', 'legal_name', 'former_name')) as names,
                   array_agg(a.alias) filter (where a.alias_type in ('abbreviation', 'symbol')) as abbreviations
            from app.companies c
            left join app.company_aliases a using (company_id)
            where c.is_active
            group by c.company_id
            """
        )).mappings()
        companies = []
        for r in rows:
            names = [n for n in (r["names"] or []) if len(n) >= 4]
            # One-word names such as "Reliance" or "Infosys" stay case-insensitive but are
            # weaker than full names, so they count as aliases.
            full = [n for n in names if " " in n]
            single = [n for n in names if " " not in n]
            abbreviations = [a for a in (r["abbreviations"] or []) if len(a) >= 3]
            abbreviations += [a.upper() for a in abbreviations]   # "Infy" and "INFY"
            companies.append({"company_id": r["company_id"], "names": full, "other_aliases": single,
                              "abbreviations": abbreviations, "exclude": list(r["news_exclude_phrases"] or [])})
        return cls(companies)

    def match(self, headline: str, snippet: str | None = None) -> list[Match]:
        results = []
        for p in self._patterns:
            h = p.exclude.sub(" ", headline) if p.exclude else headline
            s = snippet or ""
            s = p.exclude.sub(" ", s) if p.exclude else s
            if p.names and p.names.search(h):
                results.append(Match(p.company_id, HEADLINE_NAME, "headline"))
            elif p.aliases and p.aliases.search(h):
                results.append(Match(p.company_id, HEADLINE_ALIAS, "headline"))
            elif (p.names and p.names.search(s)) or (p.aliases and p.aliases.search(s)):
                results.append(Match(p.company_id, SNIPPET_ONLY, "snippet"))
        return results
