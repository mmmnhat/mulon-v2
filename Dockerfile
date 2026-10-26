FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mulon/ mulon/
COPY dossier/ dossier/
COPY config/ config/

CMD ["python", "-m", "mulon.main"]
