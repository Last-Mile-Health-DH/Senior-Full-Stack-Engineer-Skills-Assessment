FROM python:3.12-slim-bullseye AS build


ARG NAME=LMH
ARG HOME_DIR=/usr/src/${NAME}

RUN apt-get update && apt-get install -y --no-install-recommends \
    dos2unix \
    ffmpeg \
    gcc \
    git \
    libpq-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -ms /bin/bash -d ${HOME_DIR} container_user \
    && mkdir -p ${HOME_DIR} /tmp/prometheus \
    && chown -R container_user: ${HOME_DIR} /tmp/prometheus

COPY requirements.txt /requirements.txt

RUN --mount=type=cache,target=/root/.cache/pip pip install --no-cache-dir -r /requirements.txt

COPY . ${HOME_DIR}
RUN find ${HOME_DIR} -type f -print0 | xargs -0 dos2unix
RUN chmod +x ${HOME_DIR}/startup.sh
RUN chmod +x ${HOME_DIR}/startup_unix.sh

FROM python:3.12-slim-bullseye

ARG NAME=LMH
ARG PORT=6100
ARG HOME_DIR=/usr/src/${NAME}

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libpq5 \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build ${HOME_DIR} ${HOME_DIR}
COPY --from=build /tmp/prometheus /tmp/prometheus

ENV PYTHONPATH="${PYTHONPATH}:${HOME_DIR}"
ENV PORT=${PORT}


WORKDIR ${HOME_DIR}
EXPOSE ${PORT}

CMD ["./startup_unix.sh"]
