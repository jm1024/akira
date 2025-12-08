#!/usr/bin/python3
from datetime import datetime
import json

import sidraCore

DATA_DIR = "/var/sidra/drv"

EXT_READ = ".rts-r"
EXT_TRANS = ".rts-t"

######################
def read(data):
	
	stream = False
	
	# get sensor name for this lane
	thisLane = data['lane']
	print("LANE:" + str(thisLane))
	for mass in sidraCore.massSensors:
		if mass['lane'] == thisLane:
			massName = mass['name']
	
	occupied = sidraCore.massOccupied(massName)
	
	if data['side'] == "front":
		if not occupied:
			stream = True
	if data['side'] == "rear":
		if occupied:
			stream = True
	
	dt = datetime.now().isoformat()
			
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
		},
		"hmac": "XXXX",
	}
	
	print("=========================")
	print(contents)
	
	sidraCore.writeFile(DATA_DIR + "/" + data['id'] + EXT_READ, json.dumps(contents))
	
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
	
	#JM reformat this to their spec
	sidraCore.writeFile(DATA_DIR + "/" + data['id'] + EXT_TRANS, json.dumps(contents))
	