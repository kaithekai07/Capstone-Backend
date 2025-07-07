from flask import Flask, request, jsonify, url_for
from flask_cors import CORS
import os
import pdfplumber
import pandas as pd
import re
import traceback
from werkzeug.utils import secure_filename
from datetime import datetime
from supabase import create_client
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

@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return '', 204

    try:
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("Missing Supabase credentials")
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

        file = request.files.get("file")
        car_id = request.form.get("carId", "CAR-UNKNOWN")
        car_date = request.form.get("date", str(datetime.today().date()))
        car_desc = request.form.get("description", "")

        if not file:
            return jsonify({"error": "No file uploaded"}), 400

        filename = secure_filename(file.filename or f"upload_{datetime.now().timestamp()}.pdf")
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

        final_filename = os.path.basename(output_path)
        static_path = os.path.join(STATIC_FOLDER, final_filename)
        shutil.copy(output_path, static_path)

        os.remove(file_path)

        return jsonify({
            "result": "✅ Excel generated successfully.",
            "download_url": url_for('static', filename=final_filename, _external=True)
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"❌ Server error: {str(e)}"}), 500

def process_pdf(pdf_path, car_id, car_date, car_desc):
    output_path = os.path.join(OUTPUT_FOLDER, f"{car_id}_result.xlsx")
    id_sec_a = car_id
    car_no = car_id

    def extract_section_a(tables):
        details = {}
        for table in tables:
            flat = [cell for row in table for cell in row if cell]
            if "CAR No" in flat and "Issue Date" in flat:
                for row in table:
                    row = [cell if cell else "" for cell in row]
                    if row[0] == "CAR No":
                        details["CAR NO."] = row[1]
                        details["ISSUE DATE"] = row[4]
                    elif row[0] == "Reporter":
                        details["REPORTER"] = row[1]
                        details["DEPARTMENT"] = row[4]
                    elif row[0] == "Client":
                        details["CLIENT"] = row[1]
                        details["LOCATION"] = row[4]
                    elif row[0] == "Well No.":
                        details["WELL NO."] = row[1]
                        details["PROJECT"] = row[4]
        details["ID NO. SEC A"] = id_sec_a
        return pd.DataFrame([details])

    def extract_findings(pdf):
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "SECTION B" in text.upper():
                tables = page.extract_tables()
                for table in tables:
                    flat = " ".join([cell or "" for row in table for cell in row])
                    if "Chronology of Findings" in flat:
                        findings = []
                        for row in table[1:]:
                            if len(row) >= 4:
                                findings.append({
                                    "ID NO. SEC A": id_sec_a,
                                    "CAR NO.": car_no,
                                    "ID NO. SEC B": "1",
                                    "DATE": row[1],
                                    "TIME": row[2],
                                    "DETAILS": row[3]
                                })
                        return pd.DataFrame(findings)
        return pd.DataFrame()

    def extract_cost_impact():
        return pd.DataFrame([{
            "ID NO. SEC A": id_sec_a,
            "CAR NO.": car_no,
            "ID NO. SEC B": "1",
            "COST IMPACTED BREAKDOWN ": "Equipment Delay",
            "COST(MYR)": "15000"
        }])

    def extract_section_c_text(pdf):
        section_c_text = ""
        in_section_c = False
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                if "SECTION C" in line.upper():
                    in_section_c = True
                elif "SECTION D" in line.upper():
                    in_section_c = False
                if in_section_c:
                    section_c_text += line + "\n"
        return section_c_text.strip()

    def extract_answers_after_point(text):
        causal_blocks = re.split(r"Causal Factor[#\s]*\d+:\s*", text)[1:]
        titles = re.findall(r"Causal Factor[#\s]*\d+:\s*(.*)", text)
        final_data = []
        for idx, block in enumerate(causal_blocks):
            raw_why_pairs = re.findall(r"(Why\d.*?)\s*[-–]\s*(.*?)(?=Why\d|Causal Factor|$)", block, re.DOTALL)
            for why_text, answer in raw_why_pairs:
                answer = answer.strip().replace('\n', ' ')
                bullet_points = re.findall(r"•\s*(.*?)\s*(?=•|$)", answer)
                if not bullet_points:
                    bullet_points = [answer]
                for ans in bullet_points:
                    final_data.append({
                        "ID NO. SEC A": id_sec_a,
                        "CAR NO.": car_no,
                        "ID NO. SEC C": "1",
                        "CAUSAL FACTOR": titles[idx].strip() if idx < len(titles) else "",
                        "WHY": why_text.strip(),
                        "ANSWER": ans.strip()
                    })
        return pd.DataFrame(final_data)

    def extract_corrections(pdf):
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "SECTION D" in text.upper():
                tables = page.extract_tables()
                for table in tables:
                    flat = " ".join([cell or "" for row in table for cell in row])
                    if "Correction Taken" in flat:
                        return pd.DataFrame([
                            {
                                "ID NO. SEC A": id_sec_a,
                                "CAR NO.": car_no,
                                "ID NO. SEC D": "1",
                                "CORRECTION TAKEN": row[0],
                                "PIC": row[1],
                                "IMPLEMENTATION DATE": row[2],
                                "CLAUSE CODE": row[3] if len(row) > 3 else ""
                            }
                            for row in table[1:] if len(row) >= 4
                        ])
        return pd.DataFrame()

    def extract_corrective_action(pdf):
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "SECTION E" in text.upper():
                tables = page.extract_tables()
                for table in tables:
                    flat = " ".join([cell or "" for row in table for cell in row])
                    if "Corrective Action" in flat:
                        return pd.DataFrame([
                            {
                                "ID NO. SEC A": id_sec_a,
                                "CAR NO.": car_no,
                                "ID NO. SEC E": "1",
                                "CORRECTION ACTION": row[0],
                                "PIC": row[1],
                                "IMPLEMENTATION DATE": row[2]
                            }
                            for row in table[1:] if len(row) >= 3
                        ])
        return pd.DataFrame()

    def extract_conclusion_review():
        return pd.DataFrame([{
            "ID NO. SEC A": id_sec_a,
            "CAR NO.": car_no,
            "Accepted": "Yes",
            "Rejected": ""
        }])

    with pdfplumber.open(pdf_path) as pdf:
        tables = pdf.pages[0].extract_tables()
        df_a = extract_section_a(tables)
        df_b1 = extract_findings(pdf)
        df_b2 = extract_cost_impact()
        df_c2 = extract_answers_after_point(extract_section_c_text(pdf))
        df_d = extract_corrections(pdf)
        df_e1 = extract_corrective_action(pdf)
        df_e2 = extract_conclusion_review()

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_a.to_excel(writer, sheet_name="Section A", index=False)
        df_b1.to_excel(writer, sheet_name="Section B1 Chronology", index=False)
        df_b2.to_excel(writer, sheet_name="Section B2 Cost Impacted", index=False)
        df_c2.to_excel(writer, sheet_name="Section C 5Why QA", index=False)
        df_d.to_excel(writer, sheet_name="Section D Corrective Taken", index=False)
        df_e1.to_excel(writer, sheet_name="Section E1 Corrective Action", index=False)
        df_e2.to_excel(writer, sheet_name="Section E2 Conclusion", index=False)

    return output_path

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

