#!/bin/sh
# Brief: Encodes the DASH ladder into /video: testsrc2, 60 s at 30 fps, 2 s segments, CBR so each
# rendition really costs its bitrate on the wire, with resolution and bitrate burned into the picture
set -e
FONT=/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf
# height width kbit/s label
LADDER="2160 3840 16000 16
1440 2560 9000 9
1080 1920 4500 4,5
720 1280 2500 2,5
480 854 1200 1,2
360 640 700 0,7
240 426 300 0,3"

n=$(echo "$LADDER" | wc -l)
graph="[0:v]split=$n$(i=0; while [ $i -lt $n ]; do printf '[s%d]' $i; i=$((i+1)); done)"
maps=""
i=0
echo "$LADDER" | while read -r h w kbit label; do
    printf '%sp · %s Mbps\n%%{pts:hms}' "$h" "$label" > /tmp/label$i.txt
    i=$((i+1))
done
i=0
while read -r h w kbit label; do
    graph="$graph;[s$i]scale=$w:$h,drawtext=fontfile=$FONT:textfile=/tmp/label$i.txt:fontsize=$((h/9)):line_spacing=$((h/40)):fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=$((h/60)):x=(w-tw)/2:y=(h-th)/2[v$i]"
    maps="$maps -map [v$i] -b:v:$i ${kbit}k -minrate:v:$i ${kbit}k -maxrate:v:$i ${kbit}k -bufsize:v:$i ${kbit}k"
    i=$((i+1))
done <<LADDER_END
$LADDER
LADDER_END

mkdir -p /video
ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc2=size=3840x2160:rate=30:duration=60 \
    -filter_complex "$graph" $maps \
    -c:v libx264 -preset veryfast -profile:v high -pix_fmt yuv420p -x264-params nal-hrd=cbr \
    -r 30 -g 60 -keyint_min 60 -sc_threshold 0 \
    -f dash -seg_duration 2 -use_template 1 -use_timeline 0 -adaptation_sets "id=0,streams=v" \
    -init_seg_name 'init-$RepresentationID$.m4s' -media_seg_name 'chunk-$RepresentationID$-$Number%05d$.m4s' \
    /video/manifest.mpd
