	import json
import os
import sys
import time
import random
from typing import Dict, List
import hashlib
from datetime import datetime, timedelta, timezone
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

class CacheManager:
    """
    Her veri tipi için ayrı cache kontrolü yapan sınıf.
    HTML içeriğinden hash üretir ve değişiklik varsa scrape eder.
    """
    
    # Her veri tipi için cache süresi (dakika cinsinden)
    CACHE_DURATIONS = {
        'squad': 10080,         
        'injuries': 10080,        
        'suspensions': 10080,    
        'suspensions_kader': 10080,
        'new_suspensions': 10080,
        'position': 1440,         
        'form': 10080,            
        'stats': 4320,         
    }
    
    def __init__(self, db):
        self.db = db
    
    def get_content_hash(self, url: str, selector: str = None) -> str | None:
        """
        Verilen URL'den içerik çeker ve hash oluşturur.
        
        Args:
            url: Scrape edilecek URL
            selector: CSS seçici (belirli bir bölümü hash'lemek için)
        
        Returns:
            İçeriğin SHA256 hash'i veya hata durumunda None
        """
        try:
            soup = get_soup(url)
            
            if selector:
                content = soup.select_one(selector)
                if not content:
                    print(f"[CACHE] Seçici bulunamadı: {selector}", file=sys.stderr)
                    return None
                text = content.get_text(strip=True)
            else:
                text = soup.get_text(strip=True)
            
            # Whitespace'leri normalize et
            normalized = re.sub(r'\s+', ' ', text).strip()
            
            # Hash oluştur
            return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        
        except Exception as e:
            print(f"[CACHE HATA] Hash oluşturulamadı ({url}): {e}", file=sys.stderr)
            return None
    
    def should_scrape(self, team_name: str, data_type: str, current_hash: str) -> bool:
        """
        Cache kontrolü yapar ve scrape gerekip gerekmediğini döner.
        
        Args:
            team_name: Takım adı (küçük harf)
            data_type: Veri tipi ('squad', 'injuries', vs.)
            current_hash: Şu anki içeriğin hash'i
        
        Returns:
            True ise scrape et, False ise cache'den kullan
        """
        try:
            # Firestore'dan cache metadata'yı çek
            cache_ref = self.db.collection('cache_metadata').document(team_name)
            cache_doc = cache_ref.get()
            
            if not cache_doc.exists:
                print(f"[CACHE] İlk scrape: {team_name}/{data_type}", file=sys.stderr)
                return True
            
            cache_data = cache_doc.to_dict()
            
            # Bu veri tipi için cache bilgisi var mı?
            if data_type not in cache_data:
                print(f"[CACHE] Yeni veri tipi: {team_name}/{data_type}", file=sys.stderr)
                return True
            
            type_cache = cache_data[data_type]
            last_hash = type_cache.get('hash')
            last_update = type_cache.get('last_update')
            
            # Hash değişmiş mi?
            if current_hash != last_hash:
                print(f"[CACHE] İçerik değişmiş: {team_name}/{data_type}", file=sys.stderr)
                return True
            
            # Cache süresi dolmuş mu?
            if last_update:
                cache_duration = self.CACHE_DURATIONS.get(data_type, 60)
                now = datetime.now(timezone.utc)
                expiry_time = last_update + timedelta(minutes=cache_duration)
                
                if now> expiry_time:
                    print(f"[CACHE] Süresi dolmuş: {team_name}/{data_type} ({cache_duration} dk)", file=sys.stderr)
                    return True
            
            print(f"[CACHE HIT] ✓ Kullanılıyor: {team_name}/{data_type}", file=sys.stderr)
            return False
        
        except Exception as e:
            print(f"[CACHE HATA] Kontrol başarısız ({team_name}/{data_type}): {e}", file=sys.stderr)
            # Hata durumunda güvenli taraf: scrape et
            return True

    def get_suspension_hash(self, url: str) -> str | None:
        """
        Suspension sayfası için özel hash - sadece cezalı oyuncu isimlerini hashler.
        """
        try:
            soup = get_soup(url)

            # Cezalı oyuncuları bul
            suspended_players = []

            for row in soup.find_all("tr", class_=["odd", "even"]):
                ausfall_span = row.find("span", class_="ausfall-table")
                if ausfall_span:
                    name_td = row.find("td", class_="hauptlink")
                    if name_td:
                        player_name = name_td.get_text(strip=True)
                        ceza_bilgi = ausfall_span.get("title", "")
                        suspended_players.append(f"{player_name}:{ceza_bilgi}")

            # Oyuncuları sırala
            suspended_players.sort()

            # ← ÖNEMLİ DEĞİŞİKLİK: Boş liste için özel işaret
            if not suspended_players:
                hash_data = "NO_SUSPENSIONS"  # Boş liste için özel değer
            else:
                hash_data = "|".join(suspended_players)

            print(f"[SUSPENSION HASH] Cezalılar: {hash_data[:100]}", file=sys.stderr)

            return hashlib.sha256(hash_data.encode('utf-8')).hexdigest()

        except Exception as e:
            print(f"[CACHE HATA] Suspension hash oluşturulamadı: {e}", file=sys.stderr)
            return None
    
    def update_cache(self, team_name: str, data_type: str, content_hash: str):
        """
        Cache metadata'yı günceller.
        
        Args:
            team_name: Takım adı (küçük harf)
            data_type: Veri tipi
            content_hash: Yeni hash değeri
        """
        try:
            cache_ref = self.db.collection('cache_metadata').document(team_name)
            now = datetime.now(timezone.utc)
            cache_ref.set({
                data_type: {
                    'hash': content_hash,
                    'last_update': now,
                    'last_scraped': now.isoformat()
                }
            }, merge=True)
            
            print(f"[CACHE] ✓ Güncellendi: {team_name}/{data_type}", file=sys.stderr)
        
        except Exception as e:
            print(f"[CACHE HATA] Güncellenemedi ({team_name}/{data_type}): {e}", file=sys.stderr)


# Takım Sözlüğü (Değiştirilmedi)
TEAMS = {
    "chapecoense": {"name": "Chapecoense", "slug": "chapecoense", "id": "17776", "besoccer_slug": "chapecoense"},
    "remo": {"name": "Remo", "slug": "clube-do-remo-pa-", "id": "10997", "besoccer_slug": "remo"},
    "coritiba": {"name": "Coritiba", "slug": "coritiba-fc", "id": "776", "besoccer_slug": "coritiba-fbc"},
    "athletico": {"name": "Athletico", "slug": "club-athletico-paranaense", "id": "679", "besoccer_slug": "atletico-paranaense"},
    "tondela": {"name": "Tondela", "slug": "cd-tondela", "id": "7179", "besoccer_slug": "tondela"},
    "moreirense": {"name": "Moreirense", "slug": "moreirense-fc", "id": "979", "besoccer_slug": "moreirense-fc"},
    "santa clara": {"name": "Santa Clara", "slug": "cd-santa-clara", "id": "2423", "besoccer_slug": "santa-clara"},
    "nacional": {"name": "Nacional", "slug": "cd-nacional", "id": "982", "besoccer_slug": "nacional"},
    "avs": {"name": "AVS", "slug": "avs-futebol-sad", "id": "110302", "besoccer_slug": "aves-futebol-sad"},
    "porto": {"name": "Porto", "slug": "fc-porto", "id": "720", "besoccer_slug": "fc-porto"},
    "rio ave": {"name": "Rio Ave", "slug": "rio-ave-fc", "id": "2425", "besoccer_slug": "rio-ave"},
    "sporting": {"name": "Sporting", "slug": "sporting-lissabon", "id": "336", "besoccer_slug": "sporting-lisbon"},
    "benfica": {"name": "Benfica", "slug": "benfica-lissabon", "id": "294", "besoccer_slug": "benfica"},
    "braga": {"name": "Braga", "slug": "sc-braga", "id": "1075", "besoccer_slug": "sporting-braga"},
    "gil vicente": {"name": "Gil Vicente", "slug": "gil-vicente-fc", "id": "2424", "besoccer_slug": "gil-vicente"},
    "arouca": {"name": "Arouca", "slug": "fc-arouca", "id": "8024", "besoccer_slug": "arouca"},
    "vitória sc": {"name": "Vitória SC", "slug": "vitoria-guimaraes-sc", "id": "2420", "besoccer_slug": "vitoria-guimaraes"},
    "casa pia": {"name": "Casa Pia", "slug": "casa-pia-ac", "id": "3268", "besoccer_slug": "casa-pia"},
    "alverca": {"name": "Alverca", "slug": "fc-alverca", "id": "2521", "besoccer_slug": "alverca"},
    "estoril": {"name": "Estoril", "slug": "gd-estoril-praia", "id": "1465", "besoccer_slug": "estoril"},
    "estrela": {"name": "Estrela", "slug": "cf-estrela-amadora-sad", "id": "2431", "besoccer_slug": "cf-estrela-de-amadora"},
    "famalicão": {"name": "Famalicão", "slug": "fc-famalicao", "id": "3329", "besoccer_slug": "famalicao"},
    "heracles": {"name": "Heracles", "slug": "heracles-almelo", "id": "1304", "besoccer_slug": "heracles"},
    "volendam": {"name": "Volendam", "slug": "fc-volendam", "id": "724", "besoccer_slug": "fc-volendam"},
    "telstar": {"name": "Telstar", "slug": "sc-telstar", "id": "1434", "besoccer_slug": "stormvogels-telstar"},
    "excelsior": {"name": "Excelsior", "slug": "sbv-excelsior-rotterdam", "id": "798", "besoccer_slug": "excelsior"},
    "nac breda": {"name": "NAC Breda", "slug": "nac-breda", "id": "132", "besoccer_slug": "nac-breda"},
    "pec zwolle": {"name": "PEC Zwolle", "slug": "pec-zwolle", "id": "1269", "besoccer_slug": "fc-zwolle"},
    "go ahead": {"name": "Go Ahead", "slug": "go-ahead-eagles-deventer", "id": "1435", "besoccer_slug": "go-ahead-eagles"},
    "heerenveen": {"name": "Heerenveen", "slug": "sc-heerenveen", "id": "306", "besoccer_slug": "heerenveen"},
    "sparta": {"name": "Sparta", "slug": "sparta-rotterdam", "id": "468", "besoccer_slug": "sparta-rotterdam"},
    "f. sittard": {"name": "F. Sittard", "slug": "fortuna-sittard", "id": "385", "besoccer_slug": "fortuna-sittard"},
    "utrecht": {"name": "Utrecht", "slug": "fc-utrecht", "id": "200", "besoccer_slug": "fc-utrecht"},
    "twente": {"name": "Twente", "slug": "fc-twente-enschede", "id": "317", "besoccer_slug": "fc-twente-1965"},
    "nec nijmegen": {"name": "NEC Nijmegen", "slug": "nec-nijmegen", "id": "467", "besoccer_slug": "nec"},
    "groningen": {"name": "Groningen", "slug": "fc-groningen", "id": "202", "besoccer_slug": "fc-groningen"},
    "az alkmaar": {"name": "AZ Alkmaar", "slug": "az-alkmaar", "id": "1090", "besoccer_slug": "az"},
    "ajax": {"name": "Ajax", "slug": "ajax-amsterdam", "id": "610", "besoccer_slug": "ajax"},
    "psv": {"name": "PSV", "slug": "psv-eindhoven", "id": "383", "besoccer_slug": "psv"},
    "feyenoord": {"name": "Feyenoord", "slug": "feyenoord-rotterdam", "id": "234", "besoccer_slug": "feyenoord"},
    "lecce": {"name": "Lecce", "slug": "us-lecce", "id": "1005", "besoccer_slug": "lecce"},
    "cremonese": {"name": "Cremonese", "slug": "us-cremonese", "id": "2239", "besoccer_slug": "us-cremonese"},
    "cagliari": {"name": "Cagliari", "slug": "cagliari-calcio", "id": "1390", "besoccer_slug": "cagliari"},
    "verona": {"name": "Verona", "slug": "hellas-verona", "id": "276", "besoccer_slug": "hellas-verona-fc"},
    "pisa": {"name": "Pisa", "slug": "ac-pisa-1909", "id": "4172", "besoccer_slug": "pisa-calcio"},
    "genoa": {"name": "Genoa", "slug": "genua-cfc", "id": "252", "besoccer_slug": "genoa"},
    "udinese": {"name": "Udinese", "slug": "udinese-calcio", "id": "410", "besoccer_slug": "udinese"},
    "sassuolo": {"name": "Sassuolo", "slug": "us-sassuolo", "id": "6574", "besoccer_slug": "us-sassuolo-calcio"},
    "parma": {"name": "Parma", "slug": "parma-calcio-1913", "id": "130", "besoccer_slug": "parma-fc" },
    "torino": {"name": "Torino", "slug": "fc-turin", "id": "416", "besoccer_slug": "torino-fc"},
    "como": {"name": "Como", "slug": "como-1907", "id": "1047", "besoccer_slug": "como"},
    "bologna": {"name": "Bologna", "slug": "fc-bologna", "id": "1025", "besoccer_slug": "bologna"},
    "lazio": {"name": "Lazio", "slug": "lazio-rom", "id": "398", "besoccer_slug": "lazio"},
    "fiorentina": {"name": "Fiorentina", "slug": "ac-florenz", "id": "430", "besoccer_slug": "fiorentina"},
    "roma": {"name": "Roma", "slug": "as-rom", "id": "12", "besoccer_slug": "roma"},
    "atalanta": {"name": "Atalanta", "slug": "atalanta-bergamo", "id": "800", "besoccer_slug": "atalanta"},
    "napoli": {"name": "Napoli", "slug": "ssc-neapel", "id": "6195", "besoccer_slug": "napoli"},
    "milan": {"name": "Milan", "slug": "ac-mailand", "id": "5", "besoccer_slug": "milan"},
    "juventus": {"name": "Juventus", "slug": "juventus-turin", "id": "506", "besoccer_slug": "juventus-fc"},
    "inter": {"name": "Inter", "slug": "inter-mailand", "id": "46", "besoccer_slug": "internazionale"},
    "al-hazem": {"name": "Al-Hazem", "slug": "al-hazm", "id": "9131", "besoccer_slug": "al-hazm-rass"},
    "al-najma": {"name": "Al-Najma", "slug": "al-najma", "id": "32328", "besoccer_slug": "al-najma"},
    "neom sc": {"name": "NEOM SC", "slug": "al-suqoor", "id": "34911", "besoccer_slug": "al-suqoor"},
    "al-okhdood": {"name": "Al-Okhdood", "slug": "al-akhdoud-club", "id": "71665", "besoccer_slug": "al-akhdoud-saudi"},
    "damac": {"name": "Damac", "slug": "damac-fc", "id": "50532", "besoccer_slug": "dhamk-club"},
    "al-fayha": {"name": "Al-Fayha", "slug": "al-fayha-fc", "id": "50531", "besoccer_slug": "al-feiha"},
    "al-khaleej": {"name": "Al-Khaleej", "slug": "al-khaleej", "id": "6070", "besoccer_slug": "al-khaleej"},
    "al-riyadh": {"name": "Al-Riyadh", "slug": "al-riad", "id": "31008", "besoccer_slug": "al-riyadh"},
    "al-fateh": {"name": "Al-Fateh", "slug": "al-fateh", "id": "27221", "besoccer_slug": "al-fateh"},
    "al-kholood": {"name": "Al-Kholood", "slug": "al-kholood", "id": "91427", "besoccer_slug": "al-kholood-saudi"},
    "al-taawoun": {"name": "Al-Taawoun", "slug": "al-taawoun-fc", "id": "28844", "besoccer_slug": "al-taawon"},
    "al-ettifaq": {"name": "Al-Ettifaq", "slug": "al-ettifaq", "id": "7732", "besoccer_slug": "al-ittifaq-dammam"},
    "al-shabab": {"name": "Al-Shabab", "slug": "al-shabab-riad", "id": "9840", "besoccer_slug": "al-shabab"},
    "al-ahli": {"name": "Al-Ahli", "slug": "al-ahli-dschidda", "id": "18487", "besoccer_slug": "al-ahli-jeddah"},
    "al-qadsiah": {"name": "Al-Qadsiah", "slug": "al-qadisiyah-fc", "id": "26069", "besoccer_slug": "al-quadisiya-khobar"},
    "al-nassr": {"name": "Al-Nassr", "slug": "al-nasr-riad", "id": "18544", "besoccer_slug": "al-nassr"},
    "al-hilal": {"name": "Al-Hilal", "slug": "al-hilal-riad", "id": "1114", "besoccer_slug": "al-hilal"},
    "al-ittihad": {"name": "Al-Ittihad", "slug": "al-ittihad-dschidda", "id": "8023", "besoccer_slug": "al-ittihad"},
    "sport recife": {"name": "Sport Recife", "slug": "sport-club-do-recife", "id": "8718", "besoccer_slug": ""},
    "juventude": {"name": "Juventude", "slug": "esporte-clube-juventude", "id": "10492", "besoccer_slug": ""},
    "vasco": {"name": "Vasco", "slug": "vasco-da-gama-rio-de-janeiro", "id": "978", "besoccer_slug": "vasco-da-gama"},
    "fortaleza": {"name": "Fortaleza", "slug": "fortaleza-esporte-clube", "id": "10870", "besoccer_slug": ""},
    "vitória": {"name": "Vitória", "slug": "esporte-clube-vitoria", "id": "2125", "besoccer_slug": "vitoria"},
    "grêmio": {"name": "Grêmio", "slug": "gremio-porto-alegre", "id": "210", "besoccer_slug": "gremio-porto-alegre"},
    "santos": {"name": "Santos", "slug": "fc-santos", "id": "221", "besoccer_slug": "santos-fc"},
    "corinthians": {"name": "Corinthians", "slug": "corinthians-sao-paulo", "id": "199", "besoccer_slug": "corinthians-sao-paulo"},
    "ceará sc": {"name": "Ceará SC", "slug": "ceara-sporting-club", "id": "2029", "besoccer_slug": ""},
    "sc inter": {"name": "SC Inter", "slug": "sc-internacional-porto-alegre", "id": "6600", "besoccer_slug": "internacional"},
    "atlético-mg": {"name": "Atlético-MG", "slug": "clube-atletico-mineiro", "id": "330", "besoccer_slug": "atletico-mineiro"},
    "fluminense": {"name": "Fluminense", "slug": "fluminense-rio-de-janeiro", "id": "2462", "besoccer_slug": "fluminense-rio-janeiro"},
    "bragantino": {"name": "Bragantino", "slug": "red-bull-bragantino", "id": "8793", "besoccer_slug": "bragantino"},
    "são paulo": {"name": "São Paulo", "slug": "fc-sao-paulo", "id": "585", "besoccer_slug": "sao-paulo-fc"},
    "mirassol": {"name": "Mirassol", "slug": "mirassol-futebol-clube-sp-", "id": "3876", "besoccer_slug": "mirassol"},
    "botafogo": {"name": "Botafogo", "slug": "botafogo-rio-de-janeiro", "id": "537", "besoccer_slug": "botafogo-rio-janeiro"},
    "bahia": {"name": "Bahia", "slug": "esporte-clube-bahia", "id": "10010", "besoccer_slug": "ec-bahia"},
    "palmeiras": {"name": "Palmeiras", "slug": "se-palmeiras-sao-paulo", "id": "1023", "besoccer_slug": "palmeiras"},
    "cruzeiro": {"name": "Cruzeiro", "slug": "ec-cruzeiro-belo-horizonte", "id": "609", "besoccer_slug": "cruzeiro-belo-horizonte"},
    "flamengo": {"name": "Flamengo", "slug": "flamengo-rio-de-janeiro", "id": "614", "besoccer_slug": "flamengo-rio-janeiro"},
    "psg": {"name": "PSG", "slug": "fc-paris-saint-germain", "id": "583", "besoccer_slug": "paris-saint-germain-fc"},
    "marsilya": {"name": "Marsilya", "slug": "olympique-marseille", "id": "244", "besoccer_slug": "olympique-marsella"},
    "monaco": {"name": "Monaco", "slug": "as-monaco", "id": "162", "besoccer_slug": "monaco"},
    "nice": {"name": "Nice", "slug": "ogc-nizza", "id": "417", "besoccer_slug": "nice"},
    "lille": {"name": "Lille", "slug": "losc-lille", "id": "1082", "besoccer_slug": "losc-lille"},
    "lyon": {"name": "Lyon", "slug": "olympique-lyon", "id": "1041", "besoccer_slug": "olympique-lyonnais"},
    "strasbourg": {"name": "Strasbourg", "slug": "rc-strassburg-alsace", "id": "667", "besoccer_slug": "strasbourg"},
    "lens": {"name": "Lens", "slug": "rc-lens", "id": "826", "besoccer_slug": "lens"},
    "brest": {"name": "Brest", "slug": "stade-brest-29", "id": "3911", "besoccer_slug": "stade-brestois-29"},
    "toulouse": {"name": "Toulouse", "slug": "fc-toulouse", "id": "415", "besoccer_slug": "toulouse-fc"},
    "aj auxerre": {"name": "AJ Auxerre", "slug": "aj-auxerre", "id": "290", "besoccer_slug": "auxerre"},
    "rennes": {"name": "Rennes", "slug": "fc-stade-rennes", "id": "273", "besoccer_slug": "stade-rennes"},
    "nantes": {"name": "Nantes", "slug": "fc-nantes", "id": "995", "besoccer_slug": "nantes"},
    "angers": {"name": "Angers", "slug": "sco-angers", "id": "1420", "besoccer_slug": "angers-sco"},
    "le havre": {"name": "Le Havre", "slug": "ac-le-havre", "id": "738", "besoccer_slug": "havre-ac"},
    "lorient": {"name": "Lorient", "slug": "fc-lorient", "id": "1158", "besoccer_slug": "lorient"},
    "paris fc": {"name": "Paris FC", "slug": "paris-fc", "id": "10004", "besoccer_slug": "paris-sg"},
    "metz": {"name": "Metz", "slug": "fc-metz", "id": "347", "besoccer_slug": "metz"},
    "hoffenheim": {"name": "Hoffenheim", "slug": "tsg-1899-hoffenheim", "id": "533", "besoccer_slug": "tsg-1899-hoffenheim"},
    "heidenheim": {"name": "Heidenheim", "slug": "1-fc-heidenheim-1846", "id": "2036", "besoccer_slug": "heidenheim"},
    "köln": {"name": "Köln", "slug": "1-fc-koln", "id": "3", "besoccer_slug": "1-fc-koln"},
    "hamburg": {"name": "Hamburg", "slug": "hamburger-sv", "id": "41", "besoccer_slug": "hamburger-sv"},
    "st. pauli": {"name": "St. Pauli", "slug": "fc-st-pauli", "id": "35", "besoccer_slug": "st-pauli"},
    "u. berlin": {"name": "U. Berlin", "slug": "1-fc-union-berlin", "id": "89", "besoccer_slug": "1-fc-union-berlin"},
    "augsburg": {"name": "Augsburg", "slug": "fc-augsburg", "id": "167", "besoccer_slug": "fc-augsburg"},
    "wolfsburg": {"name": "Wolfsburg", "slug": "vfl-wolfsburg", "id": "82", "besoccer_slug": "wolfsburg"},
    "stuttgart": {"name": "Stuttgart", "slug": "vfb-stuttgart", "id": "79", "besoccer_slug": "stuttgart"},
    "gladbach": {"name": "Gladbach", "slug": "borussia-monchengladbach", "id": "18", "besoccer_slug": "borussia-monchengla"},
    "bremen": {"name": "Bremen", "slug": "sv-werder-bremen", "id": "86", "besoccer_slug": "werder-bremen"},
    "leipzig": {"name": "Leipzig", "slug": "rasenballsport-leipzig", "id": "23826", "besoccer_slug": "rb-leipzig"},
    "mainz": {"name": "Mainz", "slug": "1-fsv-mainz-05", "id": "39", "besoccer_slug": "mainz-amat"},
    "freiburg": {"name": "Freiburg", "slug": "sc-freiburg", "id": "60", "besoccer_slug": "sc-freiburg"},
    "frankfurt": {"name": "Frankfurt", "slug": "eintracht-frankfurt", "id": "24", "besoccer_slug": "eintracht-frankfurt"},
    "leverkusen": {"name": "Leverkusen", "slug": "bayer-04-leverkusen", "id": "15", "besoccer_slug": "bayer-leverkusen"},
    "real oviedo": {"name": "Real Oviedo", "slug": "real-oviedo", "id": "2497", "besoccer_slug": "real-oviedo"},
    "elche": {"name": "Elche", "slug": "fc-elche", "id": "1531", "besoccer_slug": "elche"},
    "levante": {"name": "Levante", "slug": "ud-levante", "id": "3368", "besoccer_slug": "levante"},
    "espanyol": {"name": "Espanyol", "slug": "espanyol-barcelona", "id": "714", "besoccer_slug": "espanyol"},
    "girona": {"name": "Girona", "slug": "fc-girona", "id": "12321", "besoccer_slug": "girona-fc"},
    "alavés": {"name": "Alavés", "slug": "deportivo-alaves", "id": "1108", "besoccer_slug": "alaves"},
    "getafe": {"name": "Getafe", "slug": "fc-getafe", "id": "3709", "besoccer_slug": "getafe"},
    "valencia": {"name": "Valencia", "slug": "fc-valencia", "id": "1049", "besoccer_slug": "valencia-cf"},
    "sociedad": {"name": "Sociedad", "slug": "real-sociedad-san-sebastian", "id": "681", "besoccer_slug": "real-sociedad"},
    "mallorca": {"name": "Mallorca", "slug": "rcd-mallorca", "id": "237", "besoccer_slug": "mallorca"},
    "osasuna": {"name": "Osasuna", "slug": "ca-osasuna", "id": "331", "besoccer_slug": "osasuna"},
    "celta vigo": {"name": "Celta Vigo", "slug": "celta-vigo", "id": "940", "besoccer_slug": "celta"},
    "rayo": {"name": "Rayo", "slug": "rayo-vallecano", "id": "367", "besoccer_slug": "rayo-vallecano"},
    "real betis": {"name": "Real Betis", "slug": "real-betis-sevilla", "id": "150", "besoccer_slug": "betis"},
    "villarreal": {"name": "Villarreal", "slug": "fc-villarreal", "id": "1050", "besoccer_slug": "villarreal"},
    "athletic bilbao": {"name": "Athletic Bilbao", "slug": "athletic-bilbao", "id": "621", "besoccer_slug": "athletic-bilbao"},
    "everton": {"name": "Everton", "slug": "fc-everton", "id": "29", "besoccer_slug": "everton-fc"},
    "leeds": {"name": "Leeds", "slug": "leeds-united", "id": "399", "besoccer_slug": "leeds-united-afc"},
    "brentford": {"name": "Brentford", "slug": "fc-brentford", "id": "1148", "besoccer_slug": "brentford"},
    "nottingham": {"name": "Nottingham", "slug": "nottingham-forest", "id": "703", "besoccer_slug": "nottingham-forest-fc"},
    "crystal palace": {"name": "Crystal Palace", "slug": "crystal-palace", "id": "873", "besoccer_slug": "crystal-palace-fc"},
    "wolves": {"name": "Wolves", "slug": "wolverhampton-wanderers", "id": "543", "besoccer_slug": "wolverhampton"},
    "burnley": {"name": "Burnley", "slug": "fc-burnley", "id": "1132", "besoccer_slug": "burnley-fc"},
    "tottenham": {"name": "Tottenham", "slug": "tottenham-hotspur", "id": "148", "besoccer_slug": "tottenham-hotspur-fc"},
    "west ham": {"name": "West Ham", "slug": "west-ham-united", "id": "379", "besoccer_slug": "west-ham-united"},
    "sunderland": {"name": "Sunderland", "slug": "afc-sunderland", "id": "289", "besoccer_slug": "sunderland-afc"},
    "fulham": {"name": "Fulham", "slug": "fc-fulham", "id": "931", "besoccer_slug": "fulham"},
    "brighton": {"name": "Brighton", "slug": "brighton-amp-hove-albion", "id": "1237", "besoccer_slug": "brighton-amp-hov"},
    "newcastle": {"name": "Newcastle", "slug": "newcastle-united", "id": "762", "besoccer_slug": "newcastle-united-fc"},
    "aston villa": {"name": "Aston Villa", "slug": "aston-villa", "id": "405", "besoccer_slug": "aston-villa-fc"},
    "liverpool": {"name": "Liverpool", "slug": "fc-liverpool", "id": "31", "besoccer_slug": "liverpool"},
    "bournemouth": {"name": "Bournemouth", "slug": "afc-bournemouth", "id": "989", "besoccer_slug": "afc-bournemouth"},
    "barcelona": {"name": "Barcelona", "slug": "fc-barcelona", "id": "131", "besoccer_slug": "barcelona"},
    "real madrid": {"name": "Real Madrid", "slug": "real-madrid", "id": "418", "besoccer_slug": "real-madrid"},
    "man united": {"name": "Man United", "slug": "manchester-united", "id": "985", "besoccer_slug": "manchester-united-fc"},
    "atletico madrid": {"name": "Atletico Madrid", "slug": "atletico-madrid", "id": "13", "besoccer_slug": "atletico-madrid"},
    "man city": {"name": "Man City", "slug": "manchester-city", "id": "281", "besoccer_slug": "manchester-city-fc"},
    "chelsea": {"name": "Chelsea", "slug": "chelsea", "id": "631", "besoccer_slug": "chelsea-fc"},
    "dortmund": {"name": "Dortmund", "slug": "borussia-dortmund", "id": "16", "besoccer_slug": "borussia-dortmund"},
    "sevilla": {"name": "Sevilla", "slug": "fc-sevilla", "id": "368", "besoccer_slug": "sevilla"},
    "arsenal": {"name": "Arsenal", "slug": "fc-arsenal", "id": "11", "besoccer_slug": "arsenal"},
    "bayern münih": {"name": "Bayern Münih", "slug": "fc-bayern-munchen", "id": "27", "besoccer_slug": "bayern-munchen"},
    "galatasaray": {"name": "Galatasaray", "slug": "galatasaray-istanbul", "id": "141", "besoccer_slug": "galatasaray-sk"},
    "fenerbahçe": {"name": "Fenerbahçe", "slug": "fenerbahce-istanbul", "id": "36", "besoccer_slug": "fenerbahce"},
    "beşiktaş": {"name": "Beşiktaş", "slug": "besiktas-istanbul", "id": "114", "besoccer_slug": "besiktas"},
    "trabzonspor": {"name": "Trabzonspor", "slug": "trabzonspor", "id": "449", "besoccer_slug": "trabzonspor"},
    "göztepe": {"name": "Göztepe", "slug": "goztepe", "id": "1467", "besoccer_slug": "goztepe"},
    "başakşehir": {"name": "Başakşehir", "slug": "istanbul-basaksehir-fk", "id": "6890", "besoccer_slug": "istanbul-bb"},
    "ç. rizespor": {"name": "Ç. Rizespor", "slug": "caykur-rizespor", "id": "126", "besoccer_slug": "caykur-rizespor"},
    "samsunspor": {"name": "Samsunspor", "slug": "samsunspor", "id": "152", "besoccer_slug": "samsunspor"},
    "kasımpaşa": {"name": "Kasımpaşa", "slug": "kasimpasa", "id": "10484", "besoccer_slug": "kasimpasa"},
    "eyüpspor": {"name": "Eyüpspor", "slug": "eyupspor", "id": "7160", "besoccer_slug": "eyupspor"},
    "alanyaspor": {"name": "Alanyaspor", "slug": "alanyaspor", "id": "11282", "besoccer_slug": "alanyaspor"},
    "antalyaspor": {"name": "Antalyaspor", "slug": "antalyaspor", "id": "589", "besoccer_slug": "antalyaspor"},
    "gaziantep fk": {"name": "Gaziantep FK", "slug": "gaziantep-fk", "id": "2832", "besoccer_slug": "gaziantep-bb"},
    "konyaspor": {"name": "Konyaspor", "slug": "konyaspor", "id": "2293", "besoccer_slug": "konyaspor"},
    "kayserispor": {"name": "Kayserispor", "slug": "kayserispor", "id": "3205", "besoccer_slug": "kayserispor"},
    "karagümrük": {"name": "Karagümrük", "slug": "fatih-karagumruk", "id": "6646", "besoccer_slug": "fatih-karagumruk"},
    "kocaelispor": {"name": "Kocaelispor", "slug": "kocaelispor", "id": "120", "besoccer_slug": "kocaelispor"},
    "gençlerbirliği": {"name": "Gençlerbirliği", "slug": "genclerbirligi-ankara", "id": "820", "besoccer_slug": "genclerbirligi-sk"},
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
    return BeautifulSoup(res.text, "lxml") # lxml parser'ı artık yüklü olmalı

def extract_first_int(s: str) -> int:
    """Bir string içindeki ilk tam sayıyı ayıkla. Yoksa 0 döner."""
    if not s:
        return 0
    s = s.replace("'", "").replace(".", "").replace(",", "").strip()
    m = re.search(r'(\d+)', s)
    return int(m.group(1)) if m else 0

def scrape_stats(team_slug: str, team_id: str) -> List[dict]:
    """Oyuncu istatistiklerini (oynadığı maç ve süre) çeker."""
    url = f"https://www.transfermarkt.com.tr/{team_slug}/leistungsdaten/verein/{team_id}"
    try:
        # requests.get'i PROXIES parametresi ile güncelle
        if PROXIES:
            print(f"[UYARI] Proxy kullanılıyor: {PROXY_URL}", file=sys.stderr)

        soup = get_soup(url)

        table = soup.select_one("table.items")
        if not table:
            print(f"[HATA] table.items bulunamadı → {team_slug}", file=sys.stderr)
            return None
        players = []
        rows = table.select("tbody tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 11:
                continue
            texts = [td.get_text(strip=True) for td in cells]

            raw_name = texts[3] if len(texts) > 3 else ""
            if not raw_name:
                continue

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

        return players

    except Exception as e:
        print(f"[HATA] {team_slug}: {e}", file=sys.stderr)
        return None

def scrape_stats_cached(team_slug: str, team_id: str, team_name: str, cache_mgr: CacheManager) -> List[dict] | None:
    """Cache-aware oyuncu istatistikleri"""
    url = f"https://www.transfermarkt.com.tr/{team_slug}/leistungsdaten/verein/{team_id}"
    
    content_hash = cache_mgr.get_content_hash(url, "table.items")
    if not content_hash:
        return scrape_stats(team_slug, team_id)
    
    if not cache_mgr.should_scrape(team_name, 'stats', content_hash):
        return None
    
    stats = scrape_stats(team_slug, team_id)
    
    if stats is not None:
        cache_mgr.update_cache(team_name, 'stats', content_hash)
    
    return stats

def scrape_suspensions(team_slug, team_id, squad):
    try:
        url_squad = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}"
        # get_soup zaten proxy kullanıyor
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

        return suspensions
    except Exception as e:
        print(f"Cezalılar veri hatası ({team_slug}): {e}", file=sys.stderr)
        return []

def scrape_besoccer_suspensions(soup: BeautifulSoup, squad: List[dict] = None) -> list:
    """
    Sadece soup üzerinden veriyi parse eden yardımcı fonksiyon.
    Sayfayı çekmez, sadece parse eder.
    """
    injuries_suspensions = []
    item_list = soup.find("ul", class_="item-list")
    
    if not item_list:
        return []

    items = item_list.find_all("li")
    
    for item in items:
        name_div = item.find("div", class_="main-text")
        reason_div = item.find("div", class_="sub-text1")
        
        if not name_div or not reason_div:
            continue
        
        player_name = name_div.get_text(strip=True)
        reason = reason_div.get_text(strip=True)
        
        # Pozisyon eşleştirme (squad'dan)
        position = ""
        if squad:
            matched = next((p for p in squad if p["name"] == player_name), None)
            position = matched["position"] if matched else ""
        
        # Status belirleme
        status = "Sakatlık"
        if "red card" in reason.lower():
            status = "Kırmızı Kart"
        elif "yellow" in reason.lower() or "suspension" in reason.lower():
            status = "Sarı Kart"
        
        injuries_suspensions.append({
            "name": player_name,
            "position": position,
            "status": status,
            "details": reason
        })
    
    return injuries_suspensions


def scrape_besoccer_suspensions_cached(besoccer_slug: str, team_name: str, 
                                        squad: List[dict], cache_mgr: CacheManager) -> list | None:
    """
    Cache-aware BeSoccer suspension scraping.
    Sayfayı sadece BİR KEZ çeker, hem hash hem scraping için kullanır.
    """
    url = f"https://www.besoccer.com/team/injuries-suspensions/{besoccer_slug}"
    
    try:
        # 1. Sayfayı BİR KEZ çek
        print(f"[BeSoccer] {besoccer_slug} için sayfa çekiliyor...", file=sys.stderr)
        soup = get_soup(url)
        
        if not soup:
            print(f"[HATA] {besoccer_slug} için soup oluşturulamadı", file=sys.stderr)
            return None

        # 2. Hash hesapla (aynı soup ile)
        item_list = soup.find("ul", class_="item-list")
        
        if not item_list:
            # Sayfa yüklendi ama liste yok (cezalı/sakatlı yok)
            print(f"[BeSoccer] {besoccer_slug} için item-list bulunamadı (boş liste)", file=sys.stderr)
            content_hash = hashlib.sha256("NO_DATA_BESOCCER".encode()).hexdigest()
            suspensions = []
        else:
            # Hash için veriyi topla
            raw_data = []
            for li in item_list.find_all("li"):
                name_div = li.find("div", class_="main-text")
                reason_div = li.find("div", class_="sub-text1")
                if name_div and reason_div:
                    raw_data.append(f"{name_div.get_text(strip=True)}:{reason_div.get_text(strip=True)}")
            
            raw_data.sort()  # Sıralama önemli (hash tutarlılığı için)
            
            if raw_data:
                hash_string = "|".join(raw_data)
            else:
                hash_string = "NO_DATA_BESOCCER"
            
            content_hash = hashlib.sha256(hash_string.encode()).hexdigest()
            
            print(f"[BESOCCER HASH] {hash_string[:100]}", file=sys.stderr)
            
            # 3. Veriyi parse et (aynı soup ile)
            suspensions = scrape_besoccer_suspensions_logic(soup, squad)

        # 4. Cache kontrolü
        if not cache_mgr.should_scrape(team_name, 'suspensions', content_hash):
            print(f"[CACHE HIT] {team_name}/suspensions (BeSoccer)", file=sys.stderr)
            return None

        # 5. Cache güncelle ve dön
        print(f"[SONUÇ] {team_name}/suspensions = {len(suspensions)} kayıt (BeSoccer)", file=sys.stderr)
        cache_mgr.update_cache(team_name, 'suspensions', content_hash)
        
        time.sleep(random.uniform(1.5, 3.0))
        
        return suspensions

    except Exception as e:
        print(f"[HATA] BeSoccer scrape başarısız ({besoccer_slug}): {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return None

def scrape_suspensions_cached(team_slug: str, team_id: str, squad: List[dict],
                              team_name: str, cache_mgr: CacheManager) -> List[dict] | None:
    """Cache-aware ceza scraping"""
    url = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}"
    
    # ← DEĞİŞTİ: Özel suspension hash kullan
    content_hash = cache_mgr.get_suspension_hash(url)
    if not content_hash:
        return scrape_suspensions(team_slug, team_id, squad)
    
    if not cache_mgr.should_scrape(team_name, 'suspensions', content_hash):
        print(f"[CACHE HIT] {team_name}/suspensions")
        return None
    
    print(f"[SCRAPING] {team_name}/suspensions")
    suspensions = scrape_suspensions(team_slug, team_id, squad)
    
    print(f"[SONUÇ] {team_name}/suspensions = {len(suspensions) if suspensions else 0} oyuncu")
    
    if suspensions is not None:
        cache_mgr.update_cache(team_name, 'suspensions', content_hash)
    
    return suspensions


def scrape_squad(team_slug: str, team_id: str) -> List[dict] | None:
    try:
        url = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}"
        soup = get_soup(url)

        table = soup.find("table", class_="items")
        if not table:
            raise ValueError("Squad table not found")

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

        return players

    except Exception as e:
        print(f"[HATA] Squad scrape başarısız ({team_slug}): {e}", file=sys.stderr)
        return None

def scrape_squad_cached(team_slug: str, team_id: str, team_name: str, cache_mgr: CacheManager) -> List[dict] | None:
    """Cache-aware kadro scraping"""
    url = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}"
    
    # Hash oluştur
    content_hash = cache_mgr.get_content_hash(url, "table.items")
    if not content_hash:
        print(f"[UYARI] Squad hash oluşturulamadı: {team_name}", file=sys.stderr)
        return scrape_squad(team_slug, team_id)  # Normal scrape'e devam et
    
    # Cache kontrolü
    if not cache_mgr.should_scrape(team_name, 'squad', content_hash):
        return None  # None = cache kullan, eski veriyi koru
    
    # Scrape et
    squad = scrape_squad(team_slug, team_id)
    
    # Başarılıysa cache'i güncelle
    if squad is not None:
        cache_mgr.update_cache(team_name, 'squad', content_hash)
    
    return squad

def scrape_injuries(team_slug: str, team_id: str, squad: List[dict]) -> List[dict] | None:
    url = f"https://www.transfermarkt.com.tr/{team_slug}/sperrenundverletzungen/verein/{team_id}"
    injuries = []
    try:
        # get_soup zaten proxy kullanıyor
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
        return injuries
    except Exception as e:
        print(f"Sakatlık verisi alınamadı: {e}", file=sys.stderr)
    return None

def scrape_injuries_cached(team_slug: str, team_id: str, squad: List[dict], 
                           team_name: str, cache_mgr: CacheManager) -> List[dict] | None:
    """Cache-aware sakatlık scraping"""
    url = f"https://www.transfermarkt.com.tr/{team_slug}/sperrenundverletzungen/verein/{team_id}"
    
    # Hash oluştur (sadece sakatlıklar bölümünden)
    content_hash = cache_mgr.get_content_hash(url, "table.items")
    if not content_hash:
        return scrape_injuries(team_slug, team_id, squad)
    
    # Cache kontrolü
    if not cache_mgr.should_scrape(team_name, 'injuries', content_hash):
        return None
    
    # Scrape et
    injuries = scrape_injuries(team_slug, team_id, squad)
    
    if injuries is not None:
        cache_mgr.update_cache(team_name, 'injuries', content_hash)
    
    return injuries



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
        # get_soup zaten proxy kullanıyor
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
        return
    except Exception as e:
        print(f"Lig sıralaması alınamadı: {e}", file=sys.stderr)
        return

def get_league_position_cached(team_name: str, league_key: str, cache_mgr: CacheManager) -> int | None:
    """Cache-aware lig pozisyonu"""
    url = get_league_url(league_key)
    if not url:
        return None
    
    content_hash = cache_mgr.get_content_hash(url, "table.items")
    if not content_hash:
        return get_league_position(team_name, league_key)
    
    if not cache_mgr.should_scrape(team_name.lower(), 'position', content_hash):
        return None
    
    position = get_league_position(team_name, league_key)
    
    if position is not None:
        cache_mgr.update_cache(team_name.lower(), 'position', content_hash)
    
    return position

def get_recent_form(team_name: str, league_key: str) -> dict:
    try:
        url = get_form_url(league_key)
        if not url:
            return
        # get_soup zaten proxy kullanıyor
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
        return
    except Exception as e:
        print(f"Form verisi alınamadı: {e}", file=sys.stderr)
        return

def get_recent_form_cached(team_name: str, league_key: str, cache_mgr: CacheManager) -> dict | None:
    """Cache-aware form tablosu"""
    url = get_form_url(league_key)
    if not url:
        return None
    
    content_hash = cache_mgr.get_content_hash(url, "div.responsive-table")
    if not content_hash:
        return get_recent_form(team_name, league_key)
    
    if not cache_mgr.should_scrape(team_name.lower(), 'form', content_hash):
        return None
    
    form = get_recent_form(team_name, league_key)
    
    if form is not None:
        cache_mgr.update_cache(team_name.lower(), 'form', content_hash)
    
    return form

def scrape_suspensions_kader(team_slug: str, team_id: str, season_id: int = 2025) -> list | None:

    url = f"https://www.transfermarkt.com.tr/{team_slug}/kader/verein/{team_id}/saison_id/{season_id}"

    try:
        soup = get_soup(url)

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
        return cezali_oyuncular

    except Exception as e:
        print(f"[UYARI] Kader cezalı scrape başarısız ({team_slug}): {e}", file=sys.stderr)
        return None

def scrape_suspensions_kader_cached(team_slug: str, team_id: str, team_name: str, 
                                     cache_mgr: CacheManager, season_id: int = 2025) -> list | None:
    """Cache-aware kader cezalı scraping"""
    url = f"https://www.transfermarkt.com.tr/{team_slug}/kader/verein/{team_id}/saison_id/{season_id}"
    
    # ← DEĞİŞTİ: Özel suspension hash kullan
    content_hash = cache_mgr.get_suspension_hash(url)
    if not content_hash:
        return scrape_suspensions_kader(team_slug, team_id, season_id)
    
    if not cache_mgr.should_scrape(team_name, 'suspensions_kader', content_hash):
        print(f"[CACHE HIT] {team_name}/suspensions_kader")
        return None
    
    print(f"[SCRAPING] {team_name}/suspensions_kader")
    suspensions = scrape_suspensions_kader(team_slug, team_id, season_id)
    
    print(f"[SONUÇ] {team_name}/suspensions_kader = {len(suspensions) if suspensions else 0} oyuncu")
    
    if suspensions is not None:
        cache_mgr.update_cache(team_name, 'suspensions_kader', content_hash)
    
    return suspensions


def generate_team_data(team_info: dict, league_key: str, cache_mgr: CacheManager) -> tuple[dict, List[dict], str]:
    """
    Cache-aware veri çekme. 
    None dönen değerler = eski veri kullanılacak (Firestore'da merge=True ile)
    """
    name = team_info["name"]
    slug = team_info["slug"]
    team_id = team_info["id"]
    besoccer_slug = team_info.get("besoccer_slug")
    team_doc = name.lower()
    
    print(f"🔄 {name} için cache-aware veri çekme başlıyor...", file=sys.stderr)
    
    # 1. Kadro (Cache-aware)
    squad = scrape_squad_cached(slug, team_id, team_doc, cache_mgr)
    
    # 2. Sakatlıklar ve Cezalılar (Kadro gerekli, ama cache'den gelebilir)
    injuries = None
    suspensions = None
    suspensions_kader = None

    # Eğer squad None ise (cache hit), mevcut squad'ı Firestore'dan çek
    if squad is None:
        try:
            doc = DB.collection("team_data").document(team_doc).get()
            if doc.exists:
                existing_squad = doc.to_dict().get('squad', [])
                # Sakatlık/ceza scrape için mevcut squad'ı kullan
                injuries = scrape_injuries_cached(slug, team_id, existing_squad, team_doc, cache_mgr)
                suspensions = scrape_suspensions_cached(slug, team_id, existing_squad, team_doc, cache_mgr)
                suspensions_kader = scrape_suspensions_kader_cached(slug, team_id, team_doc, cache_mgr)
        except Exception as e:
            print(f"[HATA] Firestore'dan squad alınamadı: {e}", file=sys.stderr)
    else:
        # Yeni squad scrape edildi, onunla devam et
        injuries = scrape_injuries_cached(slug, team_id, squad, team_doc, cache_mgr)
        suspensions = scrape_suspensions_cached(slug, team_id, squad, team_doc, cache_mgr)
        suspensions_kader = scrape_suspensions_kader_cached(slug, team_id, team_doc, cache_mgr)
    
    # 3. Bağımsız veriler (Cache-aware)
    position = get_league_position_cached(name, league_key, cache_mgr)
    form = get_recent_form_cached(name, league_key, cache_mgr)
    stats = scrape_stats_cached(slug, team_id, team_doc, cache_mgr)
    
    # 4. Veriyi birleştir (None olanlar eklenmez = eski veri korunur)
    data = {
        "team": name,
        "last_checked": datetime.now(timezone.utc).isoformat()  # Her zaman güncelle
    }
    
    if position is not None:
        data["position_in_league"] = position
    
    if squad is not None:
        data["squad"] = squad
    
    if injuries is not None:
        data["injuries"] = injuries
    
    if suspensions is not None or suspensions_kader is not None:
        combined_suspensions = []
        
        # suspensions varsa ekle
        if suspensions is not None:
            combined_suspensions.extend(suspensions)
        
        # suspensions_kader varsa ekle
        if suspensions_kader is not None:
            combined_suspensions.extend(suspensions_kader)
        
        data["suspensions"] = combined_suspensions
    
    if form is not None:
        data["recent_form"] = form
    
    print(f"✅ {name} için cache-aware veri çekme tamamlandı.", file=sys.stderr)
    print(f"   → Güncellenecek alanlar: {list(data.keys())}", file=sys.stderr)
    
    return data, stats, team_doc


def save_team_data(team_name: str, team_data: dict, player_stats: List[dict]) -> None:
    try:
        # Player stats'ı team_data'ya ekle
        if player_stats is not None:
            team_data["stats"] = player_stats
        
        # Save team data to team_data collection
        DB.collection("team_data").document(team_name.lower()).set(team_data, merge=True)
        print(f"✅ Firestore team_data'ya kaydedildi: {team_name}")
        
        # Save player stats to new_data collection
        if player_stats is not None:
            DB.collection("new_data").document(team_name.lower()).set({"player_stats": player_stats}, merge=True)
            print(f"✅ Firestore new_data'ya kaydedildi: {team_name}")
        else:
            print(f"[UYARI] {team_name} için player_stats kaydedilmedi (istatistik alınamadı)", file=sys.stderr)
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

        cache_mgr = CacheManager(DB)

        # --- EV SAHİBİ TAKIM İŞLEMİ (İzolasyon Bloğu) ---
        home_data = None
        home_stats = None
        home_doc = home_info['name'].lower()
        try:
            home_data, home_stats, home_doc = generate_team_data(home_info, league_key, cache_mgr)
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
            away_data, away_stats, away_doc = generate_team_data(away_info, league_key, cache_mgr)
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