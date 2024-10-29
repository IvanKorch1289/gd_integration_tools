from functools import wraps

from loguru import logger
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession

from gd_advanced_tools.src.core.session import CTX_SESSION, get_session
from gd_advanced_tools.src.core.errors import DatabaseError


def transaction(coro):
    @wraps(coro)
    async def inner(*args, **kwargs):
        session: AsyncSession = get_session()
        CTX_SESSION.set(session)

        try:
            result = await coro(*args, **kwargs)
            await session.commit()
            return result
        except DatabaseError as error:
            logger.error(f"Rolling back changes.\n{error}")
            await session.rollback()
            raise DatabaseError
        except (IntegrityError, PendingRollbackError) as error:
            # NOTE: Since there is a session commit on this level it should
            #       be handled because it can raise some errors also
            logger.error(f"Rolling back changes.\n{error}")
            await session.rollback()
        finally:
            await session.close()

    return inner
