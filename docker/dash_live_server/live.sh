#!/bin/sh
# Brief: Encodes a live DASH stream into the web root while nginx serves it: testsrc2 at 25 fps in
# LADDER's qualities, CBR so each one really costs its bitrate on the wire, with resolution, bitrate and
# the clock burned into the picture; 2 s segments, the last 30 s kept. Players pick the quality by the
# throughput they measure (dash-play). ffmpeg restarts if it stops.
FONT=/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf
OUT=/usr/share/nginx/html
# height width kbit/s label
LADDER="1080 1920 4500 4,5
720 1280 2500 2,5
480 854 1200 1,2
360 640 700 0,7
240 426 300 0,3"

n=$(echo "$LADDER" | wc -l)
graph="[0:v]split=$n$(i=0; while [ $i -lt $n ]; do printf '[s%d]' $i; i=$((i+1)); done)"
maps=""
i=0
while read -r h w kbit label; do
    printf '%sp · %s Mbps\n%%{gmtime:%%H\\:%%M\\:%%S} UTC' "$h" "$label" > /tmp/label$i.txt
    graph="$graph;[s$i]scale=$w:$h,drawtext=fontfile=$FONT:textfile=/tmp/label$i.txt:fontsize=$((h/9)):line_spacing=$((h/40)):fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=$((h/60)):x=(w-tw)/2:y=(h-th)/2[v$i]"
    maps="$maps -map [v$i] -b:v:$i ${kbit}k -minrate:v:$i ${kbit}k -maxrate:v:$i ${kbit}k -bufsize:v:$i ${kbit}k"
    i=$((i+1))
done <<LADDER_END
$LADDER
LADDER_END

iperf3 -s -D
while true; do
    ffmpeg -loglevel error -re -f lavfi -i testsrc2=size=1920x1080:rate=25 -filter_complex "$graph" $maps \
        -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -g 50 -keyint_min 50 -sc_threshold 0 \
        -f dash -seg_duration 2 -window_size 15 -extra_window_size 5 -remove_at_exit 1 \
        -use_template 1 -use_timeline 0 -adaptation_sets "id=0,streams=v" "$OUT/manifest.mpd"
    sleep 1
done &
exec nginx -g 'daemon off;'
