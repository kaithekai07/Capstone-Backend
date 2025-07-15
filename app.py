# === STEP 1: Import Required Libraries ===
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import pdfplumber
import pandas as pd
from datetime import datetime
from werkzeug.utils import secure_filename
from supabase import create_client
from pathlib import Path
import traceback
import re

# === STEP 2: Initialize Flask App and CORS ===
app = Flask(__name__)
CORS(app, origins=["https://safesightai.vercel.app"], supports_credentials=True)

# === STEP 3: Setup Folders and Supabase Client ===
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

SUPABASE_URL = "https://nfcgehfenpjqrijxgzio.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5mY2dlaGZlbnBqcXJpanhnemlvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MDc0Mjk4MSwiZXhwIjoyMDY2MzE4OTgxfQ.B__RkNBjBlRn9QC7L72lL2wZKO7O3Yy2iM-Da1cllpc"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# === STEP 4: Define PDF Parsing Functions (Section A to E) ===
<existing function definitions remain unchanged>

# === STEP 5: Process PDF, Save Excel, Return Metadata ===
def process_pdf_with_pdfplumber(pdf_path, id_sec_a):
    output_path = os.path.join(OUTPUT_FOLDER, f"{id_sec_a}_result.xlsx")
    with pdfplumber.open(pdf_path) as pdf:
        tables = pdf.pages[0].extract_tables()
        df_a = extract_section_a(tables, id_sec_a)
        car_no = df_a["CAR NO."].iloc[0] if "CAR NO." in df_a.columns else id_sec_a
        df_b1 = extract_findings(pdf, id_sec_a, car_no)
        df_b2 = extract_cost_impact(pdf, id_sec_a, car_no)
        section_c_text = extract_section_c_text(pdf)
        df_c = extract_answers_after_point(section_c_text, id_sec_a, car_no)
        df_d = extract_corrections(pdf, id_sec_a, car_no)
        df_e1 = extract_corrective_action(pdf, id_sec_a, car_no)
        df_e2 = extract_conclusion_review(id_sec_a, car_no)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_a.to_excel(writer, sheet_name="Section A", index=False)
        df_b1.to_excel(writer, sheet_name="Section B1 Chronology", index=False)
        df_b2.to_excel(writer, sheet_name="Section B2 Cost Impacted", index=False)
        df_c.to_excel(writer, sheet_name="Section C 5Why QA", index=False)
        df_d.to_excel(writer, sheet_name="Section D Corrective Taken", index=False)
        df_e1.to_excel(writer, sheet_name="Section E1 Corrective Action", index=False)
        df_e2.to_excel(writer, sheet_name="Section E2 Conclusion", index=False)
    structured_data = {
        "Section_A": df_a.to_dict(orient="records"),
        "Section_B1": df_b1.to_dict(orient="records"),
        "Section_B2": df_b2.to_dict(orient="records"),
        "Section_C": df_c.to_dict(orient="records"),
        "Section_D": df_d.to_dict(orient="records"),
        "Section_E1": df_e1.to_dict(orient="records"),
        "Section_E2": df_e2.to_dict(orient="records")
    }
    return output_path, structured_data, df_a, df_b1, df_b2, df_c, df_d, df_e1, df_e2

# === STEP 6: Flask API Endpoint ===
@app.route("/analyze", methods=["POST"])
def analyze():
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

        output_path, structured_data, df_a, df_b1, df_b2, df_c, df_d, df_e1, df_e2 = process_pdf_with_pdfplumber(file_path, car_id)

        reporter = df_a["REPORTER"].iloc[0] if "REPORTER" in df_a.columns else None
        location = df_a["LOCATION"].iloc[0] if "LOCATION" in df_a.columns else None
        try:
            total_cost = df_b2["COST(MYR)"].str.replace(",", "").astype(float).sum()
        except:
            total_cost = 0

        bucket_name = "processed-car"
        final_filename = Path(output_path).name
        with open(output_path, "rb") as f:
            supabase.storage.from_(bucket_name).upload(
                path=final_filename,
                file=f,
                file_options={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
            )
        public_url = supabase.storage.from_(bucket_name).get_public_url(final_filename)

        supabase.table("car_reports").insert({
            "car_id": car_id,
            "description": car_desc,
            "date": car_date,
            "file_name": filename,
            "file_url": public_url,
            "reporter": reporter,
            "location": location,
            "total_cost": total_cost,
            "submitted_at": datetime.utcnow().isoformat()
        }).execute()

        supabase.table("Output_to_merge").insert({
            "source_car_id": car_id,
            "filename": filename,
            "extracted_data": structured_data,
            "file_url": public_url,
            "created_at": datetime.utcnow().isoformat()
        }).execute()

        # === STEP 7: Insert Each Section to Separate Supabase Tables ===
        supabase.table("section_a").delete().eq("car_id", car_id).execute()
        supabase.table("section_b1").delete().eq("car_id", car_id).execute()
        supabase.table("section_b2").delete().eq("car_id", car_id).execute()
        supabase.table("section_c").delete().eq("car_id", car_id).execute()
        supabase.table("section_d").delete().eq("car_id", car_id).execute()
        supabase.table("section_e1").delete().eq("car_id", car_id).execute()
        supabase.table("section_e2").delete().eq("car_id", car_id).execute()

        supabase.table("section_a").insert(df_a.to_dict(orient="records")).execute()
        supabase.table("section_b1").insert(df_b1.to_dict(orient="records")).execute()
        supabase.table("section_b2").insert(df_b2.to_dict(orient="records")).execute()
        supabase.table("section_c").insert(df_c.to_dict(orient="records")).execute()
        supabase.table("section_d").insert(df_d.to_dict(orient="records")).execute()
        supabase.table("section_e1").insert(df_e1.to_dict(orient="records")).execute()
        supabase.table("section_e2").insert(df_e2.to_dict(orient="records")).execute()

        os.remove(file_path)
        os.remove(output_path)
        
# === STEP 8: Insert/Update Master Merged Table ===
supabase.table("merged_car_reports").delete().eq("car_id", car_id).execute()

supabase.table("merged_car_reports").insert({
    "car_id": car_id,
    "description": car_desc,
    "date": car_date,
    "reporter": reporter,
    "location": location,
    "total_cost": total_cost,
    "file_url": public_url,
    "submitted_at": datetime.utcnow().isoformat()
}).execute()

        return jsonify({
            "result": "✅ Excel generated and uploaded.",
            "download_url": public_url
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"❌ Server error: {str(e)}"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
