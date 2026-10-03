#!/bin/sh
# Brief: Fetches the QUALITIES of the dataset's Big Buck Bunny (1 s segments) into /video/1sec, as the
# dataset lays them out (pydash reads the segment length from that folder's name), with a manifest.mpd that
# lists only those, and /video/manifest.mpd pointing into it for dash-play. Usage: fetch.sh <dataset url>
set -e
DATASET=$1
QUALITIES="226106 424520 808057 1662809 2617284 4242923"   # bit/s: 360p, 360p, 720p, 720p, 1080p, 1080p
SEGMENTS=596

mkdir -p /video/1sec && cd /video/1sec
# the dataset's manifest has one Representation per line: keep the ones in QUALITIES
curl -fsS "$DATASET/BigBuckBunny_1s_simple_2014_05_09.mpd" | awk -v keep="$QUALITIES" '
    BEGIN { n = split(keep, q, " "); for (i = 1; i <= n; i++) wanted["bandwidth=\"" q[i] "\""] = 1 }
    /<Representation/ { match($0, /bandwidth="[0-9]+"/); if (!(substr($0, RSTART, RLENGTH) in wanted)) next }
    { print }' > manifest.mpd
for bw in $QUALITIES; do
    mkdir -p "bunny_${bw}bps" && cd "bunny_${bw}bps"
    { echo "$DATASET/bunny_${bw}bps/BigBuckBunny_1s_init.mp4"
      seq 1 $SEGMENTS | sed "s|.*|$DATASET/bunny_${bw}bps/BigBuckBunny_1s&.m4s|"; } | xargs -P 16 -n 20 curl -fsS --remote-name-all
    [ "$(ls | wc -l)" -eq $((SEGMENTS + 1)) ] || { echo "bunny_${bw}bps: incomplete" >&2; exit 1; }
    cd ..
done
sed 's|media="|media="1sec/|; s|initialization="|initialization="1sec/|' manifest.mpd > ../manifest.mpd
