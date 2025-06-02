import json
import requests
from bs4 import BeautifulSoup
import sys
import os
import subprocess
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

TEAMS = {
    "galatasaray": {"name": "Galatasaray", "slug": "galatasaray-istanbul", "id": "141"},
    "fenerbahçe": {"name": "Fenerbahçe", "slug": "fenerbahce-istanbul", "id": "36"},
    "beşiktaş": {"name": "Beşiktaş", "slug": "besiktas-istanbul", "id": "114"},
    "trabzonspor": {"name": "Trabzonspor", "slug": "trabzonspor", "id": "449"},
    "göztepe": {"name": "Göztepe", "slug": "goztepe", "id": "1467"},
    "başakşehir": {"name": "Başakşehir", "slug": "istanbul-basaksehir-fk", "id": "6890  "},
    "ç. rizespor": {"name": "Ç. Rizespor", "slug": "caykur-rizespor", "id": "126"},
    "samsunspor": {"name": "Samsunspor", "slug": "samsunspor", "id": "152"},
    "kasımpaşa": {"name": "Kasımpaşa", "slug": "kasimpasa", "id": "10484"},
    "eyüpspor": {"name": "Eyüpspor", "slug": "eyupspor", "id": "7160"},
    "alanyaspor": {"name": "Alanyaspor", "slug": "alanyaspor", "id": "11282"},
    "antalyaspor": {"name": "Antalyaspor", "slug": "antalyaspor", "id": "589"},
    "gaziantep fk": {"name": "Gaziantep FK", "slug": "gaziantep-fk", "id": "2832"},
    "bodrum fk": {"name": "Bodrum FK", "slug": "bodrumspor", "id": "44006"},
    "konyaspor": {"name": "Konyaspor", "slug": "konyaspor", "id": "2293"},
    "hatayspor": {"name": "Hatayspor", "slug": "hatayspor", "id": "7775"},
    "kayserispor": {"name": "Kayserispor", "slug": "kayserispor", "id": "3205"},
    "sivasspor": {"name": "Sivasspor", "slug": "sivasspor", "id": "2381"},
    "adana demirspor": {"name": "Adana Demirspor", "slug": "adana-demirspor", "id": "3840"}
}

HEADERS = {"User-Agent": "Mozilla/5.0"}

def get_team_info(team_key):
    team_key = team_key.lower()
    if team_key in TEAMS:
        return TEAMS[team_key]
    else:
        raise ValueError(f"{team_key} takımı bulunamadı. Geçerli takımlar: {list(TEAMS.keys())}")

def get_soup(url):
    res = requests.get(url, headers=HEADERS)
    res.raise_for_status()
    return BeautifulSoup(res.text, "lxml")

def scrape_squad(team_slug, team_id):
    url_squad = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}"
    soup = get_soup(url_squad)
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

def scrape_injuries(team_slug, team_id, squad):
    try:
        url_injuries = f"https://www.transfermarkt.com.tr/{team_slug}/sperrenundverletzungen/verein/{team_id}"
        soup_inj = get_soup(url_injuries)
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

def get_league_url(league_key: str) -> str:
    url_map = {
        "en1": "https://www.transfermarkt.com.tr/premier-league/startseite/wettbewerb/GB1",
        "es1": "https://www.transfermarkt.com.tr/laliga/startseite/wettbewerb/ES1",
        "de1": "https://www.transfermarkt.com.tr/bundesliga/startseite/wettbewerb/L1",
        "tr1": "https://www.transfermarkt.com.tr/super-lig/startseite/wettbewerb/TR1",
    }
    return url_map.get(league_key.lower())


def get_league_position(team_name, league_key):
    try:
        url_league = get_league_url(league_key)
        if not url_league:
            return "Lige ait URL bulunamadı."

        soup = get_soup(url_league)
        table = soup.find('table', class_='items')
        rows = table.find('tbody').find_all('tr', recursive=False)
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 3:
                continue
            pos_text = cells[0].get_text(strip=True)
            name_text = cells[2].get_text(strip=True)
            if name_text.lower() == team_name.lower():
                return int(pos_text) if pos_text.isdigit() else pos_text
        return None
    except Exception as e:
        print(f"Lig sıralaması alınamadı: {e}", file=sys.stderr)
        return None

def get_recent_form(team_name, league_key):
    try:
        url_form = get_league_url(league_key)
        if not url_form:
            return "Lige ait URL bulunamadı."

        soup = get_soup(url_form)
        form_rows = soup.select("div.responsive-table table tbody tr")
        for row in form_rows:
            team_cell = row.select_one("td.no-border-links.hauptlink a")
            if team_cell and team_name.lower() in team_cell.text.lower():
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

def generate_team_data(team_info, league_key):
    team_name = team_info["name"]
    team_slug = team_info["slug"]
    team_id = team_info["id"]

    squad = scrape_squad(team_slug, team_id)
    output_data = {
        "team": team_name,
        "position_in_league": get_league_position(team_name, league_key),
        "recent_form": get_recent_form(team_name),
        "injuries": scrape_injuries(team_slug, team_id, squad),
        "squad": squad
    }
    return output_data, f"{team_name.lower()}.json"

@app.route("/")
def index():
    return "API çalışıyor"

@app.route("/generate-json", methods=["POST"])
def generate_json_api():
    try:
        data = request.get_json()
        home_team_key = data.get("home_team")
        away_team_key = data.get("away_team")
        league_key = data.get("league")

        if not home_team_key or not away_team_key:
            return jsonify({"error": "Ev sahibi ve deplasman takımları belirtilmeli."}), 400

        try:
            home_team_info = get_team_info(home_team_key)
            away_team_info = get_team_info(away_team_key)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

        teams_data = [
            generate_team_data(home_team_info, league_key),
            generate_team_data(away_team_info, league_key)
        ]

        generated_files = []
        folder_path = "team_status"
        os.makedirs(folder_path, exist_ok=True)

        for output_data, filename in teams_data:
            file_path = os.path.join(folder_path, filename)
            new_data = json.dumps(output_data, ensure_ascii=False, indent=2)

            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    existing_data = f.read()
                if existing_data == new_data:
                    print(f"⏩ {filename} zaten güncel, atlanıyor.")
                    continue

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_data)
            generated_files.append(file_path)

        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            return jsonify({"status": "error", "message": "GitHub token bulunamadı."}), 500

        repo_url = f"https://{github_token}@github.com/providedtroubleshoot/json_api_server.git"

        subprocess.run(["git", "checkout", "main"], check=True)
        subprocess.run(["git", "config", "--local", "user.email", "bot@render.com"], check=True)
        subprocess.run(["git", "config", "--local", "user.name", "Render Bot"], check=True)
        subprocess.run(["git", "remote", "remove", "origin"], stderr=subprocess.DEVNULL)
        subprocess.run(["git", "remote", "add", "origin", repo_url], check=True)

        subprocess.run(["git", "add", "."], check=True)


        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True
        )

        if not status_result.stdout.strip():
            return jsonify({
                "status": "success",
                "message": "Değişiklik yok."
            }), 200

        file_names = [os.path.basename(path) for path in generated_files]
        try:
            subprocess.run(
                ["git", "commit", "-m", f"Auto update {', '.join(file_names)}"],
                check=True
            )
        except subprocess.CalledProcessError as e:
            if "nothing to commit" in e.stderr.lower() or "no changes added" in e.stderr.lower():
                return jsonify({
                    "status": "success",
                    "message": "Takım durumlarında değişiklik yok."
                }), 200
            raise

        try:
            push_result = subprocess.run(
                ["git", "push", "origin", "main"],
                capture_output=True,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            print("🚨 Git push hatası:", e.stderr)
            return jsonify({"status": "error", "message": f"Git push hatası: {e.stderr}"}), 500

        if push_result.returncode != 0:
            return jsonify({"status": "error", "message": push_result.stderr}), 500

        print(f"✅ {', '.join(generated_files)} oluşturuldu ve pushlandı.")
        return jsonify({
            "status": "success",
            "message": f"{', '.join(generated_files)} başarıyla oluşturuldu ve pushlandı."
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
