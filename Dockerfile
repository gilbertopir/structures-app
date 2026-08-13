# Match the local development Python version
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# No system build dependencies needed: Pillow ships aarch64 wheels and
# nothing here uses GEOS or PROJ. Keeps the image small and the build
# on the Pi down from minutes to seconds.

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Directories that are bind-mounted at runtime, created here so the
# paths exist even on a first run before the volumes are populated.
RUN mkdir -p data media staticfiles

# collectstatic imports settings, which requires SECRET_KEY. ARG (not
# ENV) means this placeholder exists only during the build and never
# leaks into the running container, where the real .env is used.
ARG SECRET_KEY=build-time-placeholder-not-used-at-runtime
RUN python manage.py collectstatic --noinput

EXPOSE 8002

CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]
