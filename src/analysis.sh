#! /usr/bin/bash

file=$1

total_video_stream=$(cat $1/* | grep "video stream" | wc -l)
failed_video_stream=$(cat $1/* | grep "video stream" | grep "fail" | wc -l)
failed_video_rate=$(echo "scale=3; $failed_video_stream / $total_video_stream * 100" | bc)

total_other_stream=$(cat $1/* | grep -v "video stream" | wc -l)
failed_other_stream=$(cat $1/* | grep -v "video stream" | grep "fail" | wc -l)
failed_other_rate=$(echo "scale=3; $failed_other_stream / $total_other_stream * 100" | bc)

other_traffic_rate=$(cat $1/*  | grep MB | awk 'BEGIN{FS="-"}{print $2}' | awk '{duration += $1; Mbyte += $3} END {print Mbyte * 8/duration}')

echo ビデオ棄却率：$failed_video_rate %
echo 他トラフィック棄却率：$failed_other_rate %
echo 他トラフィック平均通信速度：$other_traffic_rate Mbps
