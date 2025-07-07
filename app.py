from flask import Flask, request, jsonify, render_template, url_for
from flask_cors import CORS
import os
import pdfplumber
import pandas as pd
import re
import traceback
from werkzeug.utils import secure_filename
from datetime import datetime
from supabase import create_client, Client
import shutil

# === Flask App with CORS ===
app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app, resources={r"/*": {"origins": "https://safesightai.vercel.app"}})

# === Supabase ===
SUPABASE_URL = "https://nfcgehfenpjqrijxgzio.supabase.co"
SUPABASE_KEY = "your-supabase-key"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
STATIC_FOLDER = "static"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(STATIC_FOLDER, exist_ok=True)

@app.route("/")
def index():
    return render_template("upload.html")

@app.route("/health")
def health():
    return "OK", 200

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        file = request.files.get("file")
        car_id = request.form.get("carId", "CAR-UNKNOWN")
        car_date = request.form.get("date", str(datetime.today().date()))
        car_desc = request.form.get("description", "")

        if not file:
            return jsonify({"error": "No file uploaded"}), 400

        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)

        output_path = process_pdf(file_path, car_id, car_date, car_desc)

        if not os.path.exists(output_path):
            return jsonify({"error": "Excel file was not generated."}), 500

        supabase_data = {
            "car_id": car_id,
            "description": car_desc,
            "date": car_date,
            "filename": filename,
            "submitted_at": datetime.utcnow().isoformat()
        }
        supabase.table("car_reports").insert(supabase_data).execute()

        final_filename = os.path.basename(output_path)  # Keep original name
        static_path = os.path.join(STATIC_FOLDER, final_filename)
        shutil.copy(output_path, static_path)  # Copy to static folder for download

        os.remove(file_path)

        return jsonify({
            "result": "✅ Excel generated successfully.",
            "download_url": url_for('static', filename=final_filename)
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"❌ Server error: {str(e)}"}), 500

# Bind port for deployment (e.g., Render)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


