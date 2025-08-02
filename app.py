import json
import os
import sys
from typing import Dict, List

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, request, jsonify

import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

app = Flask(__name__)

# Firebase / Firestore başlatma
def init_firestore():
    if firebase_admin._apps:
        return firestore.client()

    raw_key = os.getenv("FIRESTORE_KEY")
    if not raw_key:
        raise RuntimeError("FIRESTORE_KEY env değişkeni tanımlı değil!")

    try:
        cred_dict = json.loads(raw_key)
    except json.JSONDecodeError:
        with open(raw_key, "r", encoding="utf-8") as f:
            cred_dict = json.load(f)

    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    return firestore.client()

DB = init_firestore()

TEAMS = {
    "everton": {"name": "Everton", "slug": "fc-everton", "id": "29"},
    "leeds": {"name": "Leeds", "slug": "leeds-united", "id": "399"},
    "brentford": {"name": "Brentford", "slug": "fc-brentford", "id": "1148"},
    "nottingham": {"name": "Nottingham", "slug": "nottingham-forest", "id": "703"},
    "crystal palace": {"name": "Crystal Palace", "slug": "crystal-palace", "id": "873"},
    "wolves": {"name": "Wolves", "slug": "wolverhampton-wanderers", "id": "543"},
    "burnley": {"name": "Burnley", "slug": "fc-burnley", "id": "1132"},
    "tottenham": {"name": "Tottenham", "slug": "tottenham-hotspur", "id": "148"},
    "west ham": {"name": "West Ham", "slug": "west-ham-united", "id": "379"},
    "sunderland": {"name": "Sunderland", "slug": "afc-sunderland", "id": "289"},
    "fulham": {"name": "Fulham", "slug": "fc-fulham", "id": "931"},
    "brighton": {"name": "Brighton", "slug": "brighton-amp-hove-albion", "id": "1237"},
    "newcastle": {"name": "Newcastle", "slug": "newcastle-united", "id": "762"},
    "aston villa": {"name": "Aston Villa", "slug": "aston-villa", "id": "405"},
    "liverpool": {"name": "Liverpool", "slug": "fc-liverpool", "id": "31"},
    "bournemouth": {"name": "Bournemouth", "slug": "afc-bournemouth", "id": "989"},
    "fc barcelona": {"name": "FC Barcelona", "slug": "fc-barcelona", "id": "131"},
    "real madrid": {"name": "Real Madrid", "slug": "real-madrid", "id": "418"},
    "man united": {"name": "Man United", "slug": "manchester-united", "id": "985"},
    "atlético madrid": {"name": "Atlético Madrid", "slug": "atletico-madrid", "id": "13"},
    "man city": {"name": "Man City", "slug": "manchester-city", "id": "281"},
    "chelsea": {"name": "Chelsea", "slug": "chelsea", "id": "631"},
    "dortmund": {"name": "Dortmund", "slug": "borussia-dortmund", "id": "16"},
    "sevilla fc": {"name": "Sevilla FC", "slug": "fc-sevilla", "id": "368"},
    "arsenal": {"name": "Arsenal", "slug": "fc-arsenal", "id": "11"},
    "bayern münih": {"name": "Bayern Münih", "slug": "bayern-muenchen", "id": "102"},
    "galatasaray": {"name": "Galatasaray", "slug": "galatasaray-istanbul", "id": "141"},
    "fenerbahçe": {"name": "Fenerbahçe", "slug": "fenerbahce-istanbul", "id": "36"},
    "beşiktaş": {"name": "Beşiktaş", "slug": "besiktas-istanbul", "id": "114"},
    "trabzonspor": {"name": "Trabzonspor", "slug": "trabzonspor", "id": "449"},
    "göztepe": {"name": "Göztepe", "slug": "goztepe", "id": "1467"},
    "başakşehir": {"name": "Başakşehir", "slug": "istanbul-basaksehir-fk", "id": "6890"},
    "ç. rizespor": {"name": "Ç. Rizespor", "slug": "caykur-rizespor", "id": "126"},
    "samsunspor": {"name": "Samsunspor", "slug": "samsunspor", "id": "152"},
    "kasımpaşa": {"name": "Kasımpaşa", "slug": "kasimpasa", "id": "10484"},
    "eyüpspor": {"name": "Eyüpspor", "slug": "eyupspor", "id": "7160"},
    "alanyaspor": {"name": "Alanyaspor", "slug": "alanyaspor", "id": "11282"},
    "antalyaspor": {"name": "Antalyaspor", "slug": "antalyaspor", "id": "589"},
    "gaziantep fk": {"name": "Gaziantep FK", "slug": "gaziantep-fk", "id": "2832"},
    "konyaspor": {"name": "Konyaspor", "slug": "konyaspor", "id": "2293"},
    "kayserispor": {"name": "Kayserispor", "slug": "kayserispor", "id": "3205"},
    "karagümrük": {"name": "Karagümrük", "slug": "fatih-karagumruk", "id": "6646"},
    "kocaelispor": {"name": "Kocaelispor", "slug": "kocaelispor", "id": "120"},
    "gençlerbirliği": {"name": "Gençlerbirliği", "slug": "genclerbirligi-ankara", "id": "820"},
}

HEADERS = {"User-Agent": "Mozilla/5.0"}

def get_team_info(team_key: str) -> dict:
    key = team_key.lower()
    if key not in TEAMS:
        raise ValueError(f"{team_key} takımı bulunamadı. Geçerli takımlar: {list(TEAMS.keys())}")
    return TEAMS[key]

def get_soup(url: str) -> BeautifulSoup:
    res = requests.get(url, headers=HEADERS, timeout=30)
    res.raise_for_status()
    return BeautifulSoup(res.text, "lxml")

def scrape_suspensions(team_slug, team_id, squad):
    try:
        url_squad = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}/saison_id/2025"
        soup = get_soup(url_squad)
        suspensions = []

        # Oyuncu tablosunu bul
        table = soup.find("table", class_="items")
        if not table:
            print(f"{team_slug} için oyuncu tablosu bulunamadı", file=sys.stderr)
            return suspensions

        # Oyuncu satırlarını tara (odd ve even sınıfları)
        rows = table.find_all("tr", class_=["odd", "even"])
        for row in rows:
            table_inline = row.find("table", class_="inline-table")
            if table_inline:
                name_tag = table_inline.find("a", href=True)
                if name_tag:
                    player_name = name_tag.get_text(strip=True)
                    span_tag = name_tag.find("span", class_=["ausfall-3-table", "ausfall-2-table"])
                    if span_tag:
                        suspension_type = span_tag.get("title", "").strip()
                        status = (
                            "Kırmızı Kart" if "Kırmızı kart cezalısı" in suspension_type else
                            "Sarı Kart" if "Sarı kart cezalısı" in suspension_type else
                            "Bilinmeyen Ceza"
                        )
                        matched = next((p for p in squad if p["name"] == player_name), None)
                        position = matched["position"] if matched else "Bilinmiyor"
                        suspensions.append({
                            "name": player_name,
                            "position": position,
                            "status": status,
                            "details": suspension_type
                        })

        return suspensions
    except Exception as e:
        print(f"Cezalılar veri hatası ({team_slug}): {e}", file=sys.stderr)
        return []

def scrape_squad(team_slug: str, team_id: str) -> List[dict]:
    url = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}"
    soup = get_soup(url)
    table = soup.find("table", class_="items")
    rows = table.find_all("tr", class_=["odd", "even"])
    players = []
    for row in rows:
        name = row.find("td", class_="hauptlink").text.strip()
        position = row.find_all("td")[4].text.strip()
        market_value = row.find_all("td")[-1].text.strip()
        players.append({"name": name, "position": position, "market_value": market_value})
    return players

def scrape_injuries(team_slug: str, team_id: str, squad: List[dict]) -> List[dict]:
    url = f"https://www.transfermarkt.com.tr/{team_slug}/sperrenundverletzungen/verein/{team_id}"
    injuries = []
    try:
        soup = get_soup(url)
        inj_header = soup.find("td", string="Sakatlıklar")
        if not inj_header:
            return injuries
        row = inj_header.find_parent("tr")
        next_row = row.find_next_sibling()
        while next_row and "extrarow" not in (next_row.get("class") or []):
            inline = next_row.find("table", class_="inline-table")
            if inline:
                name_tag = inline.find("a", href=True)
                if name_tag:
                    player_name = name_tag.get_text(strip=True)
                    matched = next((p for p in squad if p["name"] == player_name), None)
                    position = matched["position"] if matched else ""
                    injuries.append({"name": player_name, "position": position})
            next_row = next_row.find_next_sibling()
    except Exception as e:
        print(f"Sakatlık verisi alınamadı: {e}", file=sys.stderr)
    return injuries

def get_league_url(league_key: str) -> str | None:
    url_map = {
        "en1": "https://www.transfermarkt.com.tr/premier-league/tabelle/wettbewerb/GB1",
        "es1": "https://www.transfermarkt.com.tr/laliga/tabelle/wettbewerb/ES1",
        "de1": "https://www.transfermarkt.com.tr/bundesliga/tabelle/wettbewerb/L1",
        "tr1": "https://www.transfermarkt.com.tr/super-lig/tabelle/wettbewerb/TR1",
    }
    return url_map.get(league_key.lower())

def get_form_url(league_key: str) -> str | None:
    url_map = {
        "en1": "https://www.transfermarkt.com.tr/premier-league/formtabelle/wettbewerb/GB1",
        "es1": "https://www.transfermarkt.com.tr/laliga/formtabelle/wettbewerb/ES1",
        "de1": "https://www.transfermarkt.com.tr/bundesliga/formtabelle/wettbewerb/L1",
        "tr1": "https://www.transfermarkt.com.tr/super-lig/formtabelle/wettbewerb/TR1",
    }
    return url_map.get(league_key.lower())

def get_league_position(team_name: str, league_key: str):
    try:
        url = get_league_url(league_key)
        if not url:
            return None
        soup = get_soup(url)
        table = soup.find("table", class_="items")
        rows = table.find("tbody").find_all("tr", recursive=False)
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            pos = cells[0].text.strip()
            name = cells[2].text.strip()
            if name.lower() == team_name.lower():
                return int(pos) if pos.isdigit() else pos
        return None
    except Exception as e:
        print(f"Lig sıralaması alınamadı: {e}", file=sys.stderr)
        return None

def get_recent_form(team_name: str, league_key: str) -> dict:
    try:
        url = get_form_url(league_key)
        if not url:
            return {}
        soup = get_soup(url)
        rows = soup.select("div.responsive-table table tbody tr")
        for row in rows:
            team_cell = row.select_one("td.no-border-links.hauptlink a")
            if team_cell and team_name.lower() in team_cell.text.lower():
                tds = row.find_all("td")
                wins = int(tds[4].text.strip())
                draws = int(tds[5].text.strip())
                losses = int(tds[6].text.strip())
                form_spans = tds[10].find_all("span")
                recent_results = [s.text.strip() for s in form_spans if s.text.strip() in ["G", "B", "M"]]
                return {"wins": wins, "draws": draws, "losses": losses, "last_matches": recent_results}
        return {}
    except Exception as e:
        print(f"Form verisi alınamadı: {e}", file=sys.stderr)
        return {}

def generate_team_data(team_info: dict, league_key: str) -> tuple[dict, str]:
    name = team_info["name"]
    slug = team_info["slug"]
    team_id = team_info["id"]

    squad = scrape_squad(slug, team_id)
    injuries = scrape_injuries(slug, team_id, squad)
    position = get_league_position(name, league_key)
    form = get_recent_form(name, league_key)
    suspensions = scrape_suspensions(slug,team_id,squad)

    data = {
        "team": name,
        "position_in_league": position,
        "recent_form": form,
        "injuries": injuries,
        "suspensions": suspensions,
        "squad": squad
    }
    return data, name.lower()

def save_team_data(team_name: str, data: dict) -> None:
    try:
        DB.collection("team_data").document(team_name.lower()).set(data)
        print(f"✅ Firestore'a kaydedildi: {team_name}")
    except Exception as e:
        print(f"❌ Firestore kaydetme hatası ({team_name}): {e}", file=sys.stderr)
        
@app.route("/")
def index():
    return "API çalışıyor"

@app.route("/generate-json", methods=["POST"])
def generate_json_api():
    try:
        body = request.get_json()
        home_key = body.get("home_team")
        away_key = body.get("away_team")
        league_key = body.get("league_key")

        if not home_key or not away_key or not league_key:
            return jsonify({"error": "Eksik parametreler"}), 400

        home_info = get_team_info(home_key)
        away_info = get_team_info(away_key)

        home_data, home_doc = generate_team_data(home_info, league_key)
        away_data, away_doc = generate_team_data(away_info, league_key)

        save_team_data(home_doc, home_data)
        save_team_data(away_doc, away_data)

        return jsonify({
            "status": "success",
            "message": f"{home_doc}, {away_doc} Firestore'a kaydedildi."
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
