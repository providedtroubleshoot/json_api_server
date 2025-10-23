import json
import os
import sys
from typing import Dict, List
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import re
import time

load_dotenv()

app = Flask(__name__)

# Selenium WebDriver kurulumu
def init_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Başsız modda çalıştır
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    return driver

# Firebase / Firestore başlatma
def init_firestore():
    if firebase_admin._apps:
        return firestore.client()

    raw_key = os.getenv("FIRESTORE_KEY")
    if not raw_key:
        raise RuntimeError("FIRESTORE_KEY ortam değişkeni tanımlı değil!")

    try:
        cred_dict = json.loads(raw_key)
    except json.JSONDecodeError:
        with open(raw_key, "r", encoding="utf-8") as f:
            cred_dict = json.load(f)

    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    return firestore.client()

DB = init_firestore()

# Takım verileri (değişmedi)
TEAMS = {
    # [TEAMS sözlüğü değişmedi, orijinal hali korundu]
}

def get_team_info(team_key: str) -> dict:
    key = team_key.lower()
    if key not in TEAMS:
        raise ValueError(f"{team_key} takımı bulunamadı. Geçerli takımlar: {list(TEAMS.keys())}")
    return TEAMS[key]

def extract_first_int(s: str) -> int:
    """Bir string içindeki ilk tam sayıyı ayıkla. Yoksa 0 döner."""
    if not s:
        return 0
    s = s.replace("'", "").replace(".", "").replace(",", "").strip()
    m = re.search(r'(\d+)', s)
    return int(m.group(1)) if m else 0

def scrape_stats(team_slug: str, team_id: str, driver) -> List[dict]:
    """Oyuncu istatistiklerini (oynadığı maç ve süre) çeker."""
    url = f"https://www.transfermarkt.com.tr/{team_slug}/leistungsdaten/verein/{team_id}"
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.items tbody tr"))
        )
        rows = driver.find_elements(By.CSS_SELECTOR, "table.items tbody tr")
        players = []

        for row in rows:
            td_list = row.find_elements(By.TAG_NAME, "td")
            if len(td_list) < 5:
                continue

            # Oyuncu adı
            try:
                name_elem = row.find_element(By.CSS_SELECTOR, "td.hauptlink a")
                name = name_elem.get_attribute("title") or name_elem.text.strip()
            except:
                name = ""

            # Maç sayısı ve süre
            td_texts = [td.text.strip() for td in td_list]
            raw_played_matches = td_texts[-3] if len(td_texts) >= 3 else ""
            raw_minutes = td_texts[-1] if len(td_texts) >= 1 else ""

            played_matches = extract_first_int(raw_played_matches)
            minutes_played = extract_first_int(raw_minutes)

            if name:
                players.append({
                    "name": name,
                    "played_matches": played_matches,
                    "minutes_played": minutes_played
                })

        if players:
            return players
        else:
            raise ValueError("Stats is empty")

    except Exception as e:
        print(f"Oyuncu istatistikleri alınamadı ({team_slug}): {e}", file=sys.stderr)
        return None

def scrape_suspensions(team_slug: str, team_id: str, squad: List[dict], driver) -> List[dict]:
    """Cezalı oyuncu verilerini çeker."""
    try:
        url = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}"
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.items"))
        )
        suspensions = []

        # Oyuncu tablosunu tara
        rows = driver.find_elements(By.CSS_SELECTOR, "tr.odd, tr.even")
        for row in rows:
            try:
                table_inline = row.find_element(By.CSS_SELECTOR, "table.inline-table")
                name_tag = table_inline.find_element(By.CSS_SELECTOR, "a")
                player_name = name_tag.text.strip()
                span_tag = table_inline.find_elements(By.CSS_SELECTOR, "span.ausfall-1-table, span.ausfall-2-table, span.ausfall-3-table")
                if span_tag:
                    suspension_type = span_tag[0].get_attribute("title").strip()
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
            except:
                continue

        return suspensions
    except Exception as e:
        print(f"Cezalılar veri hatası ({team_slug}): {e}", file=sys.stderr)
        return []

def scrape_squad(team_slug: str, team_id: str, driver) -> List[dict]:
    """Takım kadrosunu (oyuncu adı, pozisyon, piyasa değeri) çeker."""
    url = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}"
    driver.get(url)
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "table.items"))
    )
    players = []
    rows = driver.find_elements(By.CSS_SELECTOR, "tr.odd, tr.even")
    for row in rows:
        try:
            name = row.find_element(By.CSS_SELECTOR, "td.hauptlink").text.strip()
            tds = row.find_elements(By.TAG_NAME, "td")
            position = tds[4].text.strip() if len(tds) > 4 else ""
            market_value = tds[-1].text.strip() if len(tds) > 0 else ""
            players.append({"name": name, "position": position, "market_value": market_value})
        except:
            continue
    return players

def scrape_injuries(team_slug: str, team_id: str, squad: List[dict], driver) -> List[dict]:
    """Sakatlık verilerini çeker."""
    url = f"https://www.transfermarkt.com.tr/{team_slug}/sperrenundverletzungen/verein/{team_id}"
    injuries = []
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//td[contains(text(), 'Sakatlıklar')]"))
        )
        inj_header = driver.find_element(By.XPATH, "//td[contains(text(), 'Sakatlıklar')]")
        row = inj_header.find_element(By.XPATH, "./parent::tr")
        next_row = row.find_element(By.XPATH, "./following-sibling::tr") if row else None
        while next_row and "extrarow" not in (next_row.get_attribute("class") or ""):
            try:
                inline = next_row.find_element(By.CSS_SELECTOR, "table.inline-table")
                name_tag = inline.find_element(By.CSS_SELECTOR, "a")
                player_name = name_tag.text.strip()
                matched = next((p for p in squad if p["name"] == player_name), None)
                position = matched["position"] if matched else ""
                injuries.append({"name": player_name, "position": position})
            except:
                pass
            next_row = next_row.find_element(By.XPATH, "./following-sibling::tr") if next_row else None
    except Exception as e:
        print(f"Sakatlık verisi alınamadı: {e}", file=sys.stderr)
    return injuries

def get_league_url(league_key: str) -> str | None:
    # [Lig URL eşleştirmesi değişmedi]
    url_map = {
        "en1": "https://www.transfermarkt.com.tr/premier-league/tabelle/wettbewerb/GB1",
        "es1": "https://www.transfermarkt.com.tr/laliga/tabelle/wettbewerb/ES1",
        "de1": "https://www.transfermarkt.com.tr/bundesliga/tabelle/wettbewerb/L1",
        "tr1": "https://www.transfermarkt.com.tr/super-lig/tabelle/wettbewerb/TR1",
        "fr1": "https://www.transfermarkt.com.tr/ligue-1/tabelle/wettbewerb/FR1",
        "br1": "https://www.transfermarkt.com.tr/campeonato-brasileiro-serie-a/tabelle/wettbewerb/BRA1",
        "sa1": "https://www.transfermarkt.com.tr/saudi-professional-league/tabelle/wettbewerb/SA1",
        "it1": "https://www.transfermarkt.com.tr/serie-a/tabelle/wettbewerb/IT1",
        "hl1": "https://www.transfermarkt.com.tr/eredivisie/tabelle/wettbewerb/NL1"
    }
    return url_map.get(league_key.lower())

def get_form_url(league_key: str) -> str | None:
    # [Form URL eşleştirmesi değişmedi]
    url_map = {
        "en1": "https://www.transfermarkt.com.tr/premier-league/formtabelle/wettbewerb/GB1",
        "es1": "https://www.transfermarkt.com.tr/laliga/formtabelle/wettbewerb/ES1",
        "de1": "https://www.transfermarkt.com.tr/bundesliga/formtabelle/wettbewerb/L1",
        "tr1": "https://www.transfermarkt.com.tr/super-lig/formtabelle/wettbewerb/TR1",
        "fr1": "https://www.transfermarkt.com.tr/ligue-1/formtabelle/wettbewerb/FR1",
        "br1": "https://www.transfermarkt.com.tr/campeonato-brasileiro-serie-a/formtabelle/wettbewerb/BRA1",
        "sa1": "https://www.transfermarkt.com.tr/saudi-professional-league/formtabelle/wettbewerb/SA1",
        "it1": "https://www.transfermarkt.com.tr/serie-a/formtabelle/wettbewerb/IT1",
        "hl1": "https://www.transfermarkt.com.tr/eredivisie/formtabelle/wettbewerb/NL1"
    }
    return url_map.get(league_key.lower())

def get_league_position(team_name: str, league_key: str, driver) -> int | None:
    """Takımın ligdeki pozisyonunu alır."""
    try:
        url = get_league_url(league_key)
        if not url:
            return None
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.items tbody tr"))
        )
        rows = driver.find_elements(By.CSS_SELECTOR, "table.items tbody tr")
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
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

def get_recent_form(team_name: str, league_key: str, driver) -> dict | None:
    """Son form durumunu alır (galibiyet, beraberlik, mağlubiyet, son maçlar)."""
    try:
        url = get_form_url(league_key)
        if not url:
            return None
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.responsive-table table tbody tr"))
        )
        rows = driver.find_elements(By.CSS_SELECTOR, "div.responsive-table table tbody tr")
        for row in rows:
            team_cell = row.find_element(By.CSS_SELECTOR, "td.no-border-links.hauptlink a")
            if team_name.lower() in team_cell.text.lower():
                tds = row.find_elements(By.TAG_NAME, "td")
                wins = int(tds[4].text.strip())
                draws = int(tds[5].text.strip())
                losses = int(tds[6].text.strip())
                form_spans = tds[10].find_elements(By.TAG_NAME, "span")
                recent_results = [s.text.strip() for s in form_spans if s.text.strip() in ["G", "B", "M"]]
                return {"wins": wins, "draws": draws, "losses": losses, "last_matches": recent_results}
        return None
    except Exception as e:
        print(f"Form verisi alınamadı: {e}", file=sys.stderr)
        return None

def generate_team_data(team_info: dict, league_key: str, driver) -> tuple[dict, List[dict], str]:
    """Takım verilerini (kadro, sakatlıklar, cezalılar, pozisyon, form) oluşturur."""
    name = team_info["name"]
    slug = team_info["slug"]
    team_id = team_info["id"]

    squad = scrape_squad(slug, team_id, driver)
    injuries = scrape_injuries(slug, team_id, squad, driver)
    position = get_league_position(name, league_key, driver)
    form = get_recent_form(name, league_key, driver)
    suspensions = scrape_suspensions(slug, team_id, squad, driver)
    stats = scrape_stats(slug, team_id, driver)

    data = {
        "team": name,
        "position_in_league": position,
        "injuries": injuries,
        "suspensions": suspensions,
        "squad": squad
    }

    if form is not None:
        data["recent_form"] = form
    else:
        print(f"[UYARI] {name} için recent_form alınamadı, mevcut JSON korunuyor")

    if stats is not None:
        data["stats"] = stats
    else:
        print(f"[UYARI] {name} için istatistik alınamadı, mevcut JSON korunuyor")

    return data, stats, name.lower()

def save_team_data(team_name: str, team_data: dict, player_stats: List[dict]) -> None:
    """Takım verilerini ve oyuncu istatistiklerini Firestore'a kaydeder."""
    try:
        DB.collection("team_data").document(team_name.lower()).set(team_data, merge=True)
        print(f"✅ Firestore team_data'ya kaydedildi: {team_name}")

        if player_stats is not None:
            DB.collection("new_data").document(team_name.lower()).set({"player_stats": player_stats}, merge=True)
            print(f"✅ Firestore new_data'ya kaydedildi: {team_name}")
        else:
            print(f"[UYARI] {team_name} için player_stats kaydedilmedi (istatistik alınamadı)")
    except Exception as e:
        print(f"❌ Firestore kaydetme hatası ({team_name}): {e}", file=sys.stderr)

@app.route("/")
def index():
    return "API çalışıyor"

@app.route("/generate-json", methods=["POST"])
def generate_json_api():
    driver = None
    try:
        body = request.get_json()
        home_key = body.get("home_team")
        away_key = body.get("away_team")
        league_key = body.get("league_key")

        if not home_key or not away_key or not league_key:
            return jsonify({"error": "Eksik parametreler"}), 400

        home_info = get_team_info(home_key)
        away_info = get_team_info(away_key)

        # Selenium driver'ı başlat
        driver = init_driver()

        # Ev sahibi takım için veri oluştur
        home_data, home_stats, home_doc = generate_team_data(home_info, league_key, driver)
        # Deplasman takımı için veri oluştur
        away_data, away_stats, away_doc = generate_team_data(away_info, league_key, driver)

        # Her iki takımın verilerini ve oyuncu istatistiklerini kaydet
        save_team_data(home_doc, home_data, home_stats)
        save_team_data(away_doc, away_data, away_stats)

        print(f"Maç: {home_info['name']} vs {away_info['name']}", file=sys.stderr)

        return jsonify({
            "status": "success",
            "message": f"{home_doc}, {away_doc} Firestore'a kaydedildi (team_data ve new_data)."
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)