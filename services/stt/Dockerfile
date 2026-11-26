# Voz a texto propio (spec 012): Parakeet y Whisper en CPU.
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
# Los modelos se bajan al primer arranque a /models, un volumen de Docker.
RUN useradd --system --create-home stt && mkdir /models && chown stt /models
ENV HF_HOME=/models PYTHONUNBUFFERED=1
USER stt
EXPOSE 8090
CMD ["python", "server.py"]
