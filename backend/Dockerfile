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

COPY backend/requirements.txt /requirements.txt

RUN pip install --no-cache-dir --default-timeout=180 --retries=10 -r /requirements.txt

# Bake the cross-encoder weights into the image.
#
# Without this the reranker is fetched from Hugging Face on the FIRST chat request, so a
# reviewer's first question is slow and fails entirely on a machine with no network. It
# also means each gunicorn worker would fetch and hold its own copy. Must match
# `settings.reranker_model`.
ARG RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
ENV HF_HOME=/opt/hf
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('${RERANKER_MODEL}')"

COPY backend ${HOME_DIR}
COPY gold_standard ${HOME_DIR}/gold_standard
COPY pytest.ini ${HOME_DIR}/pytest.ini
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
# Pre-fetched reranker weights, so no model download happens at request time.
COPY --from=build /opt/hf /opt/hf

ENV PYTHONPATH="${PYTHONPATH}:${HOME_DIR}"
ENV PORT=${PORT}
ENV HF_HOME=/opt/hf
# The weights are baked in; never reach out to Hugging Face at runtime.
ENV HF_HUB_OFFLINE=1


WORKDIR ${HOME_DIR}
EXPOSE ${PORT}

CMD ["./startup_unix.sh"]
