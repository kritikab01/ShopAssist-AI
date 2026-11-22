# ShopAssist web app (app/server.py): Python standard library + pg8000. Used by docker-compose.yml and Render.
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pg8000==1.31.2
COPY app/ app/
COPY scripts/shopassist_common.py scripts/
ENV APP_HOST=0.0.0.0 PYTHONUNBUFFERED=1
EXPOSE 8501
USER nobody
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8501') + '/api/health')"
CMD ["python", "app/server.py"]
