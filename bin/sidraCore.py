# Standard libraries
import sys
import subprocess
import os
import base64
import json
import fcntl
from decimal import Decimal
from datetime import date, datetime, timedelta
from urllib import request, parse
import requests
#import psutil

# sidra imports
sys.path.append('/var/sidra/bin')
import fileLock

VERSION = "0.02.06"

#config defaults
sidraApi = ""  #API server to use
plazaId = "000"
laneMode = "single"
eventMargin = 8     #time margin for accepting events as together

#raw config json
config = {}

#list of associated IPs
ipList = []
cams = []
readers = []
massSensors = []
lidar = []
driversRead = []
driversTrans = []
driversServer = []
driversXmit = []
servers = []

#max age of image files before they are purged
imageRetentionSeconds = 36000
trnRetentionSeconds = 36000

BIN_DIR = "/var/sidra/bin"
LOG_DIR = "/var/sidra/log"
ETC_DIR = "/var/sidra/etc"
IMG_DIR = "/var/sidra/img"
ANPR_DIR = "/var/sidra/anpr"
TRN_DIR = "/var/sidra/trn"
TRN_WORKING_DIR = "/var/sidra/trn/working"
TRN_DONE_DIR = "/var/sidra/trn/done"
TRN_TMP_DIR = "/var/sidra/trn/tmp"
XMIT_DIR = "/var/sidra/xmit"
MASS_DIR = "/var/sidra/mass"
STREAM_DIR = "/var/sidra/stream"
LOG_FILE = "sidra.log"
ERR_LOG_FILE = "errors.log"
TRN_LOG_FILE = "transactions.log"
MCP_LOG_FILE = "mcp.log"
CONFIG_FILE = "sidra.cfg"

STATE_EXTENSION_MASS = ".sm"

TRN_EXTENSION_CAM = ".tc"
TRN_EXTENSION_READER = ".tr"
TRN_EXTENSION_LIDAR = ".tl"

QUEUE_EXTENSION_CAM = ".qc"
QUEUE_EXTENSION_READER = ".qr"
QUEUE_EXTENSION_LIDAR = ".ql"
QUEUE_EXTENSION_EVENT = ".qe"

DEVICE_READER = "r"
DEVICE_CAM_FRONT = "cf"
DEVICE_CAM_REAR = "cr"

EVENT_CAM = "cam"
EVENT_RF = "rf"
EVENT_LIDAR = "lidar"

MASS_OCCUPIED = 1
MASS_EMPTY = 0

LANE_MODE_SINGLE = "single"
LANE_MODE_MULTI = "multi"

#absolute positioning
POS_MIN = 0
POS_MAX = 1000

####################################################
# config
####################################################

###############################################################
# config
###############################################################

#########################################
def loadConfig():

    global config


    #system info
    global sidraApi
    global plazaId
    global laneMode
    global driversRead
    global driversTrans
    global driversXmit
    global driversServer
    global ipList
    global cams
    global readers
    global massSensors
    global lidar
    global imageRetentionSeconds
    global logTo
    global logMode

    if not os.path.isfile(ETC_DIR + "/" + CONFIG_FILE):
        log("sidraCore: loadConfig: config missing using defaults")
        return

    #Open and read the JSON file
    with open(ETC_DIR  + "/" + CONFIG_FILE, 'r') as file:
        cfg = json.load(file)

    #save raw json
    config = cfg
    #print(cfg)

    #drivers read
    if not cfg.get("driversRead") == None:
        driversRead = cfg.get("driversRead")

    #drivers server
    if not cfg.get("driversServer") == None:
        driversServer = cfg.get("driversServer")
        
    #drivers trans
    if not cfg.get("driversTrans") == None:
        driversServer = cfg.get("driversTrans")
        
    #drivers xmit
    if not cfg.get("driversXmit") == None:
        driversXmit = cfg.get("driversXmit")
        
    #servers
        if not cfg.get("servers") == None:
            cams = cfg.get("servers")

    if not cfg.get("sidraApi") == None:
        sidraApi = cfg.get("sidraApi")

    # plaza id
    if not cfg.get("plazaId") == None:
        plazaId = cfg.get("plazaId")
        
    # lane mode
    if not cfg.get("laneMode") == None:
        laneMode = cfg.get("laneMode")
        
    #ipList
    if not cfg.get("ipList") == None:
        ipList = cfg.get("ipList")

    #cams
    if not cfg.get("cams") == None:
        cams = cfg.get("cams")

    #readers
    if not cfg.get("readers") == None:
        readers = cfg.get("readers")

    #massSensors
    if not cfg.get("massSensors") == None:
        massSensors = cfg.get("massSensors")

    #lidar
    if not cfg.get("lidar") == None:
        lidar = cfg.get("lidar")

    #device info
    if not cfg.get("deviceName") == None:
        sidraApi = cfg.get("deviceName")

    #max image age
    if not cfg.get("imageRetentionSeconds") == None:
        imageRetentionSeconds = cfg.get("imageRetentionSeconds")

    #max transaction file age
    if not cfg.get("trnRetentionSeconds") == None:
        imageRetentionSeconds = cfg.get("trnRetentionSeconds")


#########################################
    def loadConfig_INI():

        #system info
        global sidraApi
        global plazaId
        global logTo
        global logMode

        if not os.path.isfile(ETC_DIR + "/" + CONFIG_FILE):
            log("config missing loaded defaults")
            return

        f = open(ETC_DIR  + "/" + CONFIG_FILE, 'r')

        for line in f:
            #print(line)
            vals = line.split('=')

            #api server to use
            if vals[0] == "sidraApi":
                sidraApi  = vals[1].rstrip()

            # plaza id
            if vals[0] == "plazaId":
                plazaId = vals[1].rstrip()

            #device info
            if vals[0] == "deviceName":
                deviceName = vals[1].rstrip()

            #logging
            if vals[0] == "logTo":
                logTo  = vals[1].rstrip()
            if vals[0] == "logMode":
                logMode = vals[1].rstrip()



####################################################
# transactions
####################################################

###########################
def saveTransaction(fileName, data):

    with open(TRN_DIR + "/" + fileName, 'w') as f:
        f.write(data + '\n')

###########################
def trnPrefix():

    now = datetime.now()
    ret = str(now.year)
    ret += "-" + str(now.month)
    ret += "-" + str(now.day)
    ret += "-" + str(now.hour)
    ret += "-" + str(now.minute)
    ret += "-" + str(now.second)

    return ret

####################################################
# logging
####################################################

###########################
def log(msg, isError = False):

    if isError:
        fileName = LOG_DIR + "/" + ERR_LOG_FILE
    else:
        fileName = LOG_DIR + "/" + LOG_FILE
    with open(fileName, 'a') as f:
        f.write(msg + '\n')

###########################
def logTrn(msg):

    fileName = LOG_DIR + "/" + TRN_LOG_FILE
    with open(fileName, 'a') as f:
        f.write(msg + '\n')

###########################
def logMcp(msg):

    fileName = LOG_DIR + "/" + MCP_LOG_FILE
    with open(fileName, 'a') as f:
        f.write(msg + '\n')

####################################################
# communication
####################################################

###########################
def queueXmit(payload, extension = ".x"):

    ret = False

    fileName = dtToFlieName(datetime.now()) + str(extension)

    #print(str(len(payload)))
    try:
        with open(XMIT_DIR + "/" + fileName, 'w') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(payload)
            fcntl.flock(f, fcntl.LOCK_UN)
            ret = True
            #print("WF OK ")
    except Exception as ex:
        print("queueXmit error writing file " + str(ex))
        log("queueXmit error writing file " + str(ex))
        ret = False

    # old non locking way
    #try:
    #    with open(XMIT_DIR + "/" + fileName, 'w') as f:
    #        f.write(payload)
    #        ret = True
    #except:
    #    ret = False

    return ret

###########################
def xmitEvent(url, payload):

    #print("----- xmit -----")
    #print(url)
    #print(payload)
    #return

    ret = False
    resp = ""
    code = 0
    try:
        headers = {'Content-type': 'application/json'}
        resp = requests.post(url, headers=headers, data=payload, timeout=5)
        code = resp.status_code
    except Exception as ex:
        code = str(ex)
        log("Error transmitting to API " + str(ex))

    #print(resp)
    if code == 200:
        ret = True
    else:
        ret = False
        log("ERROR xmit " + url + " " + json.loads(payload).get('op') + " resp:" + str(code))

    return ret

####################################################
# get plate and class from tag user data
####################################################
def decodeUserData(userData):

    #0x0129007C0000564442383935330000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000

    tagPlate = ""
    tagClass = ""

    try:
        plateHex = userData[14:28]
        #print(userData)
        #print(plateHex)
        tagPlate = bytearray.fromhex(plateHex).decode()
        tagPlate = tagPlate.strip('\0x00')
        #tagPlate = plateHex.decode("hex")
    except Exception as ex:
        print("err " + str(ex))
        log("decudeUserData() error: " + str(ex) + " userData: " + str(userData))

    return tagPlate, tagClass

####################################################
# get state for a mass sensor
####################################################
def massState(name):

    raw = readFile(MASS_DIR + "/" + name + STATE_EXTENSION_MASS)
    ret = json.loads(raw)

    return ret
    trip = ""
    main = ""
    
###########################
def massOccupied(name):
    
    state = massState(name)
    print("ST: " + str(state))
    occupied = True
    
    for mass in massSensors:
        if name == mass['name']:
            trip = mass['trip']
            main = mass['main']
            
    if state.get(trip) == MASS_EMPTY and state.get(main) == MASS_EMPTY:
        occupied = False
        
    return occupied

####################################################
# image encoding/decoding
####################################################

###############################
def decodeImage(imgStr):

    ret = ""

    bin = base64.b64decode(imgStr)

    return bin

###############################
def encodeImage(imgFile):

    with open(imgFile, "rb") as image_file:
        imgS = base64.b64encode(image_file.read())

    ret = imgS.decode('utf-8')

    return ret

####################################################
# file cleanup
####################################################

######################
def purgeImageFiles():

    files = fileList(IMG_DIR)

    for file in files:
        ageSec = getFileAgeSeconds(IMG_DIR + "/" + file)
        #print(str(ageSec) + " - " + str(imageRetentionSeconds))
        if ageSec > imageRetentionSeconds:
            #print("PURGE " + str(ageSec) + " " + file)
            deleteFile(IMG_DIR + "/" + file)

######################
def purgeTransactionFiles():

    files = fileList(TRN_DONE_DIR)

    for file in files:
        ageSec = getFileAgeSeconds(TRN_DONE_DIR + "/" + file)
        #print(str(ageSec) + " - " + str(imageRetentionSeconds))
        if ageSec > trnRetentionSeconds:
            #print("PURGE " + str(ageSec) + " " + file)
            deleteFile(TRN_DONE_DIR + "/" + file)

######################
def getFileAgeSeconds(file):

    mTime = os.path.getmtime(file)
    dt = datetime.fromtimestamp(mTime) #, tz=timezone.utc)


    diff = datetime.now() - dt
    diffSec = diff.total_seconds()

    return diffSec

####################################################
# device name
####################################################

#################################
def parseDeviceName(name):

    #print("name")

    lName = name.split('.')

    plaza = lName[0]
    lane = lName[1]
    device = lName[2]

    return plaza, lane, device

####################################################
# off by one plate search
####################################################

#################################
def findObo(plateList, plate):
    candidates = [p for p in plateList if sum(a!=b for a,b in zip(plate,p)) == 1]
    return candidates

####################################################
# date time
####################################################

#################################
def timeOffsetMs(dtBegin, dtEnd):

    ret = 0

    diff = dtEnd - dtBegin
    diffSec = round(diff.total_seconds() * 1000)
    ret = diffSec

    return ret

#################################
def camStrToDt(dts):

    ret = ""

    #2024-05-30_12:00:01.053
    try:
        dtFormat = "%Y-%m-%d_%H:%M:%S.%f"
        ret = datetime.strptime(dts, dtFormat)
    except:
        dtFormat = "%Y-%m-%d_%H:%M:%S"
        ret = datetime.strptime(dts, dtFormat)

    return ret

#################################
def rfStrToDt(dts):

    ret = ""

    #2024-10-14T23:27:27.739
    try:
        dtFormat = "%Y-%m-%dT%H:%M:%S.%f"
        ret = datetime.strptime(dts, dtFormat)
    except:
        dtFormat = "%Y-%m-%dT%H:%M:%S"
        ret = datetime.strptime(dts, dtFormat)

    return ret

#ValueError: time data '2025-06-23 02:29.26.049' does not match format '%Y-%m-%dT%H:%M:%S.%f'

#################################
def strToDt(dts):

    ret = ""

    #2024-10-14T23:27:27.739
    try:
        dtFormat = "%Y-%m-%d %H:%M:%S.%f"
        ret = datetime.strptime(dts, dtFormat)
    except:
        #handle for dateTimes with no fractional seconds
        dtFormat = "%Y-%m-%d %H:%M:%S"
        ret = datetime.strptime(dts, dtFormat)

    return ret

#################################
def dtToFlieName(dt):

    ret = str(dt.year) + "."
    ret = ret + str(dt.month) + "."
    ret = ret + str(dt.day) + "."
    ret = ret + str(dt.hour) + "."
    ret = ret + str(dt.minute) + "."
    ret = ret + str(dt.second) + "."
    ret = ret + str(dt.microsecond)

    return ret

####################################################
# scores
####################################################

#################################
def scoreToInt(scoreS):
    ret = 0

    try:
        ret = int(scoreS)
    except:
        #print("ERROR: scoreToInt() - converting score: " + str(scoreS))
        pass

    return ret

####################################################
# json
####################################################

#################################
def jsonConverter(o):
    if isinstance(o, date):
        return o.__str__()
    elif isinstance(o, datetime):
        return o.__str__()
    elif isinstance(o, Decimal):
        return o.__str__()
    else:
        return o.__str__()

####################################################
# dicts
####################################################

#################################
def removeDictKey(d, key):
    r = dict(d)
    del r[key]
    return r

####################################################
# process control
####################################################

#########################################
def isRunning_PSU(process_name):

    ret = False

    #for process in psutil.process_iter(['pid', 'name']):
    #    if process.info['name'] == process_name:
    #        ret = True

    #log("ISRUUNNING: " + process_name + " = " + str(ret))

    return ret

#########################################
def isRunning(process_name):
    cmd = "ps -eaf | grep '" + process_name + "' | grep -v grep"
    ps = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    output = ps.stdout.read().strip()
    ps.stdout.close()
    ps.wait()
    ##print("OUTPUT: " + str(output))
    #log("ISRUUNNING: " + process_name + " = " + str(output))
    if len(output) > 5:
        #log("ISRUUNNING: True")
        return True
    else:
        #log("ISRUUNNING: False")
        return False

###############################################################
# file io
###############################################################

#########################################
def fileExist(path):

    if os.path.isfile(path):
        return True
    else:
        return False

#########################################
def moveFile(fileFrom, fileTo):

    os.replace(fileFrom, fileTo)

#########################################
def deleteFile(fileName):

    os.remove(fileName)

#########################################
def readFile(fileName, encoding=None):

    data = ""

    if os.path.isfile(fileName):
        with fileLock.FileLock(fileName, "r+", encoding=encoding) as f:
            data = f.read()

    return data

#########################################
def writeFile(fileName, data):

    try:
        # temp file to write output to
        #tmpFile = fileName + ".tmp"
        with fileLock.FileLock(fileName, "w") as fw:
        #fw = open(tmpFile, "w")

            fw.write(data)
            ##print "good write to: " + str(fileName)
        #fw.close()

        #move tmp file to prod
        #prodFile = fileName
        #os.rename(tmpFile, prodFile)
        return True
    except Exception as ex:
        log("error writing: " + str(fileName) + "  " + str(ex))
        return False

#########################################
def appendFile(fileName, data):

    try:
        # temp file to write output to
        #tmpFile = fileName + ".tmp"
        with fileLock.FileLock(fileName, "a") as fw:
            #fw.append(data)
            fw.write(data)

        return True
    except Exception as ex:
        log("sidraCore.appendFile error: " + str(fileName) + "  " + str(ex))
        return False

#########################################
def fileList_OLD(path):
    for file in os.listdir(path):
        if os.path.isfile(os.path.join(path, file)):
            yield file

#########################################
def fileList_x2(path, newestFirst=False):

    # collect only real files
    files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]

    if newestFirst:
        files = sorted(
            files,
            key=lambda f: os.path.getmtime(os.path.join(path, f)),
            reverse=True
        )

    for f in files:
        yield f

#########################################
def fileList(path, newestFirst=False, max=None):
    """
    Yield files from a directory.

    Args:
        path (str): Directory path.
        newestFirst (bool): If True, sort by modification time (newest → oldest).
        max (int or None): Maximum number of files to return (after sorting).

    Yields:
        str: File names.
    """

    # Get only actual files
    files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]

    # Apply sorting
    if newestFirst:
        files = sorted(
            files,
            key=lambda f: os.path.getmtime(os.path.join(path, f)),
            reverse=True
        )

    # Apply max limit after sorting
    if max is not None:
        files = files[:max]

    # Maintain generator behavior
    for f in files:
        yield f

#########################################
def fileExists(path):

    if os.path.isfile(path):
        return True
    else:
        return False

#########################################
def makeFileIfNotExist(fileName):

    if not os.path.isfile(fileName):
        file = open(fileName, 'w+')
        file.write("")
        file.close()

#########################################
def makeDir(path):

    if not os.path.exists(path):
        os.makedirs(path)


###################################################################

#load runtime config from etc
loadConfig()

#print("Plaza: " + str(plazaId))
#print("API: " + str(sidraApi))
