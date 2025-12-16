#!/usr/bin/python3
from datetime import datetime
import uuid
import json

import sidraCore

DATA_DIR = "/var/sidra/drv"

ENABLE_FILE = "akiraEnabled.rts"

EXT_READ = ".rts-r"
EXT_TRANS = ".rts-t"

RESPONSE_FILE = "response.log"

DEBUG = True

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

######################
def read(data):
	
	#check wether RTS wants akira data
	if not getEnable():
		print("driverRts.read() akira is disabled, aborting")
		return
	
	xmit = False
	
	# get sensor name for this lane
	thisLane = data['lane']
	thisDtS = data['dt']
	thisDt = sidraCore.rfStrToDt(thisDtS)
	massName = ""
	#print("LANE:" + str(thisLane))
	for mass in sidraCore.massSensors:
		if mass['lane'] == thisLane:
			massName = mass['name']
	
	if massName == "":
		print(f"driverRTS: no mass sensor configured for lane {thisLane}")
		#return
	
	#state = sidraCore.getMass(massName)
	lockState = sidraCore.massLock(massName)
	print(str(lockState))
	
	side = data['side']

	if DEBUG:
		print("driverRTS: tid: " + data['tid'] + " antenna: " + str(side) + " rssi: " + str(data['rssi']))
		
	if data['side'] == "front":
		if not lockState['locked'] == True:
			xmit = True
			print("driverRTS: unlocked - sending FAST read dt: " + str(thisDt))
		else:
			if thisDt < lockState['end'] and thisDt > lockState['begin']:
				print("driverRTS: window - sending FAST read dt: " + str(thisDt))
				xmit = True
			else:
				xmit = False
				print("driverRTS: locked - NOT sending FAST read dt: " + str(thisDt))
			
	if data['side'] == "back":
		if lockState['locked'] == True:
			print("driverRTS: locked sending SLOW read")
			xmit = True
		else:
			print("driverRTS: unlocked - NOT sending SLOW read")
			xmit = False
	
	#dt = datetime.now().isoformat()
	thisDtS = data['dt']
	thisDt = sidraCore.rfStrToDt(thisDtS)
	dt = thisDt.isoformat()
	
	authentic = data['tidAuthentic']
	#JM hardwire authentic for now
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
		
	#else:
	#	thisExt = EXT_TRANS
	#	contents = {
	#		"header": {
	#			"command": "NoTagDetected",
	#			"timestamp": dt,
	#		},
	#		"body": {
	#			"TxID": data['id'],
	#			"TagID": data['tid'],
	#			"PlazaID": sidraCore.plazaId,
	#			"LaneID": data['lane'],
	#			"Result":"01",
	#			"DetectedTime": dt,
	#			"Antenna": side,
	#		},
	#		"hmac": "XXXX",
	#	}
	
	#print("=========================")
	#print(contents)

	if xmit:	
		sidraCore.writeFile(DATA_DIR + "/" + data['id'] + thisExt, json.dumps(contents))
	
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