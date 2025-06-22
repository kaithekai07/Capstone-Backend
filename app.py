from flask import Flask, request, jsonify, render_template
import os
import pdfplumber
import pandas as pd
import re
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)

# Folder setup
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
STATIC_FOLDER = "static"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(STATIC_FOLDER, exist_ok=True)

@app.route("/")
def index():
    return render_template("upload.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        file = request.files.get("file")
        car_id = request.form.get("carId", "CAR-UNKNOWN")
        car_date = request.form.get("date", "2024-01-01")
        car_desc = request.form.get("description", "")

        if not file:
            return jsonify({"error": "No file uploaded"}), 400

        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)

        # Process PDF
        output_path = process_pdf(file_path, car_id, car_date, car_desc)

        # Move output to static for downloading
        final_filename = f"{car_id}_output.xlsx"
        static_path = os.path.join(STATIC_FOLDER, final_filename)
        os.replace(output_path, static_path)

        return jsonify({
            "result": "✅ Excel generated successfully.",
            "download_url": f"/static/{final_filename}"
        })

    except Exception as e:
        print("Server Error:", e)
        return jsonify({"error": f"❌ Server error: {str(e)}"}), 500

def process_pdf(pdf_path, car_id, car_date, car_desc):
    id_sec_a = "300525-0001"
    output_path = os.path.join(OUTPUT_FOLDER, f"{car_id}_result.xlsx")

    with pdfplumber.open(pdf_path) as pdf:
        tables = pdf.pages[0].extract_tables()

        def extract_section_a():
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

        def extract_findings():
            for page in pdf.pages:
                text = page.extract_text() or ""
                if "SECTION B" in text.upper():
                    tables = page.extract_tables()
                    for table in tables:
                        if "Chronology of Findings" in " ".join([cell or "" for row in table for cell in row]):
                            return pd.DataFrame([
                                {
                                    "ID NO. SEC A": id_sec_a,
                                    "CAR NO.": car_id,
                                    "ID NO. SEC B": "1",
                                    "DATE": row[1],
                                    "TIME": row[2],
                                    "DETAILS": row[3]
                                }
                                for row in table[1:] if len(row) >= 4
                            ])
            return pd.DataFrame()

        def extract_cost_impact():
            return pd.DataFrame([{
                "ID NO. SEC A": id_sec_a,
                "CAR NO.": car_id,
                "ID NO. SEC B": "1",
                "COST IMPACTED BREAKDOWN ": "Equipment Delay",
                "COST(MYR)": "15000"
            }])

        def extract_section_c_text():
            section_c_text = ""
            in_section = False
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.splitlines():
                    if "SECTION C" in line.upper():
                        in_section = True
                    elif "SECTION D" in line.upper():
                        in_section = False
                    if in_section:
                        section_c_text += line + "\n"
            return section_c_text.strip()

        def extract_why_answers(text):
            blocks = re.split(r"Causal Factor[#\s]*\d+:\s*", text)[1:]
            titles = re.findall(r"Causal Factor[#\s]*\d+:\s*(.*)", text)
            results = []
            for i, block in enumerate(blocks):
                pairs = re.findall(r"(Why\d.*?)\s*[-–]\s*(.*?)(?=Why\d|Causal Factor|$)", block, re.DOTALL)
                for why, answer in pairs:
                    bullets = re.findall(r"•\s*(.*?)\s*(?=•|$)", answer) or [answer.strip()]
                    for b in bullets:
                        results.append({
                            "ID NO. SEC A": id_sec_a,
                            "CAR NO.": car_id,
                            "ID NO. SEC C": "1",
                            "CAUSAL FACTOR": titles[i].strip() if i < len(titles) else "",
                            "WHY": why.strip(),
                            "ANSWER": b.strip()
                        })
            return pd.DataFrame(results)

        def extract_corrections():
            for page in pdf.pages:
                if "Section D" in (page.extract_text() or ""):
                    for table in page.extract_tables():
                        return pd.DataFrame([
                            {
                                "ID NO. SEC A": id_sec_a,
                                "CAR NO.": car_id,
                                "ID NO. SEC D": "1",
                                "CORRECTION TAKEN": row[0],
                                "PIC": row[1],
                                "IMPLEMENTATION DATE": row[2],
                                "CLAUSE CODE": row[3]
                            }
                            for row in table[1:] if len(row) >= 4
