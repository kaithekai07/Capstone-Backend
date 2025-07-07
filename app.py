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

        # Section A
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
                    details["CLIENT "] = row[1]
                    details["LOCATION"] = row[4]
                elif row[0] == "Well No.":
                    details["WELL NO."] = row[1]
                    details["PROJECT"] = row[4]
    details["ID NO. SEC A"] = id_sec_a
    return pd.DataFrame([details])

# Section B1
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

# Section B2
def extract_cost_impact():
    return pd.DataFrame([{
        "ID NO. SEC A": id_sec_a,
        "CAR NO.": car_no,
        "ID NO. SEC B": "1",
        "COST IMPACTED BREAKDOWN ": "Equipment Delay",
        "COST(MYR)": "15000"
    }])

# Section C
def extract_section_c_text(pdf):
    section_c_text = ""
    in_section_c = False
    for page in pdf.pages:
        text = page.extract_text() or ""
        lines = text.splitlines()
        for line in lines:
            upper_line = line.strip().upper()
            if "SECTION C" in upper_line:
                in_section_c = True
            elif "SECTION D" in upper_line:
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

# Section D (structured like Section B1)
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

# Section E1 (structured like Section B1)
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

# Section E2
def extract_conclusion_review():
    return pd.DataFrame([{
        "ID NO. SEC A": id_sec_a,
        "CAR NO.": car_no,
        "Accepted": "Yes",
        "Rejected": ""
    }])

# Run extraction
with pdfplumber.open(pdf_path) as pdf:
    all_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    tables = pdf.pages[0].extract_tables()
    df_a = extract_section_a(tables)
    df_b1 = extract_findings(pdf)
    df_b2 = extract_cost_impact()
    section_c_text = extract_section_c_text(pdf)
    df_c2 = extract_answers_after_point(section_c_text)
    df_d = extract_corrections(pdf)
    df_e1 = extract_corrective_action(pdf)
    df_e2 = extract_conclusion_review()

# Export to Excel
with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
    df_a.to_excel(writer, sheet_name="Section A", index=False)
    df_b1.to_excel(writer, sheet_name="Section B1  Chronology Findings", index=False)
    df_b2.to_excel(writer, sheet_name="Section B2 Cost Impacted", index=False)
    df_c2.to_excel(writer, sheet_name="Section C 5Why QA", index=False)
    df_d.to_excel(writer, sheet_name="Section D Corrective Taken", index=False)
    df_e1.to_excel(writer, sheet_name="Section E1 Corrective Action Ta", index=False)
    df_e2.to_excel(writer, sheet_name="SECTION E2 Conclusion and Revie", index=False)

tools.display_dataframe_to_user(name="Section A to E2 Extracted", dataframe=df_a)
output_path
