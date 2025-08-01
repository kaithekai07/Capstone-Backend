from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import pdfplumber
import pandas as pd
import numpy as np
import re
import json
import traceback
from datetime import datetime
from werkzeug.utils import secure_filename
from pathlib import Path
from supabase import create_client
from sentence_transformers import SentenceTransformer, util
from collections import Counter
from rapidfuzz import fuzz



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

# === ✅ NEW SECTION C (IMPROVED) ===
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
    c_index = 1
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
        df_c = extract_answers_after_point(extract_section_c_text(pdf), id_sec_a, df_a["CAR NO."].iloc[0])
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


def normalize_keys(record):
    return {
        k.lower().replace(" ", "_").replace(".", "").replace("-", "").replace("__", "_"): v
        for k, v in record.items()
    }

def clause_mapping(car_id, data):
    clause_ref = pd.read_excel("ISO45001_Master_Data_Refined_Final_Clause8.xlsx")
    clause_ref["Clause Number"] = clause_ref["Clause Number"].astype(str)
    clause_ref.dropna(subset=["Clause Detail"], inplace=True)
    clause_descriptions = dict(zip(clause_ref["Clause Number"], clause_ref["Clause Detail"]))
    clause_ids, clause_texts = zip(*clause_descriptions.items())
    model = SentenceTransformer("all-mpnet-base-v2")
    clause_embeddings = model.encode(list(clause_texts), convert_to_tensor=True)

    def classify_clause_with_similarity(text):
        scores = Counter()
        text = str(text).lower()
        query_emb = model.encode(text, convert_to_tensor=True)
        cos_scores = util.pytorch_cos_sim(query_emb, clause_embeddings)[0].cpu().numpy()
        scores.update({cid: score for cid, score in zip(clause_ids, cos_scores)})

        for pattern, clause_list in [
            (r"\bpump|valve|equipment|maintenance|checklist\b", ["8.1.2"]),
            (r"\bcommunication|handover|supervisor|team\b", ["8.1.4"]),
            (r"\bsuction|operation|not operating|status|protocol\b", ["8.1.1"]),
            (r"\bsit\b", ["8.1.3"]),
        ]:
            if re.search(pattern, text):
                scores.update({c: 0.1 for c in clause_list})

        for cid, desc in clause_descriptions.items():
            fuzz_score = fuzz.token_sort_ratio(text, desc)
            if fuzz_score >= 70:
                scores[cid] += fuzz_score / 100 * 0.5

        if not scores:
            return "8.1.1", 0.0, 100.0

        top_clause = max(scores.items(), key=lambda x: x[1])[0]
        top_clause_text = clause_descriptions[top_clause]
        top_emb = model.encode(top_clause_text, convert_to_tensor=True)
        cosine_sim = float(util.pytorch_cos_sim(query_emb, top_emb)[0][0]) * 100
        euclidean_dist = float(np.linalg.norm(query_emb.cpu().numpy() - top_emb.cpu().numpy()))
        return top_clause, round(cosine_sim, 2), round(euclidean_dist * 100 / np.sqrt(len(query_emb)), 2)

    # If Section_C is not present or has no answers
    if "Section_C" not in data:
        return {"error": "No Section_C data found."}

    df_section_c = pd.DataFrame(data["Section_C"])
    if "ANSWER" not in df_section_c.columns:
        return {"error": "Missing 'ANSWER' column in Section_C"}

    df_section_c = df_section_c[df_section_c["ANSWER"].notna()].copy()

    # 🔁 Add clause mapping columns directly into Section_C
    df_section_c["clause_mapped"], df_section_c["cosine_similarity_%"], df_section_c["euclidean_distance_%"] = zip(
        *df_section_c["ANSWER"].apply(classify_clause_with_similarity)
    )

    # 🧠 Update the data dict so submit_car will push this to car_reports.section_c
    data["Section_C"] = df_section_c.to_dict(orient="records")

    return {"mapped": len(df_section_c)}


@app.route("/submit-car", methods=["POST"])
def submit_car():
    try:
        content = request.get_json()
        car_id = content.get("car_id")
        all_data = content.get("data")

        print(f"✅ Final reviewed data received for: {car_id}")

        update_payload = {"submitted": True}

        for section_key in [
            "Section_A",
            "Section_B1",
            "Section_B2",
            "Section_C",
            "Section_D",
            "Section_E1",
            "Section_E2"
        ]:
            records = all_data.get(section_key, [])
            if not records:
                print(f"⚠️ Skipping {section_key} — no records")
                continue

            cleaned = []
            for r in records:
                record_cleaned = {k: (None if pd.isna(v) else v) for k, v in r.items()}
                cleaned.append(normalize_keys(record_cleaned))

            section_key_normalized = section_key.lower()
            update_payload[section_key_normalized] = cleaned
            print(f"📦 Prepared JSONB payload for {section_key_normalized} with {len(cleaned)} records")

        # ✅ Check if the car_id exists before updating
        existing = supabase.table("car_reports").select("car_id").eq("car_id", car_id).execute()
        if not existing.data:
            supabase.table("car_reports").insert({"car_id": car_id}).execute()

        # ✅ Now update the row
        supabase.table("car_reports").update(update_payload).eq("car_id", car_id).execute()

        # Run clause mapping (adds to Section_C inside update_payload already)
        result = clause_mapping(car_id, all_data)
        # ✅ OPTIONAL: Push clause-mapped results into a flat analytics table
               # ✅ OPTIONAL: Push clause-mapped results into a flat analytics table
        try:
            section_c_records = all_data.get("Section_C", [])
            section_a = all_data.get("Section_A", [{}])[0]
            enriched_records = []

            for record in section_c_records:
                enriched_records.append({
                    "car_id": car_id,
                    "car_no": record.get("CAR NO."),
                    "client": section_a.get("CLIENT"),
                    "location": section_a.get("LOCATION"),
                    "id_no_sec_c": record.get("ID NO. SEC C"),
                    "causal_factor": record.get("CAUSAL FACTOR"),
                    "why": record.get("WHY"),
                    "answer": record.get("ANSWER"),
                    "clause_mapped": record.get("clause_mapped"),
                    "cosine_similarity_%": record.get("cosine_similarity_%"),
                    "euclidean_distance_%": record.get("euclidean_distance_%")
                })

            if enriched_records:
                supabase.table("clause_mapped_issues").insert(enriched_records).execute()
                print(f"📤 Inserted {len(enriched_records)} mapped issues into clause_mapped_issues")
        except Exception as insert_err:
            print(f"⚠️ Failed to insert into clause_mapped_table: {insert_err}")

        return jsonify({"status": "✅ Final processing complete!", "result": result})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/")
def health():
    return jsonify({"status": "✅ Backend is live"}), 200


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        files = request.files.getlist("file")
        results = []

        if not files:
            return jsonify({"error": "No files uploaded"}), 400

        for file in files:
            car_id = request.form.get("carId") or f"CAR_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)

            output_path, extracted_data, df_a, df_b2 = process_pdf_with_pdfplumber(filepath, car_id)

            json_path = os.path.join(OUTPUT_FOLDER, f"{car_id}_result.json")
            with open(json_path, "w") as f:
                json.dump(extracted_data, f)

            results.append({
                "car_id": car_id,
                "filename": filename,
                "data": extracted_data
            })

        return jsonify({"status": "success", "results": results})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500



@app.route("/submit-car-status/<car_id>")
def submit_car_status(car_id):
    try:
        result = supabase.table("car_reports").select("submitted").eq("car_id", car_id).execute()
        if result.data:
            return jsonify({"submitted": result.data[0]["submitted"]})
        else:
            return jsonify({"submitted": False}), 404
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))  # 🔧 Use the correct Render port
    app.run(host="0.0.0.0", port=port)
