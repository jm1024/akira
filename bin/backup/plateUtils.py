from datetime import date, datetime, timedelta
import math
import re

#easily misread characters
CONFUSIONS = {
    ('0','O'), ('O','0'),
    ('1','I'), ('I','1'), ('1','L'), ('L','1'),
    ('2','Z'), ('Z','2'),
    ('5','S'), ('S','5'),
    ('6','G'), ('G','6'),
    ('8','B'), ('B','8'),
    ('7','T'), ('T','7'),
}

MAX_TIME_DELTA = 2000 # max allowable time delta for scoring
MAX_POS_DELTA = 5 # max position delta
WEIGHT_TIME = 0.7 # weight time is given
WEIGHT_POS = 0.3 # weight position is given
WEIGHT_SMOOTHING = 1.5

SCORE_MID = 50 #default score to be used if facing is different

DEBUG = False

#######################################
def timeDiff(a, b):
    # Positive, absolute delta in milliseconds
    return abs((a - b).total_seconds() * 1000.0)

#######################################
def getTDscore(candidate, target):
    """
    Return a number in [0,100], where:
      0   -> exact match on time & position
      100 -> outside limits or worst within limits
    combines normalized deltas with weights.
    """

    # Guard rails (missing data -> worst score)
    if 'date' not in candidate or 'date' not in target:
        return 100.0
    if candidate.get('pos') is None or target.get('pos') is None:
        return 100.0

    dt_ms = timeDiff(target['date'], candidate['date'])
    dx    = abs(target['pos'] - candidate['pos'])

    # Hard limits
    if dt_ms > MAX_TIME_DELTA or dx > MAX_POS_DELTA:
        return 100.0

    # Normalize into [0..1]
    nt = (dt_ms / MAX_TIME_DELTA) ** WEIGHT_SMOOTHING
    nx = (dx    / MAX_POS_DELTA) ** WEIGHT_SMOOTHING

    # Weighted blend, then scale to 0..100
    denom = (WEIGHT_TIME + WEIGHT_POS) or 1.0
    score = 100.0 * (WEIGHT_TIME * nt + WEIGHT_POS * nx) / denom

    #return
    return round(score, 2)

#######################################
def normalize(p: str) -> str:
    return ''.join(ch for ch in p.upper() if ch.isalnum())

#######################################
# --- Levenshtein distance ---
def levenshtein(a: str, b: str) -> int:
    la, lb = len(a), len(b)
    dp = list(range(lb + 1))
    for i in range(1, la + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, lb + 1):
            cur = dp[j]
            cost = 0 if a[i-1] == b[j-1] else 1
            dp[j] = min(dp[j] + 1,      # deletion
                        dp[j-1] + 1,    # insertion
                        prev + cost)    # substitution
            prev = cur
    return dp[lb]

#######################################
def isMatch(plate1: str, plate2: str, score: int) -> bool:
    """
    decide if two plates match based on fuzzy similarity

    Args:
        plate1 (str): first plate string
        plate2 (str): second plate string
        score (int): 0..100
            - 100 = strict (almost exact match)
            - 0   = very lenient

    Returns:
        bool: True if considered a match, False otherwise
    """

    # normalize plates (uppercase, strip spaces/hyphens)
    p1, p2 = normalize(plate1), normalize(plate2)

    # exact check
    if p1 == p2:
        return True

    dist = levenshtein(p1, p2)
    max_len = max(len(p1), len(p2), 1)
    similarity = 1 - dist / max_len  # 1.0 = exact, 0.0 = no overlap

    # map score to threshold
    # higher score => require higher similarity
    # score=100 -> threshold=0.95, score=0 -> threshold=0.50
    threshold = 0.50 + 0.45 * (score / 100.0)

    return similarity >= threshold

#######################################
def findMatches(candidates, target):

    ret = []
    if DEBUG:
        print("target: " + str(target['plate']) + " facing: " + str(target['facing']) + " pos: " + str(target['pos']) + " date: " + str(target['date']))

    for candidate in candidates:
        if DEBUG:
            print("checking: " + candidate['plate'] + " facing: " + str(candidate['facing']) + " score: " + str(candidate['plateScore'])  + " pos: " + str(candidate['pos']) + " date: " + str(candidate['date']))
        #frontCams - be more leinent based on a time/position score
        if target['facing'] == candidate['facing']:
            tdScore = getTDscore(candidate, target)
            if tdScore < 100:
                if isMatch(target['plate'], candidate['plate'], tdScore):
                    ret.append(candidate['plate'])
            if DEBUG:
                print("score: " + str(tdScore))
        else:
            if isMatch(target['plate'], candidate['plate'], 50): #assume 50 as a match score
                ret.append(candidate['plate'])

    return ret