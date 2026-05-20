# chats/queue_manager.py — FIXED: passes emit_fn + display_phone_number to handler

import threading
import queue
import time
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# RATE LIMITER
# ══════════════════════════════════════════════════════════════

class RateLimiter:
    """Token bucket — allows burst up to `capacity`, refills at `rate` per second"""

    def __init__(self, rate: float = 20, capacity: int = 30):
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last_refill = time.time()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                now = time.time()
                elapsed = now - self._last_refill
                self._tokens = min(
                    self._capacity,
                    self._tokens + elapsed * self._rate
                )
                self._last_refill = now

                if self._tokens >= 1:
                    self._tokens -= 1
                    return

            time.sleep(0.01)


rate_limiter = RateLimiter(rate=20, capacity=30)


# ══════════════════════════════════════════════════════════════
# USER QUEUE MANAGER
# ══════════════════════════════════════════════════════════════

class UserQueueManager:
    """
    Per-user FIFO queue with bounded ThreadPoolExecutor.
    Supports passing sender_phone_number_id, emit_fn, and display_phone_number.
    """

    def __init__(self, max_workers: int = 50, idle_timeout: int = 300, handler_timeout: int = 60):
        self._queues: dict[str, queue.Queue] = {}
        self._active: set[str] = set()
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="wa-worker")
        self._idle_timeout = idle_timeout
        self._handler_timeout = handler_timeout

        logger.info(f"✅ QueueManager started — max_workers={max_workers}")

    def enqueue(
        self,
        phone: str,
        message_data: dict,
        handler_fn,
        sender_phone_number_id: str = None,
        emit_fn=None,
        display_phone_number: str = None
    ):
        """
        Add message to user's queue. Starts a worker if needed.

        Args:
            phone: User's phone number
            message_data: The incoming WhatsApp message data
            handler_fn: Function to process the message
            sender_phone_number_id: Which WhatsApp number received this message
            emit_fn: SocketIO emit function to push bot reply to frontend
            display_phone_number: The room key (display number) for emit
        """
        with self._lock:
            if phone not in self._queues:
                self._queues[phone] = queue.Queue()

            self._queues[phone].put({
                "message_data": message_data,
                "sender_phone_number_id": sender_phone_number_id,
                "handler_fn": handler_fn,
                "emit_fn": emit_fn,
                "display_phone_number": display_phone_number
            })
            queue_size = self._queues[phone].qsize()

            if phone not in self._active:
                self._active.add(phone)
                self._executor.submit(self._worker_loop, phone)
                logger.info(f"🧵 Worker submitted for {phone}")
            else:
                logger.debug(f"📥 Queued for {phone} (depth={queue_size})")

    def _worker_loop(self, phone: str):
        logger.info(f"▶️ Worker started: {phone}")

        while True:
            with self._lock:
                q = self._queues.get(phone)

            if not q:
                logger.warning(f"⚠️ Queue missing for {phone}, exiting worker")
                break

            try:
                item = q.get(timeout=self._idle_timeout)
                message_data = item["message_data"]
                sender_id = item.get("sender_phone_number_id")
                handler_fn = item["handler_fn"]
                emit_fn = item.get("emit_fn")
                display_phone_number = item.get("display_phone_number")
            except queue.Empty:
                with self._lock:
                    if q.empty():
                        self._queues.pop(phone, None)
                        self._active.discard(phone)
                        logger.info(f"🧹 Worker cleaned up: {phone}")
                break

            self._run_with_timeout(handler_fn, message_data, phone, sender_id, emit_fn, display_phone_number)
            q.task_done()

    def _run_with_timeout(
        self,
        handler_fn,
        message_data: dict,
        phone: str,
        sender_id: str = None,
        emit_fn=None,
        display_phone_number: str = None
    ):
        error_holder = [None]

        def target():
            try:
                # Always pass all args; handler decides what to use
                handler_fn(
                    message_data,
                    sender_id,
                    emit_fn=emit_fn,
                    display_phone_number=display_phone_number
                )
            except Exception as e:
                error_holder[0] = e

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(timeout=self._handler_timeout)

        if t.is_alive():
            logger.error(f"⏰ Handler TIMEOUT ({self._handler_timeout}s) for {phone} — message dropped")
        elif error_holder[0]:
            logger.exception(f"❌ Handler error for {phone}: {error_holder[0]}")
        else:
            logger.debug(f"✅ Message processed for {phone}")

    def stats(self) -> dict:
        with self._lock:
            return {
                "active_users": len(self._active),
                "total_queued": sum(q.qsize() for q in self._queues.values()),
            }

    def shutdown(self, wait: bool = True):
        self._executor.shutdown(wait=wait)
        logger.info("🛑 QueueManager shut down")


user_queue_manager = UserQueueManager(max_workers=50)