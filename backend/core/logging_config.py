import logging

import graypy

from backend.core.settings import settings as s


handler_api = graypy.GELFUDPHandler(
    host=s.logging_settings.log_host,
    port=s.logging_settings.log_udp_port,
    facility="application",
)
handler_db = graypy.GELFUDPHandler(
    host=s.logging_settings.log_host,
    port=s.logging_settings.log_udp_port,
    facility="database",
)
handler_fs = graypy.GELFUDPHandler(
    host=s.logging_settings.log_host,
    port=s.logging_settings.log_udp_port,
    facility="file_system",
)

formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

app_logger = logging.getLogger("api")
app_logger.setLevel(logging.DEBUG)
handler_api.setFormatter(formatter)
app_logger.addHandler(handler_api)

db_logger = logging.getLogger("db")
db_logger.setLevel(logging.DEBUG)
handler_db.setFormatter(formatter)
db_logger.addHandler(handler_db)

fs_logger = logging.getLogger("fs")
fs_logger.setLevel(logging.DEBUG)
handler_fs.setFormatter(formatter)
fs_logger.addHandler(handler_fs)
