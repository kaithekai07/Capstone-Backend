FROM python:3.9

# Install OS dependencies
RUN apt-get update && apt-get install -y poppler-utils

# Set working directory
WORKDIR /app

# Copy source code
COPY . .

# Install required packages
RUN pip install --upgrade pip setuptools
RUN pip install -r requirements.txt

# Run the app
CMD ["python", "app.py"]
