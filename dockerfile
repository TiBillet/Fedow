FROM python:3.10-bullseye

RUN apt update
RUN apt upgrade -y

RUN mkdir -p /usr/share/man/man1
RUN mkdir -p /usr/share/man/man7
RUN apt-get install -y --no-install-recommends postgresql-client

RUN apt-get install -y nano iputils-ping curl borgbackup cron

RUN useradd -ms /bin/bash fedow
USER fedow

ENV \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/home/fedow/.local/bin:$PATH"
