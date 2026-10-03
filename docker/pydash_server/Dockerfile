# Brief: lft-pydash-server: nginx serving six qualities of Big Buck Bunny (360p to 1080p, 1 s segments,
# 596 s) from the DASH Dataset 2014, under a manifest listing only those, plus iperf3 -s. pydash plays
# http://<ip>/1sec/manifest.mpd, dash-play http://<ip>/manifest.mpd. The segments (~720 MB) are fetched
# from DATASET at build time.
# Build: docker build -t lft-pydash-server docker/pydash_server
FROM alpine:3.20 AS fetch
RUN apk add --no-cache curl
ARG DATASET=http://45.171.101.167/DASHDataset2014/BigBuckBunny/1sec
COPY fetch.sh /fetch.sh
RUN sh /fetch.sh "$DATASET"

FROM nginx:alpine
# bash: the LFT runs its discovery ping through bash -lc
RUN apk add --no-cache bash iperf3 iproute2
COPY --from=fetch /video /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
CMD ["sh", "-c", "iperf3 -s -D && exec nginx -g 'daemon off;'"]
