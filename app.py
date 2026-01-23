import json
import os
import sys
import time
import random
from typing import Dict, List
import hashlib
from curl_cffi import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import re
from requests.exceptions import HTTPError, RequestException

# Ortam değişkenlerini yükle (.env dosyasından)
load_dotenv()

app = Flask(__name__)

# Proxy ayarları
PROXY_URL = os.getenv("PROXY_URL")
# Proxy'yi requests kütüphanesinin anlayacağı formatta ayarla
# PROXY_URL'in "user:pass@host:port" formatında olduğunu varsayıyoruz.
PROXIES = {
    "http": PROXY_URL,
    "https": PROXY_URL,
} if PROXY_URL else None


# Firebase / Firestore başlatma
def init_firestore():
    """Firebase Firestore istemcisini başlatır ve döndürür."""
    if firebase_admin._apps:
        return firestore.client()

    raw_key = os.getenv("FIRESTORE_KEY")
    if not raw_key:
        raise RuntimeError("FIRESTORE_KEY env değişkeni tanımlı değil!")

    try:
        # JSON string olarak algılamaya çalış
        cred_dict = json.loads(raw_key)
    except json.JSONDecodeError:
        # JSON dosyası yolu olarak algılamaya çalış
        try:
            with open(raw_key, "r", encoding="utf-8") as f:
                cred_dict = json.load(f)
        except FileNotFoundError:
            raise RuntimeError("FIRESTORE_KEY bir JSON string veya geçerli bir dosya yolu değil!")

    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    return firestore.client()


try:
    DB = init_firestore()
except RuntimeError as e:
    print(f"[HATA] Firebase Başlatılamadı: {e}", file=sys.stderr)
    DB = None

# Takım Sözlüğü (Değiştirilmedi)
TEAMS = {
    "tondela": {"name": "Tondela", "slug": "cd-tondela", "id": "7179"},
    "moreirense": {"name": "Moreirense", "slug": "moreirense-fc", "id": "979"},
    "santa clara": {"name": "Santa Clara", "slug": "cd-santa-clara", "id": "2423"},
    "nacional": {"name": "Nacional", "slug": "cd-nacional", "id": "982"},
    "avs": {"name": "AVS", "slug": "avs-futebol-sad", "id": "110302"},
    "porto": {"name": "Porto", "slug": "fc-porto", "id": "720"},
    "rio ave": {"name": "Rio Ave", "slug": "rio-ave-fc", "id": "2425"},
    "sporting": {"name": "Sporting", "slug": "sporting-lissabon", "id": "336"},
    "benfica": {"name": "Benfica", "slug": "benfica-lissabon", "id": "294"},
    "braga": {"name": "Braga", "slug": "sc-braga", "id": "1075"},
    "gil vicente": {"name": "Gil Vicente", "slug": "gil-vicente-fc", "id": "2424"},
    "arouca": {"name": "Arouca", "slug": "fc-arouca", "id": "8024"},
    "vitória sc": {"name": "Vitória SC", "slug": "vitoria-guimaraes-sc", "id": "2420"},
    "casa pia": {"name": "Casa Pia", "slug": "casa-pia-ac", "id": "3268"},
    "alverca": {"name": "Alverca", "slug": "fc-alverca", "id": "2521"},
    "estoril": {"name": "Estoril", "slug": "gd-estoril-praia", "id": "1465"},
    "estrela": {"name": "Estrela", "slug": "cf-estrela-amadora-sad", "id": "2431"},
    "famalicão": {"name": "Famalicão", "slug": "fc-famalicao", "id": "3329"},
    "heracles": {"name": "Heracles", "slug": "heracles-almelo", "id": "1304"},
    "volendam": {"name": "Volendam", "slug": "fc-volendam", "id": "724"},
    "telstar": {"name": "Telstar", "slug": "sc-telstar", "id": "1434"},
    "excelsior": {"name": "Excelsior", "slug": "sbv-excelsior-rotterdam", "id": "798"},
    "nac breda": {"name": "NAC Breda", "slug": "nac-breda", "id": "132"},
    "pec zwolle": {"name": "PEC Zwolle", "slug": "pec-zwolle", "id": "1269"},
    "go ahead": {"name": "Go Ahead", "slug": "go-ahead-eagles-deventer", "id": "1435"},
    "heerenveen": {"name": "Heerenveen", "slug": "sc-heerenveen", "id": "306"},
    "sparta": {"name": "Sparta", "slug": "sparta-rotterdam", "id": "468"},
    "f. sittard": {"name": "F. Sittard", "slug": "fortuna-sittard", "id": "385"},
    "utrecht": {"name": "Utrecht", "slug": "fc-utrecht", "id": "200"},
    "twente": {"name": "Twente", "slug": "fc-twente-enschede", "id": "317"},
    "nec nijmegen": {"name": "NEC Nijmegen", "slug": "nec-nijmegen", "id": "467"},
    "groningen": {"name": "Groningen", "slug": "fc-groningen", "id": "202"},
    "az alkmaar": {"name": "AZ Alkmaar", "slug": "az-alkmaar", "id": "1090"},
    "ajax": {"name": "Ajax", "slug": "ajax-amsterdam", "id": "610"},
    "psv": {"name": "PSV", "slug": "psv-eindhoven", "id": "383"},
    "feyenoord": {"name": "Feyenoord", "slug": "feyenoord-rotterdam", "id": "234"},
    "lecce": {"name": "Lecce", "slug": "us-lecce", "id": "1005"},
    "cremonese": {"name": "Cremonese", "slug": "us-cremonese", "id": "2239"},
    "cagliari": {"name": "Cagliari", "slug": "cagliari-calcio", "id": "1390"},
    "verona": {"name": "Verona", "slug": "hellas-verona", "id": "276"},
    "pisa": {"name": "Pisa", "slug": "ac-pisa-1909", "id": "4172"},
    "genoa": {"name": "Genoa", "slug": "genua-cfc", "id": "252"},
    "udinese": {"name": "Udinese", "slug": "udinese-calcio", "id": "410"},
    "sassuolo": {"name": "Sassuolo", "slug": "us-sassuolo", "id": "6574"},
    "parma": {"name": "Parma", "slug": "parma-calcio-1913", "id": "130"},
    "torino": {"name": "Torino", "slug": "fc-turin", "id": "416"},
    "como": {"name": "Como", "slug": "como-1907", "id": "1047"},
    "bologna": {"name": "Bologna", "slug": "fc-bologna", "id": "1025"},
    "lazio": {"name": "Lazio", "slug": "lazio-rom", "id": "398"},
    "fiorentina": {"name": "Fiorentina", "slug": "ac-florenz", "id": "430"},
    "roma": {"name": "Roma", "slug": "as-rom", "id": "12"},
    "atalanta": {"name": "Atalanta", "slug": "atalanta-bergamo", "id": "800"},
    "napoli": {"name": "Napoli", "slug": "ssc-neapel", "id": "6195"},
    "milan": {"name": "Milan", "slug": "ac-mailand", "id": "5"},
    "juventus": {"name": "Juventus", "slug": "juventus-turin", "id": "506"},
    "inter": {"name": "Inter", "slug": "inter-mailand", "id": "46"},
    "al-hazem": {"name": "Al-Hazem", "slug": "al-hazm", "id": "9131"},
    "al-najma": {"name": "Al-Najma", "slug": "al-najma", "id": "32328"},
    "neom sc": {"name": "NEOM SC", "slug": "al-suqoor", "id": "34911"},
    "al-okhdood": {"name": "Al-Okhdood", "slug": "al-akhdoud-club", "id": "71665"},
    "damac": {"name": "Damac", "slug": "damac-fc", "id": "50532"},
    "al-fayha": {"name": "Al-Fayha", "slug": "al-fayha-fc", "id": "50531"},
    "al-khaleej": {"name": "Al-Khaleej", "slug": "al-khaleej", "id": "6070"},
    "al-riyadh": {"name": "Al-Riyadh", "slug": "al-riad", "id": "31008"},
    "al-fateh": {"name": "Al-Fateh", "slug": "al-fateh", "id": "27221"},
    "al-kholood": {"name": "Al-Kholood", "slug": "al-kholood", "id": "91427"},
    "al-taawoun": {"name": "Al-Taawoun", "slug": "al-taawoun-fc", "id": "28844"},
    "al-ettifaq": {"name": "Al-Ettifaq", "slug": "al-ettifaq", "id": "7732"},
    "al-shabab": {"name": "Al-Shabab", "slug": "al-shabab-riad", "id": "9840"},
    "al-ahli": {"name": "Al-Ahli", "slug": "al-ahli-dschidda", "id": "18487"},
    "al-qadsiah": {"name": "Al-Qadsiah", "slug": "al-qadisiyah-fc", "id": "26069"},
    "al-nassr": {"name": "Al-Nassr", "slug": "al-nasr-riad", "id": "18544"},
    "al-hilal": {"name": "Al-Hilal", "slug": "al-hilal-riad", "id": "1114"},
    "al-ittihad": {"name": "Al-Ittihad", "slug": "al-ittihad-dschidda", "id": "8023"},
    "sport recife": {"name": "Sport Recife", "slug": "sport-club-do-recife", "id": "8718"},
    "juventude": {"name": "Juventude", "slug": "esporte-clube-juventude", "id": "10492"},
    "vasco": {"name": "Vasco", "slug": "vasco-da-gama-rio-de-janeiro", "id": "978"},
    "fortaleza": {"name": "Fortaleza", "slug": "fortaleza-esporte-clube", "id": "10870"},
    "vitória": {"name": "Vitória", "slug": "esporte-clube-vitoria", "id": "2125"},
    "grêmio": {"name": "Grêmio", "slug": "gremio-porto-alegre", "id": "210"},
    "santos": {"name": "Santos", "slug": "fc-santos", "id": "221"},
    "corinthians": {"name": "Corinthians", "slug": "corinthians-sao-paulo", "id": "199"},
    "ceará sc": {"name": "Ceará SC", "slug": "ceara-sporting-club", "id": "2029"},
    "sc inter": {"name": "SC Inter", "slug": "sc-internacional-porto-alegre", "id": "6600"},
    "atlético-mg": {"name": "Atlético-MG", "slug": "clube-atletico-mineiro", "id": "330"},
    "fluminense": {"name": "Fluminense", "slug": "fluminense-rio-de-janeiro", "id": "2462"},
    "bragantino": {"name": "Bragantino", "slug": "red-bull-bragantino", "id": "8793"},
    "são paulo": {"name": "São Paulo", "slug": "fc-sao-paulo", "id": "585"},
    "mirassol": {"name": "Mirassol", "slug": "mirassol-futebol-clube-sp-", "id": "3876"},
    "botafogo": {"name": "Botafogo", "slug": "botafogo-rio-de-janeiro", "id": "537"},
    "bahia": {"name": "Bahia", "slug": "esporte-clube-bahia", "id": "10010"},
    "palmeiras": {"name": "Palmeiras", "slug": "se-palmeiras-sao-paulo", "id": "1023"},
    "cruzeiro": {"name": "Cruzeiro", "slug": "ec-cruzeiro-belo-horizonte", "id": "609"},
    "flamengo": {"name": "Flamengo", "slug": "flamengo-rio-de-janeiro", "id": "614"},
    "psg": {"name": "PSG", "slug": "fc-paris-saint-germain", "id": "583"},
    "marsilya": {"name": "Marsilya", "slug": "olympique-marseille", "id": "244"},
    "monaco": {"name": "Monaco", "slug": "as-monaco", "id": "162"},
    "nice": {"name": "Nice", "slug": "ogc-nizza", "id": "417"},
    "lille": {"name": "Lille", "slug": "losc-lille", "id": "1082"},
    "lyon": {"name": "Lyon", "slug": "olympique-lyon", "id": "1041"},
    "strasbourg": {"name": "Strasbourg", "slug": "rc-strassburg-alsace", "id": "667"},
    "lens": {"name": "Lens", "slug": "rc-lens", "id": "826"},
    "brest": {"name": "Brest", "slug": "stade-brest-29", "id": "3911"},
    "toulouse": {"name": "Toulouse", "slug": "fc-toulouse", "id": "415"},
    "aj auxerre": {"name": "AJ Auxerre", "slug": "aj-auxerre", "id": "290"},
    "rennes": {"name": "Rennes", "slug": "fc-stade-rennes", "id": "273"},
    "nantes": {"name": "Nantes", "slug": "fc-nantes", "id": "995"},
    "angers": {"name": "Angers", "slug": "sco-angers", "id": "1420"},
    "le havre": {"name": "Le Havre", "slug": "ac-le-havre", "id": "738"},
    "lorient": {"name": "Lorient", "slug": "fc-lorient", "id": "1158"},
    "paris fc": {"name": "Paris FC", "slug": "paris-fc", "id": "10004"},
    "metz": {"name": "Metz", "slug": "fc-metz", "id": "347"},
    "hoffenheim": {"name": "Hoffenheim", "slug": "tsg-1899-hoffenheim", "id": "533"},
    "heidenheim": {"name": "Heidenheim", "slug": "1-fc-heidenheim-1846", "id": "2036"},
    "köln": {"name": "Köln", "slug": "1-fc-koln", "id": "3"},
    "hamburg": {"name": "Hamburg", "slug": "hamburger-sv", "id": "41"},
    "st. pauli": {"name": "St. Pauli", "slug": "fc-st-pauli", "id": "35"},
    "u. berlin": {"name": "U. Berlin", "slug": "1-fc-union-berlin", "id": "89"},
    "augsburg": {"name": "Augsburg", "slug": "fc-augsburg", "id": "167"},
    "wolfsburg": {"name": "Wolfsburg", "slug": "vfl-wolfsburg", "id": "82"},
    "stuttgart": {"name": "Stuttgart", "slug": "vfb-stuttgart", "id": "79"},
    "gladbach": {"name": "Gladbach", "slug": "borussia-monchengladbach", "id": "18"},
    "bremen": {"name": "Bremen", "slug": "sv-werder-bremen", "id": "86"},
    "leipzig": {"name": "Leipzig", "slug": "rasenballsport-leipzig", "id": "23826"},
    "mainz": {"name": "Mainz", "slug": "1-fsv-mainz-05", "id": "39"},
    "freiburg": {"name": "Freiburg", "slug": "sc-freiburg", "id": "60"},
    "frankfurt": {"name": "Frankfurt", "slug": "eintracht-frankfurt", "id": "24"},
    "leverkusen": {"name": "Leverkusen", "slug": "bayer-04-leverkusen", "id": "15"},
    "real oviedo": {"name": "Real Oviedo", "slug": "real-oviedo", "id": "2497"},
    "elche": {"name": "Elche", "slug": "fc-elche", "id": "1531"},
    "levante": {"name": "Levante", "slug": "ud-levante", "id": "3368"},
    "espanyol": {"name": "Espanyol", "slug": "espanyol-barcelona", "id": "714"},
    "girona": {"name": "Girona", "slug": "fc-girona", "id": "12321"},
    "alavés": {"name": "Alavés", "slug": "deportivo-alaves", "id": "1108"},
    "getafe": {"name": "Getafe", "slug": "fc-getafe", "id": "3709"},
    "valencia": {"name": "Valencia", "slug": "fc-valencia", "id": "1049"},
    "sociedad": {"name": "Sociedad", "slug": "real-sociedad-san-sebastian", "id": "681"},
    "mallorca": {"name": "Mallorca", "slug": "rcd-mallorca", "id": "237"},
    "osasuna": {"name": "Osasuna", "slug": "ca-osasuna", "id": "331"},
    "celta vigo": {"name": "Celta Vigo", "slug": "celta-vigo", "id": "940"},
    "rayo": {"name": "Rayo", "slug": "rayo-vallecano", "id": "367"},
    "real betis": {"name": "Real Betis", "slug": "real-betis-sevilla", "id": "150"},
    "villarreal": {"name": "Villarreal", "slug": "fc-villarreal", "id": "1050"},
    "athletic bilbao": {"name": "Athletic Bilbao", "slug": "athletic-bilbao", "id": "621"},
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
    "barcelona": {"name": "Barcelona", "slug": "fc-barcelona", "id": "131"},
    "real madrid": {"name": "Real Madrid", "slug": "real-madrid", "id": "418"},
    "man united": {"name": "Man United", "slug": "manchester-united", "id": "985"},
    "atletico madrid": {"name": "Atletico Madrid", "slug": "atletico-madrid", "id": "13"},
    "man city": {"name": "Man City", "slug": "manchester-city", "id": "281"},
    "chelsea": {"name": "Chelsea", "slug": "chelsea", "id": "631"},
    "dortmund": {"name": "Dortmund", "slug": "borussia-dortmund", "id": "16"},
    "sevilla": {"name": "Sevilla", "slug": "fc-sevilla", "id": "368"},
    "arsenal": {"name": "Arsenal", "slug": "fc-arsenal", "id": "11"},
    "bayern münih": {"name": "Bayern Münih", "slug": "fc-bayern-munchen", "id": "27"},
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
    """Verilen URL'den HTML çekip BeautifulSoup objesine dönüştürür (Proxy kullanarak)."""
    # Proxy kullanılıp kullanılmadığını logla
    if PROXIES:
        print(f"[UYARI] Proxy kullanılıyor: {PROXY_URL}", file=sys.stderr)

    res = requests.get(url, proxies=PROXIES, impersonate="chrome120", timeout=18)
    res.raise_for_status()
    return BeautifulSoup(res.text, "lxml")  # lxml parser'ı artık yüklü olmalı


def extract_first_int(s: str) -> int:
    """Bir string içindeki ilk tam sayıyı ayıkla. Yoksa 0 döner."""
    if not s:
        return 0
    s = s.replace("'", "").replace(".", "").replace(",", "").strip()
    m = re.search(r'(\d+)', s)
    return int(m.group(1)) if m else 0


def load_hash(url: str) -> str | None:
    """Firestore'dan belirli bir URL için kaydedilmiş hash değerini yükler."""
    if not DB:
        print("[UYARI] Firestore bağlantısı yok, hash kontrolü atlanıyor.")
        return None
    try:
        doc_id = hashlib.md5(url.encode('utf-8')).hexdigest()
        doc = DB.collection("scrape_cache").document(doc_id).get()
        if doc.exists:
            return doc.to_dict().get("hash")
        return None
    except Exception as e:
        print(f"[UYARI] Hash yüklenemedi ({url}): {e}", file=sys.stderr)
        return None


def save_hash(url: str, hash_value: str):
    """Firestore'a belirli bir URL için hash değerini kaydeder."""
    if not DB:
        print("[UYARI] Firestore bağlantısı yok, hash kaydedilmiyor.")
        return
    try:
        doc_id = hashlib.md5(url.encode('utf-8')).hexdigest()
        DB.collection("scrape_cache").document(doc_id).set({
            "url": url,
            "hash": hash_value,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        print(f"[BİLGİ] Hash kaydedildi: {url}")
    except Exception as e:
        print(f"[HATA] Hash kaydedilemedi ({url}): {e}", file=sys.stderr)


def get_content_hash(element) -> str:
    """
    Belirli bir HTML elementinin metin içeriğinin parmak izini alır.
    Bu sayede sadece tablodaki veriler (dakika, maç vs.) değişince fark eder.
    """
    if not element:
        return ""
    # Sadece metin içeriğini alarak reklam/script değişimlerinden etkilenmeyi önlüyoruz
    text_content = element.get_text(strip=True)
    return hashlib.md5(text_content.encode('utf-8')).hexdigest()


def scrape_stats(team_slug: str, team_id: str) -> List[dict]:
    """Oyuncu istatistiklerini (oynadığı maç ve süre) çeker - cache destekli."""
    url = f"https://www.transfermarkt.com.tr/{team_slug}/leistungsdaten/verein/{team_id}"
    
    try:
        # Proxy desteği (dışarıdan gelen global değişkenler)
        if PROXIES:
            print(f"[UYARI] Proxy kullanılıyor: {PROXY_URL}", file=sys.stderr)

        soup = get_soup(url)

        stats_table = soup.select_one("table.items")
        if not stats_table:
            raise ValueError("Stats table not found")

        current_hash = get_content_hash(stats_table)

        old_hash = load_hash(url)
        if old_hash and old_hash == current_hash:
            print(f"[BİLGİ] {team_slug} için oyuncu istatistikleri değişmemiş, scrape atlanıyor.")
            return None  # ← orijinal davranışını korudun, istersen [] döndürebilirsin

        print(f"[GÜNCELLEME] {team_slug} için verilerde değişiklik algılandı, scrape ediliyor...")

        rows = stats_table.select("tbody tr")
        players = []

        for row in rows:
            td_list = row.find_all("td")
            if len(td_list) < 11:
                continue

            # Düzeltme: cells yerine td_list kullanıyoruz
            texts = [td.get_text(strip=True) for td in td_list]

            # İsim temizleme
            raw_name = texts[3] if len(texts) > 3 else ""
            if not raw_name:
                continue

            # Pozisyon kelimelerini kaldır
            pos_pattern = r"(Kaleci|Defans|Stoper|Sağ Bek|Sol Bek|Orta saha|Merkez Orta Saha|On Numara|Forvet|Santrafor|Sol Kanat|Sağ Kanat)"
            name_part = re.sub(pos_pattern, "", raw_name, flags=re.IGNORECASE).strip()

            # Tekrar eden soyisim / kısaltma temizliği
            name_part = re.sub(r"([A-Za-z\s]+?)([A-Z]\.\s*[A-Za-z]+?)\1?$", r"\1", name_part).strip()
            name = re.sub(r"\b[A-Z]\.\s*", "", name_part).strip()

            words = name.split()
            if len(words) >= 2 and words[-1] == words[-2]:
                name = " ".join(words[:-1]).strip()

            if not name:
                continue

            # Maç sayısı: index 8
            played_str = texts[8] if len(texts) > 8 else ""

            # Dakika: index 10
            minutes_str = texts[10].replace("'", "").replace(".", "") if len(texts) > 10 else ""

            if "oynatılmadı" in " ".join(texts).lower() or not minutes_str.isdigit():
                continue

            played = extract_first_int(played_str)
            minutes = extract_first_int(minutes_str)

            if played is not None and minutes is not None and minutes > 0:
                players.append({
                    "name": name,
                    "played_matches": played,
                    "minutes_played": minutes
                })

        if not players:
            print(f"[UYARI] {team_slug} için oyuncu verisi çıkmadı.", file=sys.stderr)
            return None

        # Cache'i sadece başarılı scrape sonrası kaydet
        save_hash(url, current_hash)
        return players

    except Exception as e:
        print(f"[HATA] {team_slug}: {e}", file=sys.stderr)
        return None

def scrape_suspensions(team_slug, team_id, squad):
    url = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}"
    try:
        soup = get_soup(url)

        table = soup.find("table", class_="items")
        if not table:
            raise ValueError("Suspensions table not found")

        current_hash = get_content_hash(table)

        old_hash = load_hash(url)
        if old_hash and old_hash == current_hash:
            print(f"[BİLGİ] {team_slug} için suspensions (old) değişmemiş, scrape atlanıyor.")
            return None

        print(f"[GÜNCELLEME] {team_slug} için suspensions (old) verilerde değişiklik algılandı, scrape ediliyor...")

        suspensions = []

        # Oyuncu satırlarını tara (odd ve even sınıfları)
        rows = table.find_all("tr", class_=["odd", "even"])
        for row in rows:
            table_inline = row.find("table", class_="inline-table")
            if table_inline:
                name_tag = table_inline.find("a", href=True)
                if name_tag:
                    player_name = name_tag.get_text(strip=True)
                    span_tag = name_tag.find("span", class_=["ausfall-1-table", "ausfall-2-table", "ausfall-3-table"])
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

        save_hash(url, current_hash)
        return suspensions
    except Exception as e:
        print(f"Cezalılar veri hatası ({team_slug}): {e}", file=sys.stderr)
        return None


def scrape_squad(team_slug: str, team_id: str) -> List[dict] | None:
    url = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}"
    try:
        soup = get_soup(url)

        table = soup.find("table", class_="items")
        if not table:
            raise ValueError("Squad table not found")

        current_hash = get_content_hash(table)

        old_hash = load_hash(url)
        if old_hash and old_hash == current_hash:
            print(f"[BİLGİ] {team_slug} için squad değişmemiş, scrape atlanıyor.")
            return None

        print(f"[GÜNCELLEME] {team_slug} için squad verilerde değişiklik algılandı, scrape ediliyor...")

        rows = table.find_all("tr", class_=["odd", "even"])
        players = []

        for row in rows:
            name = row.find("td", class_="hauptlink").text.strip()
            position = row.find_all("td")[4].text.strip()
            market_value = row.find_all("td")[-1].text.strip()
            players.append({
                "name": name,
                "position": position,
                "market_value": market_value
            })

        if not players:
            raise ValueError("Squad empty")

        save_hash(url, current_hash)
        return players

    except Exception as e:
        print(f"[HATA] Squad scrape başarısız ({team_slug}): {e}", file=sys.stderr)
        return None


def scrape_injuries(team_slug: str, team_id: str, squad: List[dict]) -> List[dict] | None:
    url = f"https://www.transfermarkt.com.tr/{team_slug}/sperrenundverletzungen/verein/{team_id}"
    try:
        soup = get_soup(url)
        inj_header = soup.find("td", string="Sakatlıklar")
        if not inj_header:
            return []

        # Injury section'ı hash için topla
        injury_section = inj_header.find_parent("tr")
        injury_content = str(injury_section)
        next_row = injury_section.find_next_sibling()
        while next_row and "extrarow" not in (next_row.get("class") or []):
            injury_content += str(next_row)
            next_row = next_row.find_next_sibling()

        current_hash = hashlib.md5(injury_content.encode('utf-8')).hexdigest()

        old_hash = load_hash(url)
        if old_hash and old_hash == current_hash:
            print(f"[BİLGİ] {team_slug} için injuries değişmemiş, scrape atlanıyor.")
            return None

        print(f"[GÜNCELLEME] {team_slug} için injuries verilerde değişiklik algılandı, scrape ediliyor...")

        injuries = []
        next_row = injury_section.find_next_sibling()
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

        save_hash(url, current_hash)
        return injuries
    except Exception as e:
        print(f"Sakatlık verisi alınamadı: {e}", file=sys.stderr)
    return None


# Lig URL'leri (Değiştirilmedi)
def get_league_url(league_key: str) -> str | None:
    url_map = {
        "en1": "https://www.transfermarkt.com.tr/premier-league/tabelle/wettbewerb/GB1",
        "es1": "https://www.transfermarkt.com.tr/laliga/tabelle/wettbewerb/ES1",
        "de1": "https://www.transfermarkt.com.tr/bundesliga/tabelle/wettbewerb/L1",
        "tr1": "https://www.transfermarkt.com.tr/super-lig/tabelle/wettbewerb/TR1",
        "fr1": "https://www.transfermarkt.com.tr/ligue-1/tabelle/wettbewerb/FR1",
        "br1": "https://www.transfermarkt.com.tr/campeonato-brasileiro-serie-a/tabelle/wettbewerb/BRA1",
        "sa1": "https://www.transfermarkt.com.tr/saudi-professional-league/tabelle/wettbewerb/SA1",
        "it1": "https://www.transfermarkt.com.tr/serie-a/tabelle/wettbewerb/IT1",
        "hl1": "https://www.transfermarkt.com.tr/eredivisie/tabelle/wettbewerb/NL1",
        "pt1": "https://www.transfermarkt.com.tr/liga-nos/tabelle/wettbewerb/PO1"
    }
    return url_map.get(league_key.lower())


def get_form_url(league_key: str) -> str | None:
    url_map = {
        "en1": "https://www.transfermarkt.com.tr/premier-league/formtabelle/wettbewerb/GB1",
        "es1": "https://www.transfermarkt.com.tr/laliga/formtabelle/wettbewerb/ES1",
        "de1": "https://www.transfermarkt.com.tr/bundesliga/formtabelle/wettbewerb/L1",
        "tr1": "https://www.transfermarkt.com.tr/super-lig/formtabelle/wettbewerb/TR1",
        "fr1": "https://www.transfermarkt.com.tr/ligue-1/formtabelle/wettbewerb/FR1",
        "br1": "https://www.transfermarkt.com.tr/campeonato-brasileiro-serie-a/formtabelle/wettbewerb/BRA1",
        "sa1": "https://www.transfermarkt.com.tr/saudi-professional-league/formtabelle/wettbewerb/SA1",
        "it1": "https://www.transfermarkt.com.tr/serie-a/formtabelle/wettbewerb/IT1",
        "hl1": "https://www.transfermarkt.com.tr/eredivisie/formtabelle/wettbewerb/NL1",
        "pt1": "https://www.transfermarkt.com.tr/eredivisie/formtabelle/wettbewerb/PO1",
    }
    return url_map.get(league_key.lower())


def get_league_position(team_name: str, league_key: str):
    try:
        url = get_league_url(league_key)
        if not url:
            return
        soup = get_soup(url)
        table = soup.select_one("table.items")
        if not table:
            raise ValueError("League table not found")

        current_hash = get_content_hash(table)

        old_hash = load_hash(url)
        if old_hash and old_hash == current_hash:
            print(f"[BİLGİ] Lig tablosu değişmemiş, position scrape atlanıyor.")
            return None

        print(f"[GÜNCELLEME] Lig tablosunda değişiklik algılandı, position scrape ediliyor...")

        rows = table.select("tbody tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 9:
                continue
            pos_td = cells[0]
            pos_text = pos_td.get_text(strip=True)
            pos_clean = ''.join(c for c in pos_text if c.isdigit())
            if not pos_clean.isdigit():
                continue

            # Takım adı: üçüncü hücredeki hauptlink içindeki <a> metni (görünen isim)
            team_td = cells[2]
            if "hauptlink" not in team_td.get("class", []):
                continue

            # En temiz yol: hauptlink içindeki ilk <a> etiketinin TEXT'ini al
            a_tag = team_td.find("a")
            team_display_name = ""
            if a_tag:
                team_display_name = a_tag.get_text(strip=True)

            if not team_display_name:
                # Alternatif: tüm td metninden kupon ikonlarını vs. temizle
                team_display_name = team_td.get_text(strip=True)
                # Başarı ikonlarını ve diğer gereksiz kısımları temizle
                team_display_name = re.sub(r"[↑↓→←★☆]+", "", team_display_name).strip()

            if not team_display_name:
                continue

            # Karşılaştırma: case-insensitive + boşluk temiz
            if team_display_name.lower().strip() == team_name.lower().strip():
                return int(pos_clean)

        print(f"[UYARI] '{team_name}' takımı {league_key} tablosunda bulunamadı.", file=sys.stderr)
        return None

    except requests.RequestException as e:
        print(f"[HATA] Bağlantı sorunu ({league_key}): {e}", file=sys.stderr)
    except Exception as e:
        print(f"[HATA] Parse hatası ({league_key}): {e}", file=sys.stderr)

    return None


def get_recent_form(team_name: str, league_key: str) -> dict:
    try:
        url = get_form_url(league_key)
        if not url:
            return
        soup = get_soup(url)
        form_table = soup.select_one("div.responsive-table table")
        if not form_table:
            raise ValueError("Form table not found")

        current_hash = get_content_hash(form_table)

        old_hash = load_hash(url)
        if old_hash and old_hash == current_hash:
            print(f"[BİLGİ] Form tablosu değişmemiş, recent_form scrape atlanıyor.")
            return None

        print(f"[GÜNCELLEME] Form tablosunda değişiklik algılandı, recent_form scrape ediliyor...")

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
                save_hash(url, current_hash)
                return {"wins": wins, "draws": draws, "losses": losses, "last_matches": recent_results}
        return
    except Exception as e:
        print(f"Form verisi alınamadı: {e}", file=sys.stderr)
        return


def scrape_suspensions_kader(team_slug: str, team_id: str, season_id: int = 2025) -> list | None:
    url = f"https://www.transfermarkt.com.tr/{team_slug}/kader/verein/{team_id}/saison_id/{season_id}"

    try:
        soup = get_soup(url)

        # Kader tablosunu bul
        kader_table = soup.find("table", class_="items")
        if not kader_table:
            raise ValueError("Kader table not found")

        current_hash = get_content_hash(kader_table)

        old_hash = load_hash(url)
        if old_hash and old_hash == current_hash:
            print(f"[BİLGİ] {team_slug} için suspensions (kader) değişmemiş, scrape atlanıyor.")
            return None

        print(f"[GÜNCELLEME] {team_slug} için suspensions (kader) verilerde değişiklik algılandı, scrape ediliyor...")

        cezali_oyuncular = []

        for row in soup.find_all("tr", class_=["odd", "even"]):
            ausfall_span = row.find("span", class_="ausfall-table")
            if not ausfall_span:
                continue

            name_td = row.find("td", class_="hauptlink")
            player_name = (
                " ".join(name_td.get_text(strip=True).split())
                if name_td else "İsim bulunamadı"
            )

            ceza_title = ausfall_span.get("title", "Ceza bilgisi yok")

            numara_div = row.find("div", class_="rn_nummer")
            numara = numara_div.get_text(strip=True) if numara_div else "-"

            pos_td = row.find("td", class_="posrela")
            pozisyon = "-"
            if pos_td:
                tds = pos_td.find_all("td")
                if len(tds) > 1:
                    pozisyon = tds[-1].get_text(strip=True)

            cezali_oyuncular.append({
                "name": player_name,
                "number": numara,
                "position": pozisyon,
                "details": ceza_title,
                "source": "kader"
            })

        time.sleep(random.uniform(1.5, 3.0))
        save_hash(url, current_hash)
        return cezali_oyuncular

    except Exception as e:
        print(f"[UYARI] Kader cezalı scrape başarısız ({team_slug}): {e}", file=sys.stderr)
        return None


def generate_team_data(team_info: dict, league_key: str) -> tuple[dict, List[dict], str]:
    name = team_info["name"]
    slug = team_info["slug"]
    team_id = team_info["id"]

    print(f"🔄 {name} için veri çekme başlıyor...", file=sys.stderr)
    # 1. Kadro (SQUAD)
    squad = None
    try:
        squad = scrape_squad(slug, team_id)
        if squad is None:
            print(f"[UYARI] Kadro bilgisi değişmemiş ({name}). Eski veri korunuyor.", file=sys.stderr)
        elif not squad:
            print(f"[UYARI] Kadro bilgisi alınamadı ({name}). Diğer verilere geçiliyor.", file=sys.stderr)
    except Exception as e:
        print(f"[HATA] Kadro çekme hatası ({name}): {e}", file=sys.stderr)

    # 2. Sakatlıklar ve Cezalılar (SQUAD'a bağımlı)
    injuries = None
    suspensions = []
    if squad or squad is None:  # Squad cache'de aynı olsa bile, diğerlerini dene (bağımsız)
        try:
            injuries = scrape_injuries(slug, team_id, squad or [])  # squad None ise boş list kullan
            if injuries is None:
                print(f"[UYARI] Sakatlık verisi değişmemiş ({name}). Eski veri korunuyor.", file=sys.stderr)
        except Exception as e:
            print(f"[HATA] Sakatlık çekme hatası ({name}): {e}", file=sys.stderr)

        try:
            old_susp = scrape_suspensions(slug, team_id, squad or [])
            if old_susp is None:
                print(f"[UYARI] Eski ceza verisi değişmemiş ({name}). Eski veri korunuyor.", file=sys.stderr)
            elif old_susp:
                suspensions.extend(old_susp)
        except Exception as e:
            print(f"[HATA] Eski ceza scrape hatası ({name}): {e}", file=sys.stderr)

        try:
            new_susp = scrape_suspensions_kader(slug, team_id)
            if new_susp is None:
                print(f"[UYARI] Yeni ceza verisi değişmemiş ({name}). Eski veri korunuyor.", file=sys.stderr)
            elif new_susp is not None:
                suspensions.extend(new_susp)
            else:
                print(f"[UYARI] Yeni ceza scrape başarısız, eski veri korunuyor ({name})", file=sys.stderr)
        except Exception as e:
            print(f"[HATA] Yeni ceza scrape hatası ({name}): {e}", file=sys.stderr)

    else:
        # Squad hata verdiyse atla
        print(f"[BİLGİ] Kadro olmadığı için sakatlık/ceza verisi atlanıyor ({name})", file=sys.stderr)

    # 3. Bağımsız Veriler: Pozisyon, Form, İstatistik
    position = None
    try:
        position = get_league_position(name, league_key)
        if position is None:
            print(f"[UYARI] Position verisi değişmemiş ({name}). Eski veri korunuyor.", file=sys.stderr)
    except Exception as e:
        print(f"[HATA] Pozisyon çekme hatası ({name}): {e}", file=sys.stderr)

    form = None
    try:
        form = get_recent_form(name, league_key)
        if form is None:
            print(f"[UYARI] Recent form verisi değişmemiş ({name}). Eski veri korunuyor.", file=sys.stderr)
    except Exception as e:
        print(f"[HATA] Form çekme hatası ({name}): {e}", file=sys.stderr)

    stats = None
    try:
        stats = scrape_stats(slug, team_id)
        if stats is None:
            print(f"[UYARI] İstatistik verisi değişmemiş ({name}). Eski veri korunuyor.", file=sys.stderr)
    except Exception as e:
        print(f"[HATA] İstatistik çekme hatası ({name}): {e}", file=sys.stderr)

    # Veriyi birleştir
    data = {
        "team": name,
    }

    if position is not None:
        data["position_in_league"] = position

    if suspensions:
        data["suspensions"] = suspensions

    if squad is not None:
        data["squad"] = squad

    # Injuries varsa ekle
    if injuries is not None:
        data["injuries"] = injuries or []  # None değilse, boş olsa bile ekle

    # Form varsa ekle
    if form is not None:
        data["recent_form"] = form

    print(f"✅ {name} için veri çekme tamamlandı.", file=sys.stderr)
    return data, stats, name.lower()


def save_team_data(team_name: str, team_data: dict, player_stats: List[dict]) -> None:
    try:
        # Save team data to team_data collection
        DB.collection("team_data").document(team_name.lower()).set(team_data, merge=True)
        print(f"✅ Firestore team_data'ya kaydedildi: {team_name}")

        # Save player stats to new_data collection
        if player_stats is not None:
            DB.collection("new_data").document(team_name.lower()).set({"player_stats": player_stats}, merge=True)
            print(f"✅ Firestore new_data'ya kaydedildi: {team_name}")
        else:
            print(f"[UYARI] {team_name} için player_stats kaydedilmedi (değişiklik yok veya alınamadı)",
                  file=sys.stderr)
    except Exception as e:
        print(f"❌ Firestore kaydetme hatası ({team_name}): {e}", file=sys.stderr)


@app.route("/")
def index():
    return "API çalışıyor"


@app.route("/generate-json", methods=["POST"])
def generate_json_api():
    # Hata toplama ve raporlama için bir listesi
    errors = []

    try:
        body = request.get_json()
        home_key = body.get("home_team")
        away_key = body.get("away_team")
        league_key = body.get("league_key")

        if not home_key or not away_key or not league_key:
            return jsonify({"error": "Eksik parametreler"}), 400

        home_info = get_team_info(home_key)
        away_info = get_team_info(away_key)

        # --- EV SAHİBİ TAKIM İŞLEMİ (İzolasyon Bloğu) ---
        home_data = None
        home_stats = None
        home_doc = home_info['name'].lower()
        try:
            home_data, home_stats, home_doc = generate_team_data(home_info, league_key)
            if home_data:
                save_team_data(home_doc, home_data, home_stats)
            else:
                errors.append(
                    f"Ev sahibi takım ({home_info['name']}) için ana veri çekilemedi ve Firestore'a kaydedilemedi.")

        except Exception as e:
            # Sadece bu takıma özel hataları yakala ve devam et
            error_msg = f"Ev sahibi takım ({home_info['name']}) işlenirken kritik hata oluştu: {str(e)}"
            print(f"[HATA İZOLASYONU] {error_msg}", file=sys.stderr)
            errors.append(error_msg)

        # --- DEPLASMAN TAKIMI İŞLEMİ (İzolasyon Bloğu) ---
        away_data = None
        away_stats = None
        away_doc = away_info['name'].lower()
        try:
            away_data, away_stats, away_doc = generate_team_data(away_info, league_key)
            if away_data:
                save_team_data(away_doc, away_data, away_stats)
            else:
                errors.append(
                    f"Deplasman takımı ({away_info['name']}) için ana veri çekilemedi ve Firestore'a kaydedilemedi.")

        except Exception as e:
            # Sadece bu takıma özel hataları yakala ve devam et
            error_msg = f"Deplasman takımı ({away_info['name']}) işlenirken kritik hata oluştu: {str(e)}"
            print(f"[HATA İZOLASYONU] {error_msg}", file=sys.stderr)
            errors.append(error_msg)

        # --- SONUÇ RAPORLAMA ---
        if not errors:
            return jsonify({
                "status": "success",
                "message": f"{home_doc}, {away_doc} Firestore'a başarıyla kaydedildi."
            }), 200
        else:
            # İşlemlerin bir kısmı başarılı, ancak hatalar var. 200 veya 207 (Multi-Status) döndürülebilir.
            # API'nin çökmemesi istendiği için 200 döndürüp hatayı mesajda gösteriyoruz.
            return jsonify({
                "status": "partial_success",
                "message": "İstek işlendi ancak bazı takım verileri çekilemedi/kaydedilemedi.",
                "errors": errors
            }), 200  # 200 (OK) ile döndürerek genel bir API hatasını (500) önlüyoruz

    except Exception as e:
        # Bu en dıştaki blok, sadece ilk parametre kontrolü (get_json) veya
        # get_team_info (takım adı bulunamadı) gibi, maçın başlamasını engelleyen
        # hataları yakalar ve 500/400 döndürür.
        error_message = f"Maç ön kontrol hatası: {str(e)}"
        print(f"[KRİTİK HATA] API Başlangıç Hatası: {error_message}", file=sys.stderr)
        return jsonify({"status": "fatal_error", "message": error_message}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)