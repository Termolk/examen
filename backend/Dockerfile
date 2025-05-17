FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаем пользователя и группу приложения
RUN groupadd -r appgroup && useradd -r -g appgroup appuser
RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 5005

# Переменные окружения для Flask будут установлены через docker-compose
# CMD ["flask", "run", "--host=0.0.0.0"] # Команда запускается из docker-compose