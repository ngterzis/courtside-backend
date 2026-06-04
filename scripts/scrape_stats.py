#!/usr/bin/env python3
"""
Scrape Λάσπη BC player stats from basketmaniacs.com.

Usage:
    pip install requests beautifulsoup4
    python scripts/scrape_stats.py
"""

import csv
import time

import requests
from bs4 import BeautifulSoup

TEAM_URL = "https://www.basketmaniacs.com/team/%ce%bb%ce%ac%cf%83%cf%80%ce%b7-bc/"
TEAM_NAME_FRAGMENT = "σπη"  # matches both Λάσπη (accented) and Λασπη
OUTPUT_FILE = "laspi_bc_stats.csv"
REQUEST_DELAY = 1.5  # seconds between requests to be polite

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

CSV_COLUMNS = [
    "date",
    "match",
    "score",
    "player",
    "pts",
    "fg2_made",
    "fg2_attempted",
    "fg3_made",
    "fg3_attempted",
    "ft_made",
    "ft_attempted",
    "ast",
    "stl",
    "blk",
    "reb_off",
    "reb_def",
    "to",
    "fls",
]


def fetch(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def get_matches(soup: BeautifulSoup) -> list[dict]:
    matches = []
    for row in soup.select("tr.sp-total-row"):
        date_td = row.select_one("td.data-date")
        match_td = row.select_one("td.data-match")
        result_td = row.select_one("td.data-result")
        if not (date_td and match_td):
            continue
        link = match_td.select_one("a")
        if not link:
            continue
        matches.append({
            "date": date_td.get_text(strip=True),
            "match": link.get_text(strip=True),
            "score": result_td.get_text(strip=True) if result_td else "",
            "url": link["href"],
        })
    return matches


def parse_player_row(row) -> dict | None:
    name_td = row.select_one("td.data-name")
    if not name_td:
        return None
    if not name_td.select_one("a[href*='/player/']"):
        return None  # skip team totals row

    def cell(css_class: str) -> str:
        td = row.select_one(f"td.{css_class}")
        return td.get_text(strip=True) if td else ""

    def split_ma(css_class: str) -> tuple[str, str]:
        raw = cell(css_class)
        if "/" in raw:
            made, attempted = raw.split("/", 1)
            return made.strip(), attempted.strip()
        return "", ""

    fg2_made, fg2_attempted = split_ma("data-fg")
    fg3_made, fg3_attempted = split_ma("data-threep")
    ft_made, ft_attempted = split_ma("data-ft")

    return {
        "player": name_td.get_text(strip=True),
        "pts": cell("data-pts"),
        "fg2_made": fg2_made,
        "fg2_attempted": fg2_attempted,
        "fg3_made": fg3_made,
        "fg3_attempted": fg3_attempted,
        "ft_made": ft_made,
        "ft_attempted": ft_attempted,
        "ast": cell("data-ast"),
        "stl": cell("data-stl"),
        "blk": cell("data-blk"),
        "reb_off": cell("data-reb-off"),
        "reb_def": cell("data-reb-def"),
        "to": cell("data-to"),
        "fls": cell("data-fls"),
    }


def get_team_player_stats(soup: BeautifulSoup) -> list[dict]:
    for caption in soup.select("h4.sp-table-caption"):
        if TEAM_NAME_FRAGMENT not in caption.get_text():
            continue
        section = caption.find_parent("div", class_="sp-template-event-performance")
        if not section:
            continue
        table = section.select_one("table.sp-data-table")
        if not table:
            continue
        rows = table.select("tr.sp-total-row")
        players = [parse_player_row(row) for row in rows]
        return [p for p in players if p]
    return []


def main() -> None:
    print(f"Fetching team page: {TEAM_URL}")
    team_soup = fetch(TEAM_URL)
    matches = get_matches(team_soup)
    print(f"Found {len(matches)} matches")

    rows: list[dict] = []
    for i, match in enumerate(matches, 1):
        print(f"[{i}/{len(matches)}] {match['date']}  {match['match']}  {match['score']}")
        time.sleep(REQUEST_DELAY)
        try:
            match_soup = fetch(match["url"])
            players = get_team_player_stats(match_soup)
            if not players:
                print(f"  WARNING: no Λάσπη BC stats found at {match['url']}")
                continue
            for player in players:
                rows.append({
                    "date": match["date"],
                    "match": match["match"],
                    "score": match["score"],
                    **player,
                })
            print(f"  {len(players)} players recorded")
        except Exception as e:
            print(f"  ERROR: {e}")

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. {len(rows)} player-game rows written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
