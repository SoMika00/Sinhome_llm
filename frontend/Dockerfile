FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ./src /app/src
CMD ["streamlit", "run", "src/chatbot_ui/app.py"]
