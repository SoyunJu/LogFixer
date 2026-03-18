import logging
import time

from fastapi import Request

logger = logging.getLogger(__name__)

 ######### Logging (http -> main.py) #######################
async def logging_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = round((time.time() - start) * 1000, 1)

    logger.info(
        "[HTTP] %s %s → %d (%sms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response