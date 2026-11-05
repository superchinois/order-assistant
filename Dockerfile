FROM python:3.12-slim

# Keep update + install in the SAME layer: if they are split, Docker reuses the
# cached "update" layer and apt ends up with a stale index -> "Unable to locate package".
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpython3-dev freetds-dev libpq-dev build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.lock /app/requirements.lock

WORKDIR /app

RUN pip3 install Cython 
RUN pip3 install -r requirements.lock

COPY ./app /app

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health


ENTRYPOINT ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]

#ENTRYPOINT ["python3"]
#CMD ["run.py"]
