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

OVERRIDE_AUTH = False

DEBUG = False
DEBUG_XMIT = False

#############################
def setEnable(state = True):
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

				# delete after successful read
				sidraCore.deleteFile(fullPath)

			except Exception as ex:
				sidraCore.log(
					"driverRts.getResponses() error processing "
					+ fname + " : " + str(ex)
				)

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
			
			new = {
				"type":"tagResult",
				"tid":response["body"]["TagID"],
				"date":response["header"]["timestamp"],
				"valid":valid,
				"resultCode":response["body"]["Result"],
				"plaza":response["body"]["PlazaID"],
				"lane":response["body"]["LaneID"],
				"plate":response["body"]["RegPlateNum"]
			}
			parsed.append(new)

	return parsed

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
		authentic == "AUTHENTIC"
	#print("AUTHENTIC? " + str(authentic))
	
	thisExt = EXT_READ
	
	#if authentic == "AUTHENTIC":
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
def trans(data):
	
	#check wether RTS wants akira data
	if not getEnable():
		print("driverRts.read() akira is disabled, aborting")
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
def trans_OLD(data):
	
	#check wether RTS wants akira data
	if not getEnable():
		print("driverRts.read() akira is disabled, aborting")
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
	
	"""
	{
	"header":{
	“command":"ANPRInfo",
	“timestamp":"2025-11-15 12:21:38.431“
	}
	"body":{
	“TxID”:”08ME20251115122138431”,
	“TagID”:”E20034120139FB000D158E5D”,
	“PlazaID”:”PRO_PLZ”,
	“LaneID”:”08ME”,
	“CapturedTime”:”2025-11-15 12:21:39.014”,
	“AnprID”:”LI_PRO_PLZ08ME202511151010852928”,
	“AnprResult”:”WAB1234”,
	“AnprImage”:”
	IkhlbGxvLCB3b3JsZC4gSGVsbG8sIHdvcmxkLiBIZWxsbywgd29ybGQuIg………
	”
	}
	“hmac”:”XXXX”
	}
	
	No Tag Detected:
	{
	"header":{
	“command":"NoTagDetected",
	“timestamp":"2025-11-15 12:21:38.431“
	}
	"body":{
	“TxID”:”08ME20251115122138431”,
	“TagID”:null,
	“PlazaID”:”PRO_PLZ”,
	“LaneID”:”08ME”,
	“Result”:”00”,
	“DetectedTime”:null,
	}
	“hmac”:”XXXX”
	}
	"""

######################
def cam(data):
	
	#check wether RTS wants akira data
	if not getEnable():
		print("driverRts.read() akira is disabled, aborting")
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