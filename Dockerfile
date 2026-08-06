FROM python:3.12-slim

RUN apt-get update -y
RUN apt-get install -y libpython3-dev freetds-dev libpq-dev build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.lock /app/requirements.lock
COPY ./app /app
WORKDIR /app
RUN pip3 install Cython 
RUN pip3 install -r requirements.lock

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health


ENTRYPOINT ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]

#ENTRYPOINT ["python3"]
#CMD ["run.py"]
