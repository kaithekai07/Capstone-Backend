from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import pdfplumber
import pandas as pd
from datetime import datetime
from werkzeug.utils import secure_filename
from supabase import create_client
from google.cloud import storage
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

def upload_section_to_gcs(df, car_id, section_name):
    csv_data = df.to_csv(index=False, header=False)
    client = storage.Client.from_service_account_json("gcp-creds.json")
    bucket = client.bucket("safesightai-car-reports-db")  # Replace with your GCS bucket
    blob_path = f"{section_name}/{car_id}_{section_name}.csv"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(csv_data, content_type="text/csv")
    print(f"✅ Uploaded {section_name} to: gs://{bucket.name}/{blob_path}")
    return f"gs://{bucket.name}/{blob_path}"

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
                    details["CLIENT "] = row[1]
                    details["LOCATION"] = row[4]
                elif row[0] == "Well No.":
                    details["WELL NO."] = row[1]
                    details["PROJECT"] = row[4]
    details["ID NO. SEC A"] = id_sec_a
    return pd.DataFrame([details])

def extract_findings(pdf, id_sec_a, car_no):
    findings = []
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
                        if len(row) > detail_idx:
                            findings.append({
                                "ID NO. SEC A": id_sec_a,
                                "CAR NO.": car_no,
                                "ID NO. SEC B": "1",
                                "DATE": row[date_idx].strip(),
                                "TIME": row[time_idx].strip(),
                                "DETAILS": row[detail_idx].strip()
                            })
    return pd.DataFrame(findings)

def extract_cost_impact(pdf, id_sec_a, car_no):
    cost_rows = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "SECTION B" in text.upper():
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                headers = [cell.strip().upper() if cell else "" for cell in table[0]]
                if "COST IMPACTED BREAKDOWN" in headers and "COST(MYR)" in headers:
                    breakdown_idx = headers.index("COST IMPACTED BREAKDOWN")
                    cost_idx = headers.index("COST(MYR)")
                    for row in table[1:]:
                        if len(row) > cost_idx:
                            cost_rows.append({
                                "ID NO. SEC A": id_sec_a,
                                "CAR NO.": car_no,
                                "ID NO. SEC B": "1",
                                "COST IMPACTED BREAKDOWN ": row[breakdown_idx].strip(),
                                "COST(MYR)": row[cost_idx].strip()
                            })
    return pd.DataFrame(cost_rows)

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

def extract_answers_after_point(text, id_sec_a, car_no):
    normalized_text = re.sub(r'\r\n|\r', '\n', text)
    causal_blocks = re.split(r'(?:Causal Factor|Root Cause Analysis)[#\s]*\d*[:\-]?\s*', normalized_text, flags=re.IGNORECASE)
    titles = re.findall(r'(?:Causal Factor|Root Cause Analysis)[#\s]*\d*[:\-]?\s*(.*)', normalized_text, flags=re.IGNORECASE)

    final_data = []
    for idx, block in enumerate(causal_blocks[1:]):
        why_matches = re.findall(
            r"(WHY\s?-?\s?\d+|Why\s?-?\s?\d+|Why\d+)\s*[:\-–—]?\s*(.*?)(?=(?:WHY\s?-?\s?\d+|Why\s?-?\s?\d+|Why\d+)\s*[:\-–—]?|$)",
            block,
            flags=re.DOTALL | re.IGNORECASE
        )
        for why_raw, answer_raw in why_matches:
            why_text = ' '.join(why_raw.strip().split())
            answer_clean = answer_raw.strip().replace('\n', ' ').replace('•', '').strip()
            bullets = re.findall(r'•\s*(.*?)\s*(?=•|$)', answer_clean)
            if not bullets:
                bullets = [answer_clean]
            for bullet in bullets:
                final_data.append({
                    "ID NO. SEC A": id_sec_a,
                    "CAR NO.": car_no,
                    "ID NO. SEC C": "1",
                    "CAUSAL FACTOR": titles[idx].strip() if idx < len(titles) else f"Factor #{idx+1}",
                    "WHY": why_text,
                    "ANSWER": bullet.strip()
                })
    return pd.DataFrame(final_data)

def extract_corrections(pdf, id_sec_a, car_no):
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

def extract_corrective_action(pdf, id_sec_a, car_no):
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

def extract_conclusion_review(id_sec_a, car_no):
    return pd.DataFrame([{
        "ID NO. SEC A": id_sec_a,
        "CAR NO.": car_no,
        "Accepted": "Yes",
        "Rejected": ""
    }])

def process_pdf_with_pdfplumber(pdf_path, id_sec_a):
    output_path = os.path.join("outputs", f"{id_sec_a}_result.xlsx")
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

    # Upload to GCS
    upload_section_to_gcs(df_a, id_sec_a, "section_a")
    upload_section_to_gcs(df_b1, id_sec_a, "section_b1")
    upload_section_to_gcs(df_b2, id_sec_a, "section_b2")
    upload_section_to_gcs(df_c, id_sec_a, "section_c")
    upload_section_to_gcs(df_d, id_sec_a, "section_d")
    upload_section_to_gcs(df_e1, id_sec_a, "section_e1")
    upload_section_to_gcs(df_e2, id_sec_a, "section_e2")

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

        public_url = f"https://storage.googleapis.com/safesightai-car-reports-db/outputs/{Path(output_path).name}"

        os.remove(file_path)
        os.remove(output_path)

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


