#!/bin/bash

# Supports analysing multiple log files generated by multiple NGAS servers within one test run
# Not that it is a user's responsibility to correlate multiple log files from the same test run

# 1. for all log files, make an overall report (e.g. throughput, average time, etc.)
# 2. for all log files, make a single record (entry) to the performance database. This entry will be used for
#    making curves (e.g. X - number of clients, Y - throughput; X - file size, Y - throughput)
# 3. for each log file, make detailed report and graph
#    3.1 each thread's start and end time as opposed to the total duration time

if [[ $# -lt 1 ]]; then
    echo "Usage: analyseLog.sh <LogFile1> [LogFile2 LogFile3 .... LogFileN]"
    echo "Example: ./analyseLog.sh LogFile.nglog.01 ../../NGAS2/log/LogFile.nglog.01"
    exit 1
fi


#####################################################################
# Evaluate a floating point number expression.

float_scale=3

function fe()
{
    local stat=0
    local result=0.0
    if [[ $# -gt 0 ]]; then
        result=$(echo "scale=$float_scale; $*" | bc -q 2>/dev/null)
        stat=$?
        if [[ $stat -eq 0  &&  -z "$result" ]]; then stat=1; fi
    fi
    echo $result
    return $stat
}

# this will return time difference in seconds
# e.g. time1 = 2012-03-23T15:53:57.834
#      time2 = 2012-03-23T15:54:21.268
# do not support month diff at the moment
# and assum $1 is start, $2 is end
function time_diff()
{
	s_day=$(echo $1 | cut -c9-10)
	s_hr=$(echo $1 | cut -c12-13)
	s_min=$(echo $1 | cut -c15-16)
	s_sec=$(echo $1 | cut -c18-23)

	e_day=$(echo $2 | cut -c9-10)
	e_hr=$(echo $2 | cut -c12-13)
    e_min=$(echo $2 | cut -c15-16)
    e_sec=$(echo $2 | cut -c18-23)
	
	day_gap=$(fe "($e_day - $s_day)");
	re1=$(fe "($e_hr + 24 * $day_gap - $s_hr) * 3600");
	re2=$(fe "($e_min - $s_min) * 60");
	re3=$(fe "($e_sec - $s_sec)");
	result=$(fe "$re1+$re2+$re3")
	echo $result
	return 0
}

function printScreen()
{
    echo "-----------------------------------------------------------------"
    echo -e "Start time: \t\t$start_time"
    echo -e "End time: \t\t\t$end_time"
    echo -e "Total Duration: \t$ttl_duration seconds"
    echo -e "Total throughput: \t$ttl_thruput Bytes/s"
    echo -e "Mean duration: \t\t$avg_duration seconds"
    echo -e "Number of files: \t$no_of_files"
    echo -e "Mean file size: \t$avg_file_size Bytes"
    echo -e "Mean throughput: \t$avg_thruput Bytes/s"
    echo -e "Throughput std: \t$final_std Bytes/s"
    echo "-----------------------------------------------------------------"
    echo -e "\n"
}

# read an HTML template and replace variables with values
function printHTML()
{
    echo ""
}

# this will be imported into database for producing cross-run analysis and curve
function printCSV()
{
    return 0
}

# produce detailed report for each LogFile in the HTML + JavaScript format
function generateDetailedReport()
{
    return 0
}

######################################################################
start_time="z"
end_time="0"
avg_time=0.000
avg_thread_rate=0.000
total_size=0.000
no_of_files=0
agg_std=0.000
std=0.000

# 1. make an overall report
for fname in "$@"
do
     	#echo $fname
	tst=$(grep "Received command: QARCHIVE" $fname | head -1 | awk '{print $1}')
	if [[ "$tst" < "$start_time" ]]; then
		start_time=$tst
	fi
	tet=$(grep "Successfully handled Archive" $fname | tail -1 | awk '{print $1}')
	if [[ "$tet" > "$end_time" ]]; then
		end_time=$tet
	fi

	agg_value=$(grep Rate $fname | awk '{s+=$12; u+=$10; v+=$15; ++t; printf("%s\t%s\t%d\t%ld\n", s,u,v,t)}' | tail -1)
	temp=$(echo "$agg_value" | cut -f1)
	avg_time=$(fe "$avg_time+$temp")

	temp=$(echo "$agg_value" | cut -f2)
	total_size=$(fe "$total_size+$temp")

	temp=$(echo "$agg_value" | cut -f3)
	avg_thread_rate=$(fe "$avg_thread_rate+$temp")

	temp=$(echo "$agg_value" | cut -f4)
	no_of_files=$(($no_of_files+$temp))
done

ttl_duration=$(time_diff "$start_time" "$end_time") 
ttl_thruput=$(fe "$total_size / $ttl_duration")
avg_thruput=$(fe "$avg_thread_rate / $no_of_files")
avg_duration=$(fe "$avg_time / $no_of_files")
avg_file_size=$(fe "$total_size / $no_of_files")

for fname in "$@"
do
	tmp_std=$(grep Rate $fname | awk -v avg=$avg_thruput '{std+=($15 - avg) * ($15 - avg); printf("%f\n", std)}' | tail -1)
	agg_std=$(fe "$agg_std+$tmp_std")
	#echo -e "tmp_std = $tmp_std"
	#echo -e "agg_std = $agg_std"
done
final_std=$(fe "sqrt($agg_std/$no_of_files)")
#echo -e "final_std = $final_std"

printScreen 

# 2. make a detailed report for each Logfile
# what to include?


