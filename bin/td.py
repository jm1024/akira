#!/usr/bin/python3
from datetime import date, datetime, timedelta
import time
import json
import base64
import os
import uuid

import sidraCore

thisUD = "0x0129007C0000564442383935330000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
ret = sidraCore.decodeUserData(thisUD)
print(ret)