FROM python:3.10

# System packages for pdf2image
RUN apt-get update && apt-get install -y poppler-utils

WORKDIR /app
COPY . .

RUN pip install --upgrade pip setuptools
RUN pip install -r requirements.txt

CMD ["python", "app.py"]
