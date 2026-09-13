FROM python:3.11-slim
WORKDIR /app
COPY app.py /app/app.py
EXPOSE 9081
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9081/healthz').status==200 else 1)"
CMD ["python", "/app/app.py"]
