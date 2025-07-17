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

app = Flask(__name__)
CORS(app, origins=["https://safesightai.vercel.app"], supports_credentials=True)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

SUPABASE_URL = "https://nfcgehfenpjqrijxgzio.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5mY2dlaGZlbnBqcXJpanhnemlvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MDc0Mjk4MSwiZXhwIjoyMDY2MzE4OTgxfQ.B__RkNBjBlRn9QC7L72lL2wZKO7O3Yy2iM-Da1cllpc"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def extract_section_a(tables, id_sec_a):
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

def extract_findings(pdf, id_sec_a):
    findings = []
    b_index = 1
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "SECTION B" in text.upper():
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                headers = [cell.strip().upper() if cell else "" for cell in table[0]]
                if "DATE" in headers and "TIME" in headers and "DETAILS" in headers:
                    date_idx = headers.index("DATE")
                    time_idx = headers.index("TIME")
                    detail_idx = headers.index("DETAILS")
                    for row in table[1:]:
                        findings.append({
                            "ID NO. SEC A": id_sec_a,
                            "ID NO. SEC B": str(b_index),
                            "DATE": row[date_idx].strip() if row[date_idx] else "",
                            "TIME": row[time_idx].strip() if row[time_idx] else "",
                            "DETAILS": row[detail_idx].strip() if row[detail_idx] else ""
                        })
                        b_index += 1
    return pd.DataFrame(findings)

def extract_cost_impact(pdf, id_sec_a):
    cost_rows = []
    b_index = 1
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "SECTION B" in text.upper():
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                headers = [cell.strip().upper() if cell else "" for cell in table[0]]
                if "COST IMPACT BREAKDOWN" in headers and "COST (MYR)" in headers:
                    breakdown_idx = headers.index("COST IMPACT BREAKDOWN")
                    cost_idx = headers.index("COST (MYR)")
                    for row in table[1:]:
                        cost_rows.append({
                            "ID NO. SEC A": id_sec_a,
                            "ID NO. SEC B": str(b_index),
                            "COST IMPACT BREAKDOWN": row[breakdown_idx].strip() if row[breakdown_idx] else "",
                            "COST (MYR)": row[cost_idx].strip() if row[cost_idx] else ""
                        })
                        b_index += 1
    return pd.DataFrame(cost_rows)

def extract_section_c_text(pdf):
    section_c_text = ""
    in_section_c = False
    for page in pdf.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            upper = line.strip().upper()
            if "SECTION C" in upper:
                in_section_c = True
            elif "SECTION D" in upper:
                in_section_c = False
            if in_section_c:
                section_c_text += line + "\\n"
    return section_c_text.strip()

def extract_answers_after_point(text, id_sec_a):
    normalized = re.sub(r'\\r\\n|\\r', '\\n', text)
    blocks = re.split(r'(?:Causal Factor|Root Cause Analysis)[#\\s]*\\d*[:\\-]?\\s*', normalized, flags=re.IGNORECASE)
    titles = re.findall(r'(?:Causal Factor|Root Cause Analysis)[#\\s]*\\d*[:\\-]?\\s*(.*)', normalized, flags=re.IGNORECASE)
    final_data = []
    c_index = 1
    for idx, block in enumerate(blocks[1:]):
        why_matches = re.findall(
            r"(WHY\\s?-?\\s?\\d+|Why\\s?-?\\s?\\d+|Why\\d+)\\s*[:\\-–—]?\\s*(.*?)(?=(?:WHY\\s?-?\\s?\\d+|Why\\s?-?\\s?\\d+|Why\\d+)\\s*[:\\-–—]?|$)",
            block,
            flags=re.DOTALL | re.IGNORECASE
        )
        for why_raw, answer_raw in why_matches:
            why_text = ' '.join(why_raw.strip().split())
            answer_clean = answer_raw.strip().replace('\\n', ' ').replace('•', '').strip()
            bullets = re.findall(r'•\\s*(.*?)\\s*(?=•|$)', answer_clean)
            if not bullets:
                bullets = [answer_clean]
            for bullet in bullets:
                final_data.append({
                    "ID NO. SEC A": id_sec_a,
                    "ID NO. SEC C": str(c_index),
                    "CAUSAL FACTOR": titles[idx].strip() if idx < len(titles) else f"Factor #{idx+1}",
                    "WHY": why_text,
                    "ANSWER": bullet.strip()
                })
                c_index += 1
    return pd.DataFrame(final_data)

def extract_corrections(pdf, id_sec_a):
    corrections = []
    d_index = 1
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "SECTION D" in text.upper():
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                if "Correction Taken" in " ".join([cell or "" for row in table for cell in row]):
                    for row in table[1:]:
                        if len(row) >= 3:
                            corrections.append({
                                "ID NO. SEC A": id_sec_a,
                                "ID NO. SEC D": str(d_index),
                                "CORRECTION TAKEN": row[0],
                                "PIC": row[1],
                                "IMPLEMENTATION DATE": row[2],
                                "CLAUSE CODE": row[3] if len(row) > 3 else ""
                            })
                            d_index += 1
    return pd.DataFrame(corrections)

def extract_corrective_action(pdf, id_sec_a):
    e1_rows = []
    e_index = 1
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "SECTION E" in text.upper():
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                if "Correction Taken" in " ".join([cell or "" for row in table for cell in row]):
                    for row in table[1:]:
                        if len(row) >= 3:
                            e1_rows.append({
                                "ID NO. SEC A": id_sec_a,
                                "ID NO. SEC E": str(e_index),
                                "CORRECTION ACTION": row[0],
                                "PIC": row[1],
                                "IMPLEMENTATION DATE": row[2],
                                "CLAUSE CODE": row[3] if len(row) > 3 else ""
                            })
                            e_index += 1
    return pd.DataFrame(e1_rows)

def extract_conclusion_review(id_sec_a):
    return pd.DataFrame([{
        "ID NO. SEC A": id_sec_a,
        "Accepted": "Yes",
        "Rejected": ""
    }])

def process_pdf_with_pdfplumber(pdf_path, id_sec_a):
    output_path = os.path.join(OUTPUT_FOLDER, f"{id_sec_a}_result.xlsx")
    with pdfplumber.open(pdf_path) as pdf:
        tables = pdf.pages[0].extract_tables()
        df_a = extract_section_a(tables, id_sec_a)
        df_b1 = extract_findings(pdf, id_sec_a)
        df_b2 = extract_cost_impact(pdf, id_sec_a)
        df_c = extract_answers_after_point(extract_section_c_text(pdf), id_sec_a)
        df_d = extract_corrections(pdf, id_sec_a)
        df_e1 = extract_corrective_action(pdf, id_sec_a)
        df_e2 = extract_conclusion_review(id_sec_a)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_a.to_excel(writer, sheet_name="Section A", index=False)
        df_b1.to_excel(writer, sheet_name="Section B1 Chronology", index=False)
        df_b2.to_excel(writer, sheet_name="Section B2 Cost Impacted", index=False)
        df_c.to_excel(writer, sheet_name="Section C 5Why QA", index=False)
        df_d.to_excel(writer, sheet_name="Section D Corrective Taken", index=False)
        df_e1.to_excel(writer, sheet_name="Section E1 Corrective Action", index=False)
        df_e2.to_excel(writer, sheet_name="Section E2 Conclusion", index=False)

    return output_path, {
        "Section_A": df_a.to_dict(orient="records"),
        "Section_B1": df_b1.to_dict(orient="records"),
        "Section_B2": df_b2.to_dict(orient="records"),
        "Section_C": df_c.to_dict(orient="records"),
        "Section_D": df_d.to_dict(orient="records"),
        "Section_E1": df_e1.to_dict(orient="records"),
        "Section_E2": df_e2.to_dict(orient="records")
    }, df_a, df_b2

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        file = request.files.get("file")
        car_id = request.form.get("carId", f"CAR-{datetime.utcnow().timestamp()}")
        car_desc = request.form.get("description", "")
        car_date = request.form.get("date", str(datetime.today().date()))

        if not file:
            return jsonify({"error": "No file uploaded"}), 400

        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)

        output_path, structured_data, df_a, df_b2 = process_pdf_with_pdfplumber(file_path, car_id)
        final_filename = Path(output_path).name
        bucket = "processed-car"

        with open(output_path, "rb") as f:
            supabase.storage.from_(bucket).upload(
                path=final_filename,
                file=f,
                file_options={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
            )

        public_url = supabase.storage.from_(bucket).get_public_url(final_filename)

        reporter = df_a["REPORTER"].iloc[0] if "REPORTER" in df_a.columns else None
        location = df_a["LOCATION"].iloc[0] if "LOCATION" in df_a.columns else None
        try:
            total_cost = df_b2["COST (MYR)"].str.replace(",", "").astype(float).sum()
        except:
            total_cost = 0

        supabase.table("merged_car_reports").insert({
            "car_id": car_id,
            "description": car_desc,
            "date": car_date,
            "reporter": reporter,
            "location": location,
            "submitted_at": datetime.utcnow().isoformat(),
            "file_url": public_url
        }).execute()

        for section in ["section_a", "section_b1", "section_b2", "section_c", "section_d", "section_e1", "section_e2"]:
            supabase.table(section).delete().eq("ID NO. SEC A", car_id).execute()

        def insert_records(table, records):
            for chunk in [records[i:i+1000] for i in range(0, len(records), 1000)]:
                supabase.table(table).insert(chunk).execute()

        insert_records("section_a", structured_data["Section_A"])
        insert_records("section_b1", structured_data["Section_B1"])
        insert_records("section_b2", structured_data["Section_B2"])
        insert_records("section_c", structured_data["Section_C"])
        insert_records("section_d", structured_data["Section_D"])
        insert_records("section_e1", structured_data["Section_E1"])
        insert_records("section_e2", structured_data["Section_E2"])

        os.remove(file_path)
        os.remove(output_path)

        return jsonify({
            "result": "✅ File extracted and uploaded.",
            "download_url": public_url,
            "data": structured_data
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
