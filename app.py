from flask import Flask, request, jsonify, url_for
from flask_cors import CORS
import os
from pdf2image import convert_from_path
from paddleocr import PaddleOCR
import pandas as pd
import re
import traceback
from werkzeug.utils import secure_filename
from datetime import datetime
from supabase import create_client
import shutil
from pathlib import Path
import tempfile
import shutil


app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app, supports_credentials=True)

@app.after_request
def add_cors_headers(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    return response

@app.route("/health")
def health():
    return "OK", 200

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
STATIC_FOLDER = "static"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(STATIC_FOLDER, exist_ok=True)

SUPABASE_URL = "https://nfcgehfenpjqrijxgzio.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5mY2dlaGZlbnBqcXJpanhnemlvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MDc0Mjk4MSwiZXhwIjoyMDY2MzE4OTgxfQ.B__RkNBjBlRn9QC7L72lL2wZKO7O3Yy2iM-Da1cllpc"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return '', 204

    try:
        file = request.files.get("file")
        car_id = request.form.get("carId", "CAR-UNKNOWN")
        car_date = request.form.get("date", str(datetime.today().date()))
        car_desc = request.form.get("description", "")

        if not file:
            return jsonify({"error": "No file uploaded"}), 400

        filename = secure_filename(file.filename or f"upload_{datetime.now().timestamp()}.pdf")
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)

        output_path, structured_data = process_pdf(file_path, car_id)
        if not os.path.exists(output_path):
            return jsonify({"error": "Excel file was not generated."}), 500

        # Step 1: Upload Excel to Supabase Storage
        bucket_name = "processed-car"
        final_filename = Path(output_path).name
        with open(output_path, "rb") as f:
            supabase.storage.from_(bucket_name).upload(
                path=final_filename,
                file=f,
                file_options={
                    "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                },
            )

        # Step 2: Get Public URL
        public_url = supabase.storage.from_(bucket_name).get_public_url(final_filename)

        # Step 3: Insert to car_reports
        supabase.table("car_reports").insert({
            "car_id": car_id,
            "description": car_desc,
            "date": car_date,
            "filename": filename,
            "submitted_at": datetime.utcnow().isoformat()
        }).execute()

        # Step 4: Insert parsed data + file_url to Output_to_merge
        supabase.table("Output_to_merge").insert({
            "source_car_id": car_id,
            "filename": filename,
            "extracted_data": structured_data,
            "file_url": public_url,
            "created_at": datetime.utcnow().isoformat()
        }).execute()

        # Step 5: Clean up
        os.remove(file_path)
        os.remove(output_path)

        # Step 6: Return URL
        return jsonify({
            "result": "✅ Excel generated and uploaded.",
            "download_url": public_url
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"❌ Server error: {str(e)}"}), 500

def process_pdf(pdf_path, car_id):
    output_path = os.path.join(OUTPUT_FOLDER, f"{car_id}_result.xlsx")
    car_no = car_id

    # Step 1: Convert PDF to images
    image_dir = tempfile.mkdtemp()
    images = convert_from_path(pdf_path, dpi=300, output_folder=image_dir, fmt="png")
    image_paths = sorted([os.path.join(image_dir, f) for f in os.listdir(image_dir) if f.endswith(".png")])

    # Step 2: Initialize PaddleOCR
    ocr = PaddleOCR(use_angle_cls=True, lang='en')

    # Step 3: OCR-based section detection
    section_a = []
    chronology = []
    section_b2 = []
    section_c = []
    section_d = []
    section_e1 = []
    section_e2 = []

    for i, img_path in enumerate(image_paths):
        result = ocr.ocr(img_path, cls=True)
        lines = [line[-1][0] for block in result for line in block]

        for line in lines:
            if "CAR No" in line:
                section_a.append({
                    "CAR NO.": line.split("CAR No")[-1].strip(),
                    "ID NO. SEC A": car_id
                })
            elif "Chronology" in line or "Finding" in line:
                chronology.append({
                    "ID NO. SEC A": car_id,
                    "CAR NO.": car_id,
                    "ID NO. SEC B": f"{car_id}-B1-{i+1}",
                    "DETAILS": line.strip()
                })
            elif "Cost Impact" in line or "MYR" in line:
                section_b2.append({
                    "ID NO. SEC A": car_id,
                    "CAR NO.": car_id,
                    "ID NO. SEC B": "1",
                    "COST IMPACTED BREAKDOWN ": "Detected in OCR",
                    "COST(MYR)": "TBA"
                })
            elif "Causal Factor" in line or "Why" in line:
                section_c.append({
                    "ID NO. SEC A": car_id,
                    "CAR NO.": car_id,
                    "ID NO. SEC C": "1",
                    "CAUSAL FACTOR": "Detected in OCR",
                    "WHY": line,
                    "ANSWER": ""
                })
            elif "Correction Taken" in line:
                section_d.append({
                    "ID NO. SEC A": car_id,
                    "CAR NO.": car_id,
                    "ID NO. SEC D": "1",
                    "CORRECTION TAKEN": line,
                    "PIC": "",
                    "IMPLEMENTATION DATE": "",
                    "CLAUSE CODE": ""
                })
            elif "Corrective Action" in line:
                section_e1.append({
                    "ID NO. SEC A": car_id,
                    "CAR NO.": car_id,
                    "ID NO. SEC E": "1",
                    "CORRECTION ACTION": line,
                    "PIC": "",
                    "IMPLEMENTATION DATE": ""
                })
            elif "Accepted" in line:
                section_e2.append({
                    "ID NO. SEC A": car_id,
                    "CAR NO.": car_id,
                    "Accepted": "Yes" if "X" in line else "",
                    "Rejected": "Yes" if "Rejected" in line and "X" in line else ""
                })

    # Fallbacks if sections are empty
    if not section_a:
        section_a.append({"CAR NO.": car_id, "ID NO. SEC A": car_id})
    if not section_e2:
        section_e2.append({"ID NO. SEC A": car_id, "CAR NO.": car_id, "Accepted": "", "Rejected": ""})

    # Convert to DataFrames
    df_a = pd.DataFrame(section_a)
    df_b1 = pd.DataFrame(chronology)
    df_b2 = pd.DataFrame(section_b2)
    df_c = pd.DataFrame(section_c)
    df_d = pd.DataFrame(section_d)
    df_e1 = pd.DataFrame(section_e1)
    df_e2 = pd.DataFrame(section_e2)

    # Write to Excel
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_a.to_excel(writer, sheet_name="Section A", index=False)
        df_b1.to_excel(writer, sheet_name="Section B1 Chronology", index=False)
        df_b2.to_excel(writer, sheet_name="Section B2 Cost Impacted", index=False)
        df_c.to_excel(writer, sheet_name="Section C 5Why QA", index=False)
        df_d.to_excel(writer, sheet_name="Section D Corrective Taken", index=False)
        df_e1.to_excel(writer, sheet_name="Section E1 Corrective Action", index=False)
        df_e2.to_excel(writer, sheet_name="Section E2 Conclusion", index=False)

    # Clean temp images
    shutil.rmtree(image_dir, ignore_errors=True)

    structured_data = {
        "Section_A": df_a.to_dict(orient="records"),
        "Section_B1": df_b1.to_dict(orient="records"),
        "Section_B2": df_b2.to_dict(orient="records"),
        "Section_C": df_c.to_dict(orient="records"),
        "Section_D": df_d.to_dict(orient="records"),
        "Section_E1": df_e1.to_dict(orient="records"),
        "Section_E2": df_e2.to_dict(orient="records")
    }

    return output_path, structured_data

