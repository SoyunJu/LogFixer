
import asyncio
import logging
from typing import Optional

import paramiko

from app.core.config import settings

logger = logging.getLogger(__name__)


async def run_ssh_command(
        host: str,
        command: str,
        user: Optional[str] = None,
        key_path: Optional[str] = None,
        timeout: int = 30,
) -> tuple[bool, str]:

    user = user or settings.SSH_DEFAULT_USER
    key_path = key_path or settings.SSH_DEFAULT_KEY_PATH

    def _run() -> tuple[bool, str]:
        client = paramiko.SSHClient()
        # 처음 접속하는 서버도 자동으로 known_hosts에 추가
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=host,
                username=user,
                key_filename=key_path,
                timeout=timeout,
            )
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            exit_code = stdout.channel.recv_exit_status()

            if exit_code == 0:
                logger.info("[SSH] 성공 host=%s cmd='%s'", host, command[:80])
                return True, out
            else:
                logger.warning("[SSH] 실패 host=%s cmd='%s' err=%s", host, command[:80], err[:200])
                return False, err

        except Exception as e:
            logger.error("[SSH] 접속/실행 오류 host=%s err=%s", host, e)
            return False, str(e)
        finally:
            client.close()

    # FastAPI 이벤트 루프 블로킹 방지
    return await asyncio.to_thread(_run)