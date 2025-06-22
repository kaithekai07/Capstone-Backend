from flask import Flask, request, jsonify, render_template
import os
import pdfplumber
import pandas as pd
import re

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

@app.route("/")
def index():
    return render_template("upload.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    file = request.files.get("file")
    car_id = request.form.get("carId", "CAR-UNKNOWN")
    car_date = request.form.get("date", "2024-01-01")
    car_desc = request.form.get("description", "")

    if not file:
        return jsonify({"error": "No PDF uploaded"}), 400

    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    try:
        result_path = process_pdf(filepath, car_id, car_date, car_desc)
        return jsonify({"result": f"Success! Extracted to: {result_path}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def process_pdf(pdf_path, car_no, car_date, car_desc):
    id_sec_a = "300525-0001"
    output_excel = os.path.join(OUTPUT_FOLDER, f"{car_no}_result.xlsx")

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

        def extract_section_c_text():
            section_c_text = ""
            in_section_c = False
            for page in pdf.pages:
                text = page.extract_text() or ""
                lines = text.splitlines()
                for line in lines:
                    upper = line.strip().upper()
                    if "SECTION C" in upper:
                        in_section_c = True
                    elif "SECTION D" in upper:
                        in_section_c = False
                    if in_section_c:
                        section_c_text += line + "\n"
            return section_c_text.strip()

        def extract_why_answers(text):
            causal_blocks = re.split(r"Causal Factor[#\s]*\d+:\s*", text)[1:]
            titles = re.findall(r"Causal Factor[#\s]*\d+:\s*(.*)", text)
            data = []
            for idx, block in enumerate(causal_blocks):
                why_blocks = re.findall(r"(Why\d.*?)\s*[-–]\s*(.*?)(?=Why\d|Causal Factor|$)", block, re.DOTALL)
                for why_text, answer in why_blocks:
                    answer = answer.strip().replace('\n', ' ')
                    bullets = re.findall(r"•\s*(.*?)\s*(?=•|$)", answer) or [answer]
                    for b in bullets:
                        data.append({
                            "ID NO. SEC A": id_sec_a,
                            "CAR NO.": car_no,
                            "ID NO. SEC C": "1",
                            "CAUSAL FACTOR": titles[idx].strip() if idx < len(titles) else "",
                            "WHY": why_text.strip(),
                            "ANSWER": b.strip()
                        })
            return pd.DataFrame(data)

        def extract_corrections():
            corrections = []
            for page in pdf.pages:
                if "Section D" in (page.extract_text() or ""):
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table[1:]:
                            if len(row) >= 4:
                                corrections.append({
                                    "ID NO. SEC A": id_sec_a,
                                    "CAR NO.": car_no,
                                    "ID NO. SEC D": "1",
                                    "CORRECTION TAKEN": row[0],
                                    "PIC": row[1],
                                    "IMPLEMENTATION DATE": row[2],
                                    "CLAUSE CODE": row[3]
                                })
            return pd.DataFrame(corrections)

        def extract_corrective_action():
            return pd.DataFrame([{
                "ID NO. SEC A": id_sec_a,
                "CAR NO.": car_no,
                "ID NO. SEC E": "1",
                "CORRECTION ACTION": car_desc,
                "PIC": "Safety Officer",
                "IMPLEMENTATION DATE": car_date
            }])

        def extract_conclusion_review():
            return pd.DataFrame([{
                "ID NO. SEC A": id_sec_a,
                "CAR NO.": car_no,
                "Accepted": "Yes",
                "Rejected": ""
            }])

        # Run all
        df_a = extract_section_a()
        df_b1 = extract_findings()
        df_b2 = extract_cost_impact()
        df_c2 = extract_why_answers(extract_section_c_text())
        df_d = extract_corrections()
        df_e1 = extract_corrective_action()
        df_e2 = extract_conclusion_review()

    with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
        df_a.to_excel(writer, sheet_name="Section A", index=False)
        df_b1.to_excel(writer, sheet_name="Section B1  Chronology Findings", index=False)
        df_b2.to_excel(writer, sheet_name="Section B2 Cost Impacted", index=False)
        df_c2.to_excel(writer, sheet_name="Section C 5Why QA", index=False)
        df_d.to_excel(writer, sheet_name="Section D Corrective Taken", index=False)
        df_e1.to_excel(writer, sheet_name="Section E1 Corrective Action Ta", index=False)
        df_e2.to_excel(writer, sheet_name="SECTION E2 Conclusion and Revie", index=False)

    return output_excel

if __name__ == "__main__":
    app.run(debug=True)
