import json
import os
import time
import random
import sys
from typing import Dict, List
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import re

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

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/110.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
]

PROXIES = {
    "http": os.getenv("HTTP_PROXY"),
    "https": os.getenv("HTTPS_PROXY")
}

HEADERS = {
    "User-Agent": random.choice(USER_AGENTS),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": "https://www.transfermarkt.com.tr/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cookie": (
        "%7B%22signature%22%3A%22ID5_Ag1x6pmLZexKIJG_Pw7y-53i68Fpx1mmb-2Zc8tWFdabcKC30FVmVnIsnCWv0vVbJ65P3gkGUVJB8V1r6J3DG7rkwz038bbQ194tIkv12iF-PmUV1JqE6iIgIczYFViPRo93To1nvHtks4IqDguv8jQQNXc1AvIgvRIqQxSaqmZ0UNvR5IE%22%2C%22created_at%22%3A%222024-11-20T05%3A27%3A28.076Z%22%2C%22id5_consent%22%3Atrue%2C%22original_uid%22%3A%22ID5*eNs3AyzZxWFlzej2MgUALn92MBinO809LGqKXGOPmCJEwiiX4or-7WLUBly3qUD8RQLqT7QkKUUhFmysX0l-2kUJ-pxmcayHlLeuWmEGXj1EytxubHTSzzh9u9jjYaXeRMzVrAh-xAi9rTPhc49G_ETOfJ8mjd9uy8AcwPY7lI5FEP0dDmGx-35FnO8QoT5TRNss7eZbHtafbacXNYlYuETcXJ2qUNKL1dBclFmaYBtE39D23u9QDU4yhVRGXiGTROAExI3uuiWNtJsFoBjtNUTmK8KY7wfH1Y0pV7aYoiFE6ZdL0kIiGEg6r9KOcjpiROqm8j2RqzOh2_dmi8JrHETr2i83NNaJseevQivqycRE7URgk75QZ9JwRnEBQ1eJRLNprY5dh-piVp-PQuZkWUS0L248ar28r-vOKZAbmbBE9o8ge4i8w3oCjw9ruWrWRPiBW5iY2voUjE6OgxI5jkS5THoseo-5Pb3CFr5oDohEunxC9QEbT1g73dFRfg_xRLvoXguEmmznH0KHQXLC0ET7ySOBvnnktwm0scSgOZhE_Zn02FadnAX2fwdpDpZzRP53mUBzd9OP7CPOIyo8iQ%22%2C%22universal_uid%22%3A%22ID5*4CXogHGFyl1QWGOzkev1ccgYZls_zif4szNC9U2sEaREwjQa09HQhU7OWBWisEivRQI8bIbP1lK-PfvT-l3WBUUJAsD0Hfck7sp_vevNF6REykNRpjDh4HkLSQz_WYc1RMyqn5FMaSybAiXIZ3u0KETOtfpYm6r028PYhugzZDVFEGZHDbMu5yGrgsTuJ-55RNsTg5vpshIAUArElGrfAUTcIEjqIiwALiftUTQqIcxE3xyIIkslQkzWnDNZSRj6RODpA0dfGm72cEAL2bjNfUTmGmUTiFuBhwbXVFEsA8ZE6YvrQK_em0ex6YDJaAV4ROrN_iOiYFncX9UGGiIRIETr_idiDRPrM37DEUl7INJE7ZbVQW1r7QhkrUreRqweRLM8xyoaBLepiLk4ALe-U0S0-IlX26ERAtFYlBM6RChE9ojzpBlxlkA480VfrDnKRPjaGJ45PILVslvdvYvZG0S5DAGdd8rmDBiCvuCEwwtEuldNOdZj4IAMLnypjliQRLsJHXo5nhJpZMGo_5YPZET7GlxfIAKAhylW7av18WFE_cScH49O5c_-PLd4dCunRP7zPy9s-TmBE-QyeKOhlQ%22%2C%22link_type%22%3A2%2C%22cascade_needed%22%3Atrue%2C%22privacy%22%3A%7B%22jurisdiction%22%3A%22gdpr%22%2C%22id5_consent%22%3Atrue%7D%2C%22ext%22%3A%7B%22linkType%22%3A2%2C%22pba%22%3A%22811%2B%2BG%2FW%2FhARwChmudR7%2Bx%2F%2FmOoLnxTsJ4eLE6PTuA6uSgMTIYiUqGwGFMQtl4iy%22%7D%2C%22cache_control%22%3A%7B%22max_age_sec%22%3A7200%7D%2C%22ids%22%3A%7B%22id5id%22%3A%7B%22eid%22%3A%7B%22source%22%3A%22id5-sync.com%22%2C%22uids%22%3A%5B%7B%22id%22%3A%22ID5*4CXogHGFyl1QWGOzkev1ccgYZls_zif4szNC9U2sEaREwjQa09HQhU7OWBWisEivRQI8bIbP1lK-PfvT-l3WBUUJAsD0Hfck7sp_vevNF6REykNRpjDh4HkLSQz_WYc1RMyqn5FMaSybAiXIZ3u0KETOtfpYm6r028PYhugzZDVFEGZHDbMu5yGrgsTuJ-55RNsTg5vpshIAUArElGrfAUTcIEjqIiwALiftUTQqIcxE3xyIIkslQkzWnDNZSRj6RODpA0dfGm72cEAL2bjNfUTmGmUTiFuBhwbXVFEsA8ZE6YvrQK_em0ex6YDJaAV4ROrN_iOiYFncX9UGGiIRIETr_idiDRPrM37DEUl7INJE7ZbVQW1r7QhkrUreRqweRLM8xyoaBLepiLk4ALe-U0S0-IlX26ERAtFYlBM6RChE9ojzpBlxlkA480VfrDnKRPjaGJ45PILVslvdvYvZG0S5DAGdd8rmDBiCvuCEwwtEuldNOdZj4IAMLnypjliQRLsJHXo5nhJpZMGo_5YPZET7GlxfIAKAhylW7av18WFE_cScH49O5c_-PLd4dCunRP7zPy9s-TmBE-QyeKOhlQ%22%2C%22atype%22%3A1%2C%22ext%22%3A%7B%22linkType%22%3A2%2C%22pba%22%3A%22811%2B%2BG%2FW%2FhARwChmudR7%2Bx%2F%2FmOoLnxTsJ4eLE6PTuA6uSgMTIYiUqGwGFMQtl4iy%22%7D%7D%5D%7D%7D%7D%7D;"
        "pbjs-id5id_cst=v3sfEQ%3D%3D;"
        "pbjs-id5id_last=Mon%2C%2001%20Sep%202025%2016%3A25%3A50%20GMT;"
        "pbjs-unifiedid=%7B%22TDID_LOOKUP%22%3A%22FALSE%22%2C%22TDID_CREATED_AT%22%3A%222025-09-01T16%3A25%3A46%22%7D;"
        "pbjs-unifiedid_cst=vyx7LB8sEQ%3D%3D;"
        "sharedid=d4555e90-530f-4c00-801c-a35fb8ac89c4;"
        "sharedid_cst=v3sfEQ%3D%3D"
    )
}

def get_public_ip():
    try:
        response = requests.get("https://api.ipify.org", proxies=PROXIES, timeout=10)
        print(f"Kullanılan IP: {response.text}", file=sys.stderr)
        return response.text
    except Exception as e:
        print(f"IP alınamadı: {e}", file=sys.stderr)
        return None

def get_team_info(team_key: str) -> dict:
    key = team_key.lower()
    if key not in TEAMS:
        raise ValueError(f"{team_key} takımı bulunamadı. Geçerli takımlar: {list(TEAMS.keys())}")
    return TEAMS[key]

def get_soup(url: str) -> BeautifulSoup:
    try:
        time.sleep(random.uniform(2, 5))  # Rastgele gecikme
        res = requests.get(url, headers=HEADERS, proxies=PROXIES if PROXIES["http"] else None, timeout=30)
        res.raise_for_status()
        return BeautifulSoup(res.text, "lxml")
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Hatası ({url}): {e} - Status Code: {res.status_code}", file=sys.stderr)
        return None
    except requests.exceptions.RequestException as e:
        print(f"İstek Hatası ({url}): {e}", file=sys.stderr)
        return None

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
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        rows = soup.select("table.items tbody tr")
        players = []

        for row in rows:
            td_list = row.find_all("td")
            if len(td_list) < 5:
                continue

            # Oyuncu adı
            name_td = row.find("td", class_="hauptlink")
            a = name_td.find("a") if name_td else None
            name = a.get("title") if a and a.get("title") else (a.text.strip() if a else "")

            # Maç sayısı ve süre
            td_texts = [td.get_text(" ", strip=True) for td in td_list]
            raw_minutes = td_texts[-1] if len(td_texts) >= 1 else ""
            raw_played_matches = td_texts[-3] if len(td_texts) >= 3 else ""

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

def scrape_suspensions(team_slug, team_id, squad):
    try:
        url_squad = f"https://www.transfermarkt.com.tr/{team_slug}/startseite/verein/{team_id}"
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
        "fr1": "https://www.transfermarkt.com.tr/ligue-1/tabelle/wettbewerb/FR1",
        "br1": "https://www.transfermarkt.com.tr/campeonato-brasileiro-serie-a/tabelle/wettbewerb/BRA1",
        "sa1": "https://www.transfermarkt.com.tr/saudi-professional-league/tabelle/wettbewerb/SA1",
        "it1": "https://www.transfermarkt.com.tr/serie-a/tabelle/wettbewerb/IT1",
        "hl1": "https://www.transfermarkt.com.tr/eredivisie/tabelle/wettbewerb/NL1"
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
        "hl1": "https://www.transfermarkt.com.tr/eredivisie/formtabelle/wettbewerb/NL1"
    }
    return url_map.get(league_key.lower())

def get_league_position(team_name: str, league_key: str):
    try:
        url = get_league_url(league_key)
        if not url:
            return
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

def get_recent_form(team_name: str, league_key: str) -> dict:
    try:
        url = get_form_url(league_key)
        if not url:
            return
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

def generate_team_data(team_info: dict, league_key: str) -> tuple[dict, List[dict], str]:
    name = team_info["name"]
    slug = team_info["slug"]
    team_id = team_info["id"]

    squad = scrape_squad(slug, team_id)
    injuries = scrape_injuries(slug, team_id, squad)
    position = get_league_position(name, league_key)
    form = get_recent_form(name, league_key)
    suspensions = scrape_suspensions(slug, team_id, squad)
    stats = scrape_stats(slug, team_id)

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
    try:
        # Save team data to team_data collection
        DB.collection("team_data").document(team_name.lower()).set(team_data, merge=True)
        print(f"✅ Firestore team_data'ya kaydedildi: {team_name}")

        # Save player stats to new_data collection
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
    try:
        body = request.get_json()
        home_key = body.get("home_team")
        away_key = body.get("away_team")
        league_key = body.get("league_key")

        if not home_key or not away_key or not league_key:
            return jsonify({"error": "Eksik parametreler"}), 400

        home_info = get_team_info(home_key)
        away_info = get_team_info(away_key)

        get_public_ip()

        # Generate data for home team
        home_data, home_stats, home_doc = generate_team_data(home_info, league_key)
        # Generate data for away team
        away_data, away_stats, away_doc = generate_team_data(away_info, league_key)

        # Save both team data and player stats
        save_team_data(home_doc, home_data, home_stats)
        save_team_data(away_doc, away_data, away_stats)

        print(f"Maç: {home_info['name']} vs {away_info['name']}", file=sys.stderr)

        return jsonify({
            "status": "success",
            "message": f"{home_doc}, {away_doc} Firestore'a kaydedildi (team_data ve new_data)."
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)