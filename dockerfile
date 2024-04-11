FROM python:3.10-bullseye

RUN apt update
RUN apt upgrade -y

RUN apt-get install -y nano iputils-ping curl borgbackup cron git

RUN useradd -ms /bin/bash fedow
USER fedow

ENV POETRY_NO_INTERACTION=1

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/home/fedow/.local/bin:$PATH"

# RUN cd /home/fedow && git clone https://github.com/TiBillet/Fedow.git
COPY --chown=fedow:fedow ./ /home/fedow/Fedow
COPY --chown=fedow:fedow ./bashrc /home/fedow/.bashrc
COPY --chown=fedow:fedow ./backup /backup

WORKDIR /home/fedow/Fedow
RUN poetry install

# CMD ["bash", "start.sh"]

# docker build -t tibillet/fedow:alpha1 .
# docker push tibillet/fedow:alpha1
