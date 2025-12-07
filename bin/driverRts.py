#!/usr/bin/python3

import sidraCore

######################
def read(data):
	
	print(data)
	
	stream = False
	
	# get sensor name for this lane
	thisLane = data['lane']
	for mass in sidraCore.massSensors:
		if mass['lane'] == thisLane:
			massName = mass['name']
	
	occupied = sidraCore.massOccupied(massName)
	
	if side = "front":
		if not occupied:
			stream = True
	if side = "rear":
		if occupied:
			stream = True
	
	output = 
		{
		"header":
		{
		"command":"TagDetected",
		"timestamp":dt
		}
		"body":{
		"TxID":data['id'],
		"TagID":data['tid'],
		"PlazaID":sidraCore.plazaId,
		"LaneID":data['lane'],
		"DetectedTime":dt
		}
		"hmac":"XXXX"
		}
	
	writeFile(sidraCore.DIR_STREAM + "/" + data['id'] + ".rts", output)
	
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