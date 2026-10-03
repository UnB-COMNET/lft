# Brief: lft-pydash-client: pydash (github.com/mfcaetano/pydash) as a testbed client, with pydash-play to
# run it against a testbed video server (lft-pydash-server), R2AThroughput in its r2a/, iperf3 and ping.
# Build: docker build -t lft-pydash-client docker/pydash_client
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git iperf3 iproute2 iputils-ping curl \
    && rm -rf /var/lib/apt/lists/*
ARG PYDASH_COMMIT=636a493a9d4d4ba2de00bb6662f0f9edf4082e68
RUN git clone https://github.com/mfcaetano/pydash.git /pydash && git -C /pydash checkout -q $PYDASH_COMMIT \
    && pip install --no-cache-dir -r /pydash/requirements.txt && mkdir -p /pydash/results
COPY r2athroughput.py /pydash/r2a/
COPY pydash-play /usr/local/bin/pydash-play
ENV MPLBACKEND=Agg
CMD ["sleep", "infinity"]
