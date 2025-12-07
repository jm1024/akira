#!/usr/bin/python3
import psutil
import time
import os
import datetime
#from icmplib import ping
import psutil
import json
import glob
import subprocess

import sidraCore

MON_FILE = "/var/sidra/mon/current"
MON_PATH = "/var/sidra/mon/"

intervals = (
    ('w', 604800),  # 60 * 60 * 24 * 7
    ('d', 86400),    # 60 * 60 * 24
    ('h', 3600),    # 60 * 60
    ('m', 60),
    ('s', 1),
)

##########################################
def ping(host, timeoutMs=500):
    
    try:
        result = subprocess.run(
            ["fping", "-c1", f"-t{timeoutMs}", host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
    
        # fping prints results to stderr
        line = result.stderr.strip()
    
        if result.returncode != 0:
            return 0
    
        # Extract avg latency from: "min/avg/max = A/B/C"
        if "min/avg/max" in line:
            stats = line.split("min/avg/max = ")[1]
            avgLatency = stats.split("/")[1]
            return float(avgLatency)
    
        return 0
    
    except Exception:
        return 0

##########################################
def ps(process_name):

    ret = "DOWN"

    for process in psutil.process_iter(['pid', 'name', 'create_time']):
        if process.info['name'] == process_name:
            createTime = datetime.datetime.fromtimestamp(process.info['create_time'])
            diff = datetime.datetime.now() - createTime
            diffSec = round(diff.total_seconds())
            #print(diffSec)
            sElapsed = displayElapsed(diffSec, 2)
            ret = sElapsed

    return ret

##########################################
def countFiles(dir_path):

    count = 0

    for path in os.listdir(dir_path):
        # check if current path is a file
        if os.path.isfile(os.path.join(dir_path, path)):
            count += 1

    return count

##########################################
def isUp(hostname):

    ret = "DOWN"
    ret = ping(hostname)
    #ret = round(host.avg_rtt,2)
    if ret == 0:
        ret = "DOWN"
    else:
        ret = f'{ret:.2f}'
        ret = str(ret) + " ms"

    return ret #host.packets_sent == host.packets_received

##########################################
def getDirSize(start_path = '.'):
    total_size = 0

    try:
        for dirpath, dirnames, filenames in os.walk(start_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                # skip if it is symbolic link
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
    except:
        return("err")

    return str(round(total_size /1024 /1024)) #+ "m"

##########################################
def getEventCounts():

    countLastHour = 0
    countLastMin = 0

    try:
        dir_entries = os.scandir('/var/sidra/trn/done')
        for entry in dir_entries:
            if entry.is_file():
                last_modified = datetime.datetime.fromtimestamp(entry.stat().st_mtime)
                diff = datetime.datetime.now() - last_modified
                diffSec = diff.total_seconds()
                if diffSec < 3600:
                    countLastHour = countLastHour +1
                if diffSec < 60:
                    countLastMin = countLastMin +1
    except Exception as ex:
        print("monCore: getEventCounts: ERROR:  " + str(ex))

    return countLastMin, countLastHour

##########################################
def getCpu():

    return str(psutil.cpu_percent(.3)) + "%"

##########################################
def clear():

        _ = os.system('clear')

##########################################
def displayElapsed(seconds, granularity=2):
    result = []

    for name, count in intervals:
        value = seconds // count
        if value:
            seconds -= value * count
            result.append("{}{}".format(str(value).rjust(2,' '), name))
    return ' '.join(result[:granularity])

##########################################
def getUps():
    ret = []

    try:
        upsNum = 0
        for file in glob.glob(MON_PATH + "ups-*"):
            upsNum = upsNum +1
            thisUps = {}
            thisUps['number'] = upsNum
            contents = sidraCore.readFile(file)
            lines = contents.split('\n')
            for line in lines:
                #print(line)
                vals = line.split(':')
                if vals[0] == "ups.status":
                    thisUps['status'] = vals[1]
                if vals[0] == "battery.voltage":
                    thisUps['voltage'] = vals[1]
                if vals[0] == "battery.charge":
                    thisUps['charge'] = vals[1]
                if vals[0] == "ups.mfr":
                    thisUps['mfr'] = vals[1]
                if vals[0] == "ups.model":
                    thisUps['model'] = vals[1]
            ret.append(thisUps)
    except Exception as ex:
        print("monCore: getUps: ERROR: " + str(ex))

    return ret


##########################################
def getAll(ipList):

    #get processes
    reader = ps("reader")
    cam = ps("cam")
    mcp = ps("mcp")
    xmit = ps("xmit")

    #get pings
    for ip in ipList:
        ip['state'] = isUp(ip['address'])

    #get stats
    xmitQ = countFiles("/var/sidra/xmit")
    mcpQ = countFiles("/var/sidra/trn")
    img = countFiles("/var/sidra/img")
    du = getDirSize("/var/sidra/img")
    cpu = getCpu()
    epm, eph = getEventCounts()
    ups = getUps()

    data = {
        "pings": ipList,
        "reader": reader,
        "cam": cam,
        "mcp": mcp,
        "xmit": xmit,
        "mcpQ": mcpQ,
        "xmitQ": xmitQ,
        "img": img,
        "du": du,
        "cpu": cpu,
        "epm": epm,
        "eph": eph,
        "ups": ups
    }

    return data







