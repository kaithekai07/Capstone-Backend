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

# === Flask App with CORS ===
app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app, resources={r"/*": {"origins": "https://safesightai.vercel.app"}})

# === Supabase ===
SUPABASE_URL = "https://nfcgehfenpjqrijxgzio.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5mY2dlaGZlbnBqcXJpanhnemlvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MDc0Mjk4MSwiZXhwIjoyMDY2MzE4OTgxfQ.B__RkNBjBlRn9QC7L72lL2wZKO7O3Yy2iM-Da1cllpc"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
STATIC_FOLDER = "static"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

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

        final_filename = f"{car_id}_output.xlsx"
        static_path = os.path.join(STATIC_FOLDER, final_filename)
        os.replace(output_path, static_path)
        os.remove(file_path)

        return jsonify({
            "result": "✅ Excel generated successfully.",
            "download_url": url_for('static', filename=final_filename)
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"❌ Server error: {str(e)}"}), 500

def process_pdf(pdf_path, car_id, car_date, car_desc):
    output_path = os.path.join(OUTPUT_FOLDER, f"{car_id}_result.xlsx")

    with pdfplumber.open(pdf_path) as pdf:
        text_by_page = [page.extract_text() or "" for page in pdf.pages]
        tables_by_page = [page.extract_tables() for page in pdf.pages]

        def extract_section(pattern, text_pages):
            content = []
            in_section = False
            for text in text_pages:
                for line in text.splitlines():
                    if re.search(fr"SECTION {pattern}", line, re.IGNORECASE):
                        in_section = True
                    elif re.search(r"SECTION [A-E]", line, re.IGNORECASE):
                        if in_section:
                            return "\n".join(content).strip()
                        in_section = False
                    if in_section:
                        content.append(line)
            return "\n".join(content).strip()

        def default_df(columns, values):
            return pd.DataFrame([{col: val for col, val in zip(columns, values)}])

        df_a = default_df(["CAR NO.", "ISSUE DATE", "ID NO. SEC A"], [car_id, car_date, car_id])
        df_b1 = default_df(["DETAILS", "DATE", "TIME", "ID NO. SEC A", "CAR NO."], [car_desc, car_date, "00:00", car_id, car_id])
        df_b2 = default_df(["COST IMPACTED BREAKDOWN", "COST(MYR)", "ID NO. SEC A", "CAR NO."], ["Equipment", "15000", car_id, car_id])
        section_c_text = extract_section("C", text_by_page)
        df_c2 = default_df(["WHY", "ANSWER", "ID NO. SEC A", "CAR NO."], ["Why1", section_c_text[:100], car_id, car_id])
        df_d = default_df(["CORRECTION TAKEN", "PIC", "IMPLEMENTATION DATE", "CLAUSE CODE", "ID NO. SEC A", "CAR NO."],
                          ["None", "Unknown", car_date, "-", car_id, car_id])
        df_e1 = default_df(["CORRECTION ACTION", "PIC", "IMPLEMENTATION DATE", "ID NO. SEC A", "CAR NO."],
                           [car_desc, "Safety Officer", car_date, car_id, car_id])
        df_e2 = default_df(["Accepted", "Rejected", "ID NO. SEC A", "CAR NO."],
                           ["Yes", "", car_id, car_id])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_a.to_excel(writer, sheet_name="Section A", index=False)
        df_b1.to_excel(writer, sheet_name="Section B1", index=False)
        df_b2.to_excel(writer, sheet_name="Section B2", index=False)
        df_c2.to_excel(writer, sheet_name="Section C", index=False)
        df_d.to_excel(writer, sheet_name="Section D", index=False)
        df_e1.to_excel(writer, sheet_name="Section E1", index=False)
        df_e2.to_excel(writer, sheet_name="Section E2", index=False)

    return output_path

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
