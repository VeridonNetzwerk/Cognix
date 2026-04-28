"""Bot IPC."""

from bot.ipc.consumer import IpcConsumer
from bot.ipc.schemas import IpcAck, IpcMessage

__all__ = ["IpcAck", "IpcConsumer", "IpcMessage"]
