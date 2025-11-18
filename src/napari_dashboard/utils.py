import time

import requests


def requests_get(url: str, depth: int = 10):
    """this is util function to workaround a problem with status 500 in vercell"""
    for i in range(1, depth + 1):
        res = requests.get(url)
        if res.status_code != 500:
            return res
        time.sleep(i)  # wait before retrying, longer each time
    raise RuntimeError(f"Failed to get data from the server for {url}")
