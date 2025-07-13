FROM python:3.10

RUN apt-get update && apt-get install -y poppler-utils

WORKDIR /app
COPY . .

RUN pip install --upgrade pip setuptools
RUN pip install -r requirements.txt

CMD ["python", "app.py"]
