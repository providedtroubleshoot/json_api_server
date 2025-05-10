import os
import json
import subprocess
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

@app.route("/")
def index():
    return "API çalışıyor"

@app.route("/generate-json", methods=["POST"])
def generate_json():
    try:
        data = request.get_json()

        # JSON dosyasını oluştur
        with open("output.json", "w") as f:
            json.dump(data, f, indent=4)

        # GITHUB_TOKEN'ı ortam değişkenlerinden al
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            return jsonify({"status": "error", "message": "GitHub token bulunamadı."}), 500

        # Token'lı repo adresi
        repo_url = f"https://{github_token}@github.com/providedtroubleshoot/json_api_server.git"

        # Git ayarları
        subprocess.run(["git", "config", "--local", "user.email", "bot@render.com"])
        subprocess.run(["git", "config", "--local", "user.name", "Render Bot"])
        subprocess.run(["git", "remote", "remove", "origin"], stderr=subprocess.DEVNULL)
        subprocess.run(["git", "remote", "add", "origin", repo_url])
        subprocess.run(["git", "add", "output.json"])
        subprocess.run(["git", "commit", "-m", "Auto update output.json"], check=True)

        # Push işlemi
        push_result = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)

        if push_result.returncode != 0:
            return jsonify({"status": "error", "message": push_result.stderr}), 500

        return jsonify({"status": "success", "message": "JSON oluşturuldu ve pushlandı."})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
