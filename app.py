import os
import pdfplumber
import pandas as pd
from pathlib import Path

def process_pdf_with_pdfplumber(pdf_path, car_id):
    output_path = os.path.join("outputs", f"{car_id}_result.xlsx")

    section_a, chronology, section_b2, section_c, section_d, section_e1, section_e2 = [], [], [], [], [], [], []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            tables = page.extract_tables()

            for line in text.splitlines():
                if "CAR No" in line:
                    section_a.append({"CAR NO.": line.split("CAR No")[-1].strip(), "ID NO. SEC A": car_id})
                elif "Chronology" in line or "Finding" in line:
                    chronology.append({
                        "ID NO. SEC A": car_id,
                        "CAR NO.": car_id,
                        "ID NO. SEC B": f"{car_id}-B1-{i+1}",
                        "DETAILS": line.strip()
                    })
                elif "Cost Impact" in line or "MYR" in line:
                    section_b2.append({
                        "ID NO. SEC A": car_id,
                        "CAR NO.": car_id,
                        "ID NO. SEC B": "1",
                        "COST IMPACTED BREAKDOWN ": "Detected in text",
                        "COST(MYR)": "TBA"
                    })
                elif "Causal Factor" in line or "Why" in line:
                    section_c.append({
                        "ID NO. SEC A": car_id,
                        "CAR NO.": car_id,
                        "ID NO. SEC C": "1",
                        "CAUSAL FACTOR": "Detected in text",
                        "WHY": line,
                        "ANSWER": ""
                    })
                elif "Correction Taken" in line:
                    section_d.append({
                        "ID NO. SEC A": car_id,
                        "CAR NO.": car_id,
                        "ID NO. SEC D": "1",
                        "CORRECTION TAKEN": line,
                        "PIC": "",
                        "IMPLEMENTATION DATE": "",
                        "CLAUSE CODE": ""
                    })
                elif "Corrective Action" in line:
                    section_e1.append({
                        "ID NO. SEC A": car_id,
                        "CAR NO.": car_id,
                        "ID NO. SEC E": "1",
                        "CORRECTION ACTION": line,
                        "PIC": "",
                        "IMPLEMENTATION DATE": ""
                    })
                elif "Accepted" in line:
                    section_e2.append({
                        "ID NO. SEC A": car_id,
                        "CAR NO.": car_id,
                        "Accepted": "Yes" if "X" in line else "",
                        "Rejected": "Yes" if "Rejected" in line and "X" in line else ""
                    })

    if not section_a:
        section_a.append({"CAR NO.": car_id, "ID NO. SEC A": car_id})
    if not section_e2:
        section_e2.append({"ID NO. SEC A": car_id, "CAR NO.": car_id, "Accepted": "", "Rejected": ""})

    df_a = pd.DataFrame(section_a)
    df_b1 = pd.DataFrame(chronology)
    df_b2 = pd.DataFrame(section_b2)
    df_c = pd.DataFrame(section_c)
    df_d = pd.DataFrame(section_d)
    df_e1 = pd.DataFrame(section_e1)
    df_e2 = pd.DataFrame(section_e2)

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

    return output_path, structured_data

# Run on uploaded sample
uploaded_pdf = "/mnt/data/CAR-WRL-2024-05-DLC-04S-Power Pack 102232 Water Pump Malfunction_QHSE Reviewed (1).pdf"
process_pdf_with_pdfplumber(uploaded_pdf, "CAR-WRL-2024-05-DLC-04S")
