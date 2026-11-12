# The portal behind a reverse proxy. One worker only: runs are threads inside the web process (README, Hosting).
FROM python:3.14.6-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0 \
 && useradd --create-home portal && mkdir instance && chown portal instance
COPY evalportal evalportal
COPY scripts scripts
USER portal
ENV PORTAL_HTTPS=1
EXPOSE 15500
CMD ["gunicorn", "--workers", "1", "--threads", "8", "--bind", "0.0.0.0:15500", "evalportal:create_app()"]
