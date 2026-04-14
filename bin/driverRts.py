#!/usr/bin/python3
from datetime import datetime
import uuid
import json
import os

import sidraCore

DATA_DIR = "/var/sidra/drv"

ENABLE_FILE = "akiraEnabled.rts"

EXT_READ = ".rts-r"
EXT_TRANS = ".rts-t"
EXT_RESPONSE = ".rts-resp"

RESPONSE_FILE = "response.log"

OVERRIDE_AUTH = True

DEBUG = False
DEBUG_XMIT = False

TAG_AUTHENTIC = "AUTHENTIC"

RTS_CODES = {"00":"Valid Tag", "01":"Zero Balance", "02":"Insufficient Balance", "03":"Ivalid Tag", "04":"Suspended Tag", "05":"Terminated Tag", "06":"Not Registered Tag", "07":"Last Detected Tag", "99":"Others", }

#############################
def setEnable(state = True):
	try:
		#sidraCore.log(f"{datetime.now()} driverRts.setEnable() {str(state)}") # test this!
		sidraCore.log("driverRts.setEnable() " + str(state))
	except Exception as ex:
		print("driverRts.setEnable() error " + str(ex))
	sidraCore.writeFile(sidraCore.TMP_DIR + "/" + ENABLE_FILE, str(state))

#############################
def getEnable():

	ret = True
	try:
		result = sidraCore.readFile(sidraCore.TMP_DIR + "/" + ENABLE_FILE)
		if result == "False":
			ret = False
	except Exception as ex:
		print("driverRts.getEnable() " + str(ex))

	return ret

#############################
def getResponses():

	responses = []

	try:
		for fname in os.listdir(DATA_DIR):

			# only response files
			if not fname.endswith(EXT_RESPONSE):
				continue

			fullPath = os.path.join(DATA_DIR, fname)

			try:
				# read contents
				data = sidraCore.readFile(fullPath)

				# oJSON-decode
				data = json.loads(data)

				responses.append(data)

			except Exception as ex:
				sidraCore.log("driverRts.getResponses() error processing " + fname + " : " + str(ex))

			# delete file
			sidraCore.deleteFile(fullPath)

	except Exception as ex:
		sidraCore.log("driverRts.getResponses() error listing dir: " + str(ex))

	parsed = []
	try:
		parsed = parseResponses(responses)
		#ignore last tag detected
		#if parsed.get('resultCode','') == "07":
		#	parsed = []

	except Exception as ex:
		err = "driverRts.getResponses() error parsing " + str(ex)
		sidraCore.log(err)
		print(err)

	return parsed

######################
def parseResponses(responses):

	parsed = []

	for response in responses:
		if response["header"]["command"] == "TagResult":

			valid = False
			if response["body"]["Result"] == "00":
				valid = True

			#ignore last tag sent messages
			if response["body"]["Result"] == "07":
				continue

			thisResponseName =  RTS_CODES.get(response["body"]["Result"],"Unknown")

			new = {
				"id":str(uuid.uuid4()),
				"type":"tagResult",
				"tid":response["body"]["TagID"],
				"date":response["header"]["timestamp"],
				"valid":valid,
				"code":response["body"]["Result"],
				"name": thisResponseName,
				"plaza":response["body"]["PlazaID"],
				"lane":response["body"]["LaneID"],
				"plate":response["body"]["RegPlateNum"]
			}
			parsed.append(new)

	return parsed

##################################################################
# driver functions

######################
def read(data):

	#check wether RTS wants akira data
	if not getEnable():
		if DEBUG:
			print("driverRts.read() akira is disabled, aborting")
		return

	xmit = True

	# get sensor name for this lane
	thisLane = data['lane']
	thisDt = data['date']
	#thisDt = sidraCore.rfStrToDt(thisDtS)
	thisTID = data['tid']
	shortTID = thisTID[-5:]
	shortTime = thisDt.time()
	thisRSSI = data['rssi']
	side = data['side']
	massName = ""

	debugInfo = "rts: " + str(shortTID) + " " + str(thisRSSI) + " " + str(shortTime)
	xmitDebug = "driverRTS read: " + str(thisDt) + " tid: " + str(data['tid']) + " antenna: " + str(side) + " rssi: " + str(data['rssi'])

	if DEBUG:
		print(debugInfo)


	if DEBUG_XMIT:
		print(xmitDebug)
		sidraCore.appendFile("/var/sidra/log/rtsDebug.log", xmitDebug + "\n")

	#dt = datetime.now().isoformat()
	#thisDtS = data['date']
	#thisDt = sidraCore.rfStrToDt(thisDtS)
	dt = thisDt.isoformat()

	authentic = data['tidAuthentic']
	#JM hardwire authentic for now
	if OVERRIDE_AUTH:
		if not authentic == TAG_AUTHENTIC:
			print("driverRts - overrideAuth")
		authentic = TAG_AUTHENTIC
	#print("AUTHENTIC? " + str(authentic))

	#hard auth
	#authentic = TAG_AUTHENTIC

	thisExt = EXT_READ

	if authentic == TAG_AUTHENTIC:
		thisExt = EXT_READ
		contents = {
			"header": {
				"command": "TagDetected",
				"timestamp": dt,
			},
			"body": {
				"TxID": data['id'],
				"TagID": data['tid'],
				"PlazaID": sidraCore.plazaId,
				"LaneID": data['lane'],
				"DetectedTime": dt,
				"Antenna": side,
			},
			"hmac": "XXXX",
		}

		if xmit:
			sidraCore.writeFile(DATA_DIR + "/" + data['id'] + thisExt, json.dumps(contents))
			if DEBUG_XMIT:
				print("driverRTS sent: " + str(datetime.now()))


	else:
		print("driverRts.read() INAUTHENTIC TAG")
		thisExt = EXT_READ
		contents = {
			"header": {
				"command": "NoTagDetected",
				"timestamp": dt,
			},
			"body": {
				"TxID": data['id'],
				"TagID": data['tid'],
				"PlazaID": sidraCore.plazaId,
				"LaneID": data['lane'],
				"DetectedTime": dt,
				"Result":"01",
				"Antenna": side,
			},
			"hmac": "XXXX",
		}

		if xmit:
			sidraCore.writeFile(DATA_DIR + "/" + data['id'] + thisExt, json.dumps(contents))
			if DEBUG_XMIT:
				print("driverRTS sent: " + str(datetime.now()))



	"""
	tData = {
		'date': str(dt),
		'reader': reader,
		'lane': lane,
		'side': side,
		'antenna': antenna,
		'ip': readerIp,
		'ts': dt,
		'rssi': rssi,
		'tid': tid,
		'epc': epc,
		'userData': userData,
		'tagPlate': tagPlate,
		'tagClass': tagClass,
		"tidAuthentic": tidAuthentic,
		"pwAuthentic": pwAuthentic,
	}
	"""

######################
def trans_DISABLED(data):

	#check wether RTS wants akira data
	if not getEnable():
		print("driverRts.trans() akira is disabled, aborting")
		return

	#data['img_f'] = ""
	#data['img_fp'] = ""

	msgNTD = ""
	xmit = False
	#No tag detected message
	if data['tid'] == "":
		xmit = True
		msgNTD = {
			'header':{
			'command':"NoTagDetected",
			'timestamp':data['date'].isoformat()
			},
			'body':{
			'TxID':data['id'],
			'TagID':None,
			'PlazaID':data['plaza'],
			'LaneID':data['lane'],
			'Result':"00",
			'DetectedTime':None,
			},
			'hmac':"XXXX"
			}

	if xmit:
		sidraCore.writeFile(DATA_DIR + "/" +data['id'] + EXT_READ, json.dumps(msgNTD, default=sidraCore.jsonConverter))

	msg = ""
	xmit = True

	msg = {
		"header":{
		'command':"ANPRInfo",
		'timestamp':data['date'].isoformat()
		},
		'body':{
		'TxID':data['id'],
		'TagID':data['tid'],
		'PlazaID':data['plaza'],
		'LaneID':data['lane'],
		'CapturedTime':data['date'].isoformat(),
		'AnprID':data['id'],
		'AnprResult':data['plate'],
		'AnprImage':data['img_f']
		},
		'hmac':"XXXX"
		}

	if xmit:
		sidraCore.writeFile(DATA_DIR + "/" + data['id'] + EXT_TRANS, json.dumps(msg, default=sidraCore.jsonConverter))


######################
def noTag(lane, antenna):

	#check wether RTS wants akira data
	if not getEnable():
		print("driverRts.noTag() akira is disabled, aborting")
		return

	#print("NO TAG DETECTED driverRts")

	msgNTD = ""
	transId = str(uuid.uuid4())

	xmit = True
	msgNTD = {
		'header':{
		'command':"NoTagDetected",
		'timestamp':datetime.now().isoformat()
		},
		'body':{
		'TxID':transId,
		'TagID':None,
		'PlazaID':str(sidraCore.plazaId),
		'LaneID':str(lane),
		'Result':"00",
		'Antenna':str(antenna),
		'DetectedTime':None,
		},
		'hmac':"XXXX"
		}

	if xmit:
		sidraCore.writeFile(DATA_DIR + "/" + transId + EXT_READ, json.dumps(msgNTD, default=sidraCore.jsonConverter))

######################
def laneClear(lane):

	#check wether RTS wants akira data
	if not getEnable():
		print("driverRts.laneClear() akira is disabled, aborting")
		return

	msgNTD = ""

	transId = str(uuid.uuid4())

	xmit = True
	msgNTD = {
		'header':{
		'command':"LaneClear",
		'timestamp':datetime.now().isoformat()
		},
		'body':{
		'TxID':transId,
		'PlazaID':str(sidraCore.plazaId),
		'LaneID':str(lane),
		'Result':"00",
		'ClearedTime':datetime.now().isoformat(),
		},
		'hmac':"XXXX"
		}

	if xmit:
		sidraCore.writeFile(DATA_DIR + "/" + transId + EXT_TRANS, json.dumps(msgNTD, default=sidraCore.jsonConverter))

######################
def cam(data):

	#check wether RTS wants akira data
	if not getEnable():
		print("driverRts.cam() akira is disabled, aborting")
		return

	msg = ""
	xmit = True

	print(data)


	dt = sidraCore.camStrToDt(data['transit']['timestamps']['start'])
	#dt = thisDt.isoformat()
	id = str(uuid.uuid4())

	# get dateTime
	try:
		thisDtS = data['transit']['timestamps']["image"]
		thisDt = sidraCore.camStrToDt(thisDtS)
	except:
		thisDt = datetime.now()

	dev    = data.get('device', {})
	device = dev.get('name', 'UNKNOWN')
	lane   = dev.get('lane', 0)

	#get plate
	try:
		plate = data['transit']['plate']['text']
	except:
		plate = DATA_UNKNOWN

	#get plate score
	try:
		plateScore = sidraCore.scoreToInt(data['transit']['plate']['score'])
	except:
		plateScore = 0

	#get images
	imageFile = data['transit']['image']

	imagePlateFile = ""
	try:
		imagePlateFile = data['transit']['image_plate']
		#print("IPF: " + str(imagePlateFile))
	except Exception as ex:
		print("error getting plate image")

	imageBin = ""
	try:
		imageBin = sidraCore.encodeImage(sidraCore.IMG_DIR + "/" + imageFile)
	except Exception as ex:
		sidraCore.log("ERROR: mcp loading main image " + imageFile + " " + str(ex), True)


	msg = {
		"header":{
		'command':"ANPRInfo",
		'timestamp':dt.isoformat()
		},
		'body':{
		'TxID':id,
		'TagID':'',
		'PlazaID':sidraCore.plazaId,
		'LaneID':lane,
		'CapturedTime':dt.isoformat(),
		'AnprID':id,
		'AnprResult':plate, #data['plate'],
		'AnprImage':imageBin
		},
		'hmac':"XXXX"
		}

	if xmit:
		sidraCore.writeFile(DATA_DIR + "/" + id + EXT_TRANS, json.dumps(msg, default=sidraCore.jsonConverter))

######################
def genFakeTagResponse_X(tid):

	#00 = good
	#01 = zero balance
	ret = {}

	ret = {
	  "header": {
		"command": "TagResult",
		"timestamp": datetime.now().isoformat()
	  },
	  "body": {
		"TxID": "d29c4ff1-a6b4-4089-b26f-a94ef1a55aba",
		"TagID": tid,
		"PlazaID": "PRO_PLZ",
		"LaneID": "08ME",
		"Result": "00",
		"AnprID": "LI_PRO_PLZ08ME202601121021311458",
		"RegPlateNum": "VCG4791",
		"RegVehClass": "C1",
		"TagStatus": "A",
		"AcctType": "P",
		"FareAmt": 2.13,
		"AcctBal": 105.68
	  },
	  "hmac": "4V1h0iwzIg6H+0qpAEIlpqn5C2jW9nVuODgOeNiNPTM="
	}

	writeResponse(ret)

#############################
def writeResponse(msg):

	fileName = datetime.now().strftime("%Y%m%d%H%M%S%f") + EXT_RESPONSE
	responseFile = DATA_DIR + "/" + fileName
	sidraCore.writeFile(responseFile, json.dumps(msg))