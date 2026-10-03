# Brief: lft-dash-client: a testbed client that plays the lft-dash-video ladder (dash-play, one JSON line
# per segment), runs neubot's dash-client against neubot/dash servers, and has iperf3 and ping.
# Build: docker build -t lft-dash-client docker/dash_video_client
FROM neubot/dash-client:latest AS neubot

FROM alpine:3.20
RUN apk add --no-cache python3 iperf3 iproute2 iputils bash curl
COPY --from=neubot /usr/local/bin/dash-client /usr/local/bin/dash-client
COPY dash-play /usr/local/bin/dash-play
CMD ["sleep", "infinity"]
