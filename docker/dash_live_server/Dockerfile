# Brief: lft-dash-live: a live DASH stream (ffmpeg, five qualities from 1080p to 240p, encoded in real time)
# served by nginx at http://<ip>/manifest.mpd, plus iperf3 -s. dash-play follows its live edge and picks
# the quality by the throughput that reaches the client. Encoding takes about 60% of a core.
# Build: docker build -t lft-dash-live docker/dash_live_server
FROM nginx:alpine
# bash: the LFT runs its discovery ping through bash -lc
RUN apk add --no-cache bash ffmpeg font-dejavu iperf3 iproute2
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY live.sh /live.sh
CMD ["sh", "/live.sh"]
