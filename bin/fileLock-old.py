import time
import fcntl
import errno
import os
#version = "2.04.03"
#foo

def makeFileIfNotExist(fileName):
    if not os.path.isfile(fileName):
        dir = os.path.dirname(fileName)
        if not os.path.exists(dir):
            os.makedirs(dir)
        file = open(fileName, 'w+')
        file.write("")
        file.close()


def getCurMs():
    return int(round(time.time()*1000))


class FileLock:

    def __init__(self, fileName, mode, timeout=200, encoding=None):
        makeFileIfNotExist(fileName)
        self.fileName = fileName
        self.mode = mode
        self.timeout = timeout
        self.encoding = encoding

    def __enter__(self):
        if self.encoding:
            self.file = open(self.fileName, self.mode, encoding=self.encoding)
        else:
            self.file = open(self.fileName, self.mode)
        self.startTime = getCurMs()

        while True:
            try:
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self.file
            except IOError as e:
                if e.errno != errno.EAGAIN:
                    raise IOError
                elif (getCurMs() > (self.startTime + self.timeout)):
                    raise IOError("File has exclusive lock on it. Tried until timeout")

            time.sleep(.05)

    def __exit__(self, *args):
        fcntl.flock(self.file, fcntl.LOCK_UN)
        self.file.close()
        self.file = None
