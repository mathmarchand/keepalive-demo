FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 8080
# The CMD will be overridden in the Helm Chart deployment to run as worker or web
CMD ["python", "app.py"]
