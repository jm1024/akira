import time
import fcntl
import errno
import os

def makeFileIfNotExist(fileName):
    if not os.path.isfile(fileName):
        dir_ = os.path.dirname(fileName) or "."
        if not os.path.exists(dir_):
            os.makedirs(dir_, exist_ok=True)
        # 'a' creates the file if missing without truncating any future content by mistake
        with open(fileName, 'a'):
            pass

def getCurMs():
    return int(round(time.time() * 1000))

class FileLock:
    def __init__(self, fileName, mode, timeout=200, encoding=None):
        makeFileIfNotExist(fileName)
        self.fileName = fileName
        self.mode = mode
        self.timeout = timeout
        self.encoding = encoding
        self.file = None

    def __enter__(self):
        # open first
        if self.encoding:
            f = open(self.fileName, self.mode, encoding=self.encoding)
        else:
            f = open(self.fileName, self.mode)

        # prevent inheriting the fd across exec()
        try:
            fcntl.fcntl(f.fileno(), fcntl.F_SETFD,
                        fcntl.fcntl(f.fileno(), fcntl.F_GETFD) | fcntl.FD_CLOEXEC)
        except Exception:
            # not fatal on some platforms
            pass

        start = getCurMs()
        try:
            while True:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.file = f
                    return f
                except OSError as e:
                    if e.errno != errno.EAGAIN:
                        # not a contention error -> close and re-raise
                        raise
                    if getCurMs() - start > self.timeout:
                        raise TimeoutError("File has exclusive lock on it. Tried until timeout")
                    time.sleep(0.05)
        except Exception:
            #lose on any failure before leaving __enter__
            try:
                f.close()
            finally:
                self.file = None
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        # in case __enter__ failed midway
        if self.file is not None:
            try:
                fcntl.flock(self.file, fcntl.LOCK_UN)
            finally:
                try:
                    self.file.close()
                finally:
                    self.file = None