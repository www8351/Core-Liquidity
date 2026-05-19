FROM python:3.11-slim

WORKDIR /app

# התקנת ספריות
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# העתקת הקוד
COPY . .

# הגדרת אזור זמן
ENV TZ=Asia/Jerusalem

CMD ["python", "main.py"]