import logging

import graypy

from gd_advanced_tools.core.settings import settings as s


handler = graypy.GELFUDPHandler(
    host=s.logging_settings.log_host,
    port=s.logging_settings.log_udp_port,
    facility="python_application",
)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")


app_logger = logging.getLogger("api")
app_logger.setLevel(logging.DEBUG)
handler.setFormatter(formatter)
app_logger.addHandler(handler)


db_logger = logging.getLogger("db")
db_logger.setLevel(logging.DEBUG)
handler.setFormatter(formatter)
db_logger.addHandler(handler)


fs_logger = logging.getLogger("fs")
fs_logger.setLevel(logging.DEBUG)
handler.setFormatter(formatter)
fs_logger.addHandler(handler)
