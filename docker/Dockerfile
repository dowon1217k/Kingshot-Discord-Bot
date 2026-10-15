FROM python:3.12.12-slim-bookworm
LABEL maintainer="yolo <justinyolo33@gmail.com>"
LABEL org.opencontainers.image.source=https://github.com/kingshot-project/Kingshot-Discord-Bot

COPY docker/bootstrap.sh /bootstrap.sh

RUN set -x
RUN apt-get update && apt-get install --no-install-recommends -y curl ca-certificates unzip
RUN pip install --upgrade pip
RUN mkdir -p /app
# Build this customized checkout, never the upstream latest release.
COPY . /app/
RUN cd /app && pip install -r requirements.txt
RUN chmod +x /bootstrap.sh
RUN apt-get -y autoremove && apt-get -y autoclean && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

WORKDIR /app
ENTRYPOINT ["/bin/sh", "/bootstrap.sh"]