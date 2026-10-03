# Brief: lft-dash-video: nginx serving a real DASH ladder (2160p..240p) plus iperf3 -s, as a testbed
# server: lft topology create --preset diamond-video, or lft host add ... --image lft-dash-video --server
# Build: docker build -t lft-dash-video docker/dash_video_server
FROM alpine:3.20 AS encode
RUN apk add --no-cache ffmpeg font-dejavu
COPY encode.sh /encode.sh
RUN sh /encode.sh

FROM nginx:alpine
# bash: the LFT runs its discovery ping through bash -lc
RUN apk add --no-cache bash iperf3 iproute2
COPY --from=encode /video /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
CMD ["sh", "-c", "iperf3 -s -D && exec nginx -g 'daemon off;'"]
