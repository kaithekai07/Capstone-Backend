FROM python:3.10

# Required for pdfplumber (uses poppler under the hood for PDF parsing)
RUN apt-get update && apt-get install -y poppler-utils

# Optional cleanup to keep image small
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN pip install --upgrade pip setuptools
RUN pip install -r requirements.txt

CMD ["python", "app.py"]
