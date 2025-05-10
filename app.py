import json
import requests
from bs4 import BeautifulSoup
import sys
import os

from flask import Flask, request, jsonify

app = Flask(__name__)

TEAMS = {
    "galatasaray": {"name": "Galatasaray", "slug": "galatasaray-istanbul", "id": "141"},
    "fenerbahçe": {"name": "Fenerbahçe", "slug": "fenerbahce-istanbul", "id": "36"},
    "beşiktaş": {"name": "Beşiktaş", "slug": "besiktas-istanbul", "id": "114"},
    "trabzonspor": {"name": "Trabzonspor", "slug": "trabzonspor", "id": "449"},
    "göztepe": {"name": "Göztepe", "slug": "goztepe", "id": "1467"},
    "başakşehir": {"name": "Başakşehir", "slug": "istanbul-basaksehir-fk", "id": "6890"},
    "rizespor": {"name": "Ç. Rizespor", "slug": "caykur-rizespor", "id": "126"},
    "samsunspor": {"name": "Samsunspor", "slug": "samsunspor", "id": "152"},
    "kasımpaşa": {"name": "Kasımpaşa", "slug": "kasimpasa", "id": "10484"},
    "eyüpspor": {"name": "Eyüpspor", "slug": "eyupspor", "id": "7160"},
    "alanyaspor": {"name": "Alanyaspor", "slug": "alanyaspor", "id": "11282"},
    "antalyaspor": {"name": "Antalyaspor", "slug": "antalyaspor", "id": "589"},
    "gaziantep": {"name": "Gaziantep FK", "slug": "gaziantep-fk", "id": "2832"},
    "bodrum": {"name": "Bodrum FK", "slug": "bodrumspor", "id": "44006"},
    "konyaspor": {"name": "Konyaspor", "slug": "konyaspor", "id": "2293"},
    "hatayspor": {"name": "Hatayspor", "slug": "hatayspor", "id": "7775"},
    "kayserispor": {"name": "Kayserispor", "slug": "kayserispor", "id": "3205"},
    "sivasspor": {"name": "Sivasspor", "slug": "sivasspor", "id": "2381"},
    "adana demirspor": {"name": "Adana Demirspor", "slug": "adana-demirspor", "id": "3840"}
}

def get_team_info(team_key):
    team_key = team_key.lower()
    if team_key in TEAMS:
        return TEAMS[team_key]
    else:
        raise ValueError(f"{team_key} takımı bulunamadı. Geçerli takımlar: {list(TEAMS.keys())}")

HEADERS = {"User-Agent": "Mozilla/5.0"}

def get_soup(url):
    res = requests.get(url, headers=HEADERS)
    res.raise_for_status()
    return BeautifulSoup(res.text, "lxml")

def scrape_squad(URL_SQUAD):
    soup = get_soup(URL_SQUAD)
    table = soup.find("table", class_="items")
    rows = table.find_all("tr", class_=["odd", "even"])

    players = []
    for row in rows:
        name = row.find("td", class_="hauptlink").text.strip()
        position = row.find_all("td")[4].text.strip()
        market_value_td = row.find_all("td")[-1]
        market_value = market_value_td.text.strip() if market_value_td else "N/A"

        players.append({
            "name": name,
            "position": position,
            "market_value": market_value
        })

    return players

def scrape_injuries(URL_INJURIES, squad):
    try:
        soup_inj = get_soup(URL_INJURIES)
        injuries = []

        inj_header = soup_inj.find('td', string="Sakatlıklar")
        if inj_header:
            row = inj_header.find_parent('tr')
            next_row = row.find_next_sibling()
            while next_row and 'extrarow' not in (next_row.get('class') or []):
                table_inline = next_row.find('table', class_='inline-table')
                if table_inline:
                    name_tag = table_inline.find('a', href=True)
                    if name_tag:
                        player_name = name_tag.get_text(strip=True)
                        matched = next((p for p in squad if p["name"] == player_name), None)
                        position = matched["position"] if matched else player_name
                        injuries.append({
                            "name": player_name,
                            "position": position
                        })
                next_row = next_row.find_next_sibling()
        return injuries
    except Exception as e:
        print(f"Sakat/Cezalı oyuncu verisi alınamadı: {e}", file=sys.stderr)
        return []

def get_league_position(TEAM_NAME):
    try:
        URL_LEAGUE = "https://www.transfermarkt.com.tr/super-lig/tabelle/wettbewerb/TR1"
        soup = get_soup(URL_LEAGUE)
        table = soup.find('table', class_='items')
        rows = table.find('tbody').find_all('tr', recursive=False)
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 3:
                continue
            pos_text = cells[0].get_text(strip=True)
            name_text = cells[2].get_text(strip=True)
            if name_text.lower() == TEAM_NAME.lower():
                return int(pos_text) if pos_text.isdigit() else pos_text
        return None
    except Exception as e:
        print(f"Lig sıralaması alınamadı: {e}", file=sys.stderr)
        return None

def get_recent_form(TEAM_NAME):
    try:
        URL_FORM = "https://www.transfermarkt.com.tr/super-lig/formtabelle/wettbewerb/TR1/"
        res = requests.get(URL_FORM, headers=HEADERS)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "lxml")
        form_rows = soup.select("div.responsive-table table tbody tr")
        for row in form_rows:
            team_cell = row.select_one("td.no-border-links.hauptlink a")
            if team_cell and TEAM_NAME.lower() in team_cell.text.lower():
                tds = row.find_all("td")
                wins = int(tds[4].get_text(strip=True))
                draws = int(tds[5].get_text(strip=True))
                losses = int(tds[6].get_text(strip=True))
                form_spans = tds[10].find_all("span")
                recent_results = [s.get_text(strip=True) for s in form_spans if s.get_text(strip=True) in ["G", "B", "M"]]
                return {
                    "wins": wins,
                    "draws": draws,
                    "losses": losses,
                    "last_matches": recent_results
                }
        return {}
    except Exception as e:
        print(f"Form verisi alınamadı: {e}", file=sys.stderr)
        return {}

@app.route("/generate-json", methods=["POST"])
def generate_json_api():
    data = request.get_json()
    team_key = data.get("team")

    if not team_key:
        return jsonify({"error": "Takım adı belirtilmeli."}), 400

    try:
        team_info = get_team_info(team_key)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    TEAM_NAME = team_info["name"]
    TEAM_SLUG = team_info["slug"]
    TEAM_ID = team_info["id"]

    URL_SQUAD = f"https://www.transfermarkt.com.tr/{TEAM_SLUG}/startseite/verein/{TEAM_ID}"
    URL_INJURIES = f"https://www.transfermarkt.com.tr/{TEAM_SLUG}/sperrenundverletzungen/verein/{TEAM_ID}"

    squad = scrape_squad(URL_SQUAD)
    data = {
        "team": TEAM_NAME,
        "position_in_league": get_league_position(TEAM_NAME),
        "recent_form": get_recent_form(TEAM_NAME),
        "injuries": scrape_injuries(URL_INJURIES, squad),
        "squad": squad
    }

    filename = f"{TEAM_NAME.lower()}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ {filename} oluşturuldu.")
    return jsonify({"message": f"{filename} başarıyla oluşturuldu."}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
