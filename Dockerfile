FROM python:3.10

# Install system dependencies
RUN apt-get update && apt-get install -y poppler-utils

# Set working directory
WORKDIR /app

# Copy code
COPY . .

# Install Python dependencies
RUN pip install --upgrade pip setuptools
RUN pip install -r requirements.txt

# Start your app
CMD ["python", "app.py"]
