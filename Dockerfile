# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

#Install Python dependencie
RUN pip install --no-cache-dir \
    flask \
    pdfplumber \
    click \
    python-dotenv \
    streamlit \
    pandas

#Copy all project files
COPY . .

#DB and chunks stored here) 
RUN mkdir -p data outputs

# Flask API  → 8000
# Streamlit  → 8501
EXPOSE 8000 8501

CMD ["sh", "-c", "python cli.py index && python -m app.main"]
