from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import pdfplumber
import pandas as pd
from datetime import datetime
from werkzeug.utils import secure_filename
from supabase import create_client
from pathlib import Path
import shutil
import traceback
import re
from datetime import datetime

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "https://safesightai.vercel.app"}}, supports_credentials=True)

@app.after_request
def add_cors_headers(response):
    response.headers.add("Access-Control-Allow-Origin", "https://safesightai.vercel.app")
    response.headers.add("Access-Control-Allow-Credentials", "true")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    return response

# === Setup folders
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# === Supabase config
SUPABASE_URL = "https://nfcgehfenpjqrijxgzio.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5mY2dlaGZlbnBqcXJpanhnemlvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MDc0Mjk4MSwiZXhwIjoyMDY2MzE4OTgxfQ.B__RkNBjBlRn9QC7L72lL2wZKO7O3Yy2iM-Da1cllpc"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# === Text cleanup and pattern detection
def clean_text(text):
    return re.sub(r"\s+", " ", str(text).strip()) if text else ""

date_pattern = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")

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

        output_path, structured_data = process_pdf_with_pdfplumber(file_path, car_id)
        if not os.path.exists(output_path):
            return jsonify({"error": "Excel file was not generated."}), 500

        # Upload to Supabase
        bucket_name = "processed-car"
        final_filename = Path(output_path).name
        with open(output_path, "rb") as f:
            supabase.storage.from_(bucket_name).upload(
                path=final_filename,
                file=f,
                file_options={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
            )

        public_url = supabase.storage.from_(bucket_name).get_public_url(final_filename)

        # Save metadata
        supabase.table("car_reports").insert({
            "car_id": car_id,
            "description": car_desc,
            "date": car_date,
            "filename": filename,
            "submitted_at": datetime.utcnow().isoformat()
        }).execute()

        supabase.table("Output_to_merge").insert({
            "source_car_id": car_id,
            "filename": filename,
            "extracted_data": structured_data,
            "file_url": public_url,
            "created_at": datetime.utcnow().isoformat()
        }).execute()

        os.remove(file_path)
        os.remove(output_path)

        return jsonify({
            "result": "✅ Excel generated and uploaded.",
            "download_url": public_url
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"❌ Server error: {str(e)}"}), 500


def process_pdf_with_pdfplumber(pdf_path, car_id):
    output_path = os.path.join("outputs", f"{car_id}_result.xlsx")

    section_a, chronology, section_b2, section_c, section_d, section_e1, section_e2 = [], [], [], [], [], [], []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            tables = page.extract_tables()

            # === Section C: keep text-based extraction
            for line in text.splitlines():
                if "Causal Factor" in line or "Why" in line:
                    section_c.append({
                        "ID NO. SEC A": car_id,
                        "CAR NO.": car_id,
                        "ID NO. SEC C": "1",
                        "CAUSAL FACTOR": "Detected in text",
                        "WHY": line,
                        "ANSWER": ""
                    })

            section_state = None
            for table in tables:
                for row in table:
                    if not row:
                        continue

                    joined_row = " ".join(str(cell) for cell in row if cell).lower()

                    # Detect section headers
                    if "car no" in joined_row:
                        section_state = "A"
                        continue
                    elif "chronology" in joined_row or "finding" in joined_row:
                        section_state = "B1"
                        continue
                    elif "cost impact" in joined_row or "myr" in joined_row:
                        section_state = "B2"
                        continue
                    elif "correction taken" in joined_row:
                        section_state = "D"
                        continue
                    elif "corrective action" in joined_row:
                        section_state = "E1"
                        continue
                    elif "accepted" in joined_row or "rejected" in joined_row:
                        section_state = "E2"
                        continue

                    # === Section-specific extraction
                    cleaned = [clean_text(cell) for cell in row if cell]

                    if section_state == "A":
                        car_no = cleaned[0] if cleaned else car_id
                        section_a.append({
                            "CAR NO.": car_no,
                            "ID NO. SEC A": car_id
                        })

                    elif section_state == "B1":
                        chronology.append({
                            "ID NO. SEC A": car_id,
                            "CAR NO.": car_id,
                            "ID NO. SEC B": f"{car_id}-B1-{i+1}",
                            "DETAILS": " ".join(cleaned)
                        })

                    elif section_state == "B2":
                        breakdown = " ".join(cleaned)
                        cost = next((s for s in cleaned if re.search(r"\d+(?:,\d+)?(?:\.\d{2})?", s)), "TBA")
                        section_b2.append({
                            "ID NO. SEC A": car_id,
                            "CAR NO.": car_id,
                            "ID NO. SEC B": "1",
                            "COST IMPACTED BREAKDOWN ": breakdown,
                            "COST(MYR)": cost
                        })

                    elif section_state == "D":
                        section_d.append({
                            "ID NO. SEC A": car_id,
                            "CAR NO.": car_id,
                            "ID NO. SEC D": "1",
                            "CORRECTION TAKEN": cleaned[0] if len(cleaned) > 0 else "",
                            "PIC": cleaned[1] if len(cleaned) > 1 else "",
                            "IMPLEMENTATION DATE": cleaned[2] if len(cleaned) > 2 and date_pattern.match(cleaned[2]) else "",
                            "CLAUSE CODE": cleaned[3] if len(cleaned) > 3 else ""
                        })

                    elif section_state == "E1":
                        section_e1.append({
                            "ID NO. SEC A": car_id,
                            "CAR NO.": car_id,
                            "ID NO. SEC E": "1",
                            "CORRECTION ACTION": cleaned[0] if len(cleaned) > 0 else "",
                            "PIC": cleaned[1] if len(cleaned) > 1 else "",
                            "IMPLEMENTATION DATE": cleaned[2] if len(cleaned) > 2 and date_pattern.match(cleaned[2]) else ""
                        })

                    elif section_state == "E2":
                        accepted = "Yes" if "x" in joined_row and "accepted" in joined_row else ""
                        rejected = "Yes" if "x" in joined_row and "rejected" in joined_row else ""
                        section_e2.append({
                            "ID NO. SEC A": car_id,
                            "CAR NO.": car_id,
                            "Accepted": accepted,
                            "Rejected": rejected
                        })

    # === Fallbacks if empty
    if not section_a:
        section_a.append({"CAR NO.": car_id, "ID NO. SEC A": car_id})
    if not section_e2:
        section_e2.append({
            "ID NO. SEC A": car_id,
            "CAR NO.": car_id,
            "Accepted": "",
            "Rejected": ""
        })

    # === Convert to DataFrames
    df_a = pd.DataFrame(section_a)
    df_b1 = pd.DataFrame(chronology)
    df_b2 = pd.DataFrame(section_b2)
    df_c = pd.DataFrame(section_c)
    df_d = pd.DataFrame(section_d)
    df_e1 = pd.DataFrame(section_e1)
    df_e2 = pd.DataFrame(section_e2)

    # === Write to Excel
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_a.to_excel(writer, sheet_name="Section A", index=False)
        df_b1.to_excel(writer, sheet_name="Section B1 Chronology", index=False)
        df_b2.to_excel(writer, sheet_name="Section B2 Cost Impacted", index=False)
        df_c.to_excel(writer, sheet_name="Section C 5Why QA", index=False)
        df_d.to_excel(writer, sheet_name="Section D Corrective Taken", index=False)
        df_e1.to_excel(writer, sheet_name="Section E1 Corrective Action", index=False)
        df_e2.to_excel(writer, sheet_name="Section E2 Conclusion", index=False)

    # === Return structured data
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
